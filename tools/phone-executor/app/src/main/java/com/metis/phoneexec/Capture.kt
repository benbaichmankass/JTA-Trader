package com.metis.phoneexec

import android.graphics.Bitmap
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.util.Base64
import android.webkit.WebView
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONArray
import org.json.JSONObject
import java.io.ByteArrayOutputStream
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.TimeZone

/**
 * STEP CAPTURES (PHONE-EXEC-OBSERVABLE-1018; operator 2026-10-18: "the app must know what it is doing, record its
 * own actions WITHOUT anything popping up on screen, and show what it did right and wrong").
 *
 * At each step of a flow (positions read, row find, tap, sheet open, field set, confirm / abort) the app records
 *   (a) an OFF-SCREEN bitmap of its own WebView -- the view is drawn to a Canvas; no MediaProjection, no system
 *       screenshot, nothing shown or asked on screen. Never on a credential screen (the caller passes allowBitmap
 *       from [credentialScreen]; this guards what the APP sends off the phone and is not a screenshot block -- the app
 *       sets no FLAG_SECURE since 2026-11-12, operator). The redaction rectangles exec.js returns
 *       with the snapshot (account ids, balances, equity, P&L: every masked text) are painted BLACK on the device
 *       before the image is encoded -- the operator's decision is that nothing of that kind leaves the phone;
 *   (b) a sanitized DOM snapshot (exec.js __ex.snapshot: visible elements with geometry, attributes, React
 *       handlers; digits kept only under price / quantity / trigger contexts), the material the real-page fixtures
 *       are built from.
 * Both go to POST /api/bot/prop/phone/capture (server-only storage, 7-day TTL, never git). A capture never throws
 * into the flow, never blocks it and never changes what the flow does: it is evidence, not a gate.
 */
class CaptureRun(val flow: String, val ticket: String) {
    val id: String = Capture.runId(flow, ticket)
    var seq = 0
    var posted = 0
    var failed = 0
}

object Capture {
    const val MAX_W = 720
    const val JPEG_Q = 55
    const val MAX_NODES = 2200
    @Volatile var posted = 0          // process-wide count for the heartbeat
    @Volatile var lastError = ""

    private val STAMP = SimpleDateFormat("yyyyMMdd'T'HHmmss'Z'", Locale.US).apply { timeZone = TimeZone.getTimeZone("UTC") }

    /** `<flow>-<ticket>-<UTC stamp>`, within the server's run_id charset ([A-Za-z0-9][A-Za-z0-9._-]{2,79}): the amend
     *  id's "#" becomes "-" and anything else outside the charset is dropped. Pure (CaptureTest). */
    fun runId(flow: String, ticket: String, at: Date = Date()): String {
        val f = flow.lowercase().replace(Regex("[^a-z0-9]"), "").ifEmpty { "flow" }
        val t = ticket.replace("#", "-").replace(Regex("[^A-Za-z0-9._-]"), "").trim('.', '-').ifEmpty { "na" }.take(48)
        return "$f-$t-${STAMP.format(at)}".take(80)
    }

    /** A page that must NEVER be captured as an image: any page off the trade host (the portal / login) and any page with a
     *  password or e-mail field, a code / number-matching step or a challenge. This is the ONLY gate on the app's OWN
     *  self-captures uploaded to the VM (PHONE-SELF-SCREENSHOTS, operator 2026-11-07): "the terminal reads ready" no longer
     *  decides it, because an unrecognised layout is exactly when the image is needed. It is NOT a screenshot block: the
     *  operator's own system screenshots are never blocked (FLAG_SECURE removed, operator 2026-11-12). Pure (CaptureTest). */
    fun credentialScreen(host: String, pw: Boolean, email: Boolean, codeWait: Boolean, challenged: Boolean): Boolean =
        !(host == "trade.breakoutprop.com" || host.endsWith(".trade.breakoutprop.com")) || pw || email || codeWait || challenged

    /** The page-shape hash exec.js puts first in its structure dump ("shape:<8 hex>"), or "" when absent. Pure. */
    fun shapeOf(first: String): String = if (Regex("^shape:[0-9a-f]{8}$").matches(first)) first else ""

    /** An anomaly capture is due for a NEW page shape at once, and for the same shape only every [everyMs] (one new layout
     *  = one capture, not one a minute). Pure. */
    fun anomalyDue(shape: String, lastShape: String, now: Long, lastMs: Long, everyMs: Long): Boolean =
        shape != lastShape || now - lastMs >= everyMs

    /** The server's step charset ([a-z][a-z0-9_]{1,39}). */
    fun stepName(s: String): String {
        val x = s.lowercase().replace(Regex("[^a-z0-9_]"), "_").trimStart('_', '0', '1', '2', '3', '4', '5', '6', '7', '8', '9')
        return (if (x.length < 2) "step_$x" else x).take(40)
    }

    /** Luma standard deviation (0..255) of packed ARGB pixels. A uniform frame (an all-white or all-black draw: the
     *  off-screen WebView draw that rendered nothing) reads ~0; a real terminal page reads well above [BLANK_STD].
     *  Pure (CaptureTest). PHONE-SELF-DIAGNOSE: every image says whether it is blank, so a lane never has to ask. */
    fun lumaStd(px: IntArray): Double {
        if (px.isEmpty()) return 0.0
        var sum = 0.0; var sq = 0.0
        for (c in px) {
            val y = 0.299 * ((c shr 16) and 0xFF) + 0.587 * ((c shr 8) and 0xFF) + 0.114 * (c and 0xFF)
            sum += y; sq += y * y
        }
        val m = sum / px.size
        return Math.sqrt(maxOf(0.0, sq / px.size - m * m))
    }
    const val BLANK_STD = 4.0
    /** The last image's luma std, read by [step] right after [bitmap] (same coroutine, main thread). -1 = not measured. */
    @Volatile var lastStd = -1.0

    /** The page draw for one step: the WebView drawn to an ARGB bitmap, scaled to MAX_W wide, the redaction boxes
     *  painted, JPEG-encoded. [redact] is the snapshot's rect list in CSS px of a [vw]-wide viewport. Null when the
     *  view has no size (never attached) or anything fails. Main thread (it touches the view). */
    fun bitmap(web: WebView, redact: JSONArray?, vw: Double): ByteArray? {
        val w = web.width; val h = web.height
        if (w <= 0 || h <= 0) return null
        return try {
            val full = Bitmap.createBitmap(w, h, Bitmap.Config.ARGB_8888)
            web.draw(Canvas(full))
            val scale = if (w > MAX_W) MAX_W.toDouble() / w else 1.0
            val bmp = if (scale < 1.0) Bitmap.createScaledBitmap(full, (w * scale).toInt().coerceAtLeast(1), (h * scale).toInt().coerceAtLeast(1), true) else full
            // measured BEFORE the redaction boxes are painted: black boxes on a blank draw would read as content
            lastStd = try {
                val sw = bmp.width.coerceAtMost(96); val sh = bmp.height.coerceAtMost(192)
                val small = Bitmap.createScaledBitmap(bmp, sw, sh, false)
                val px = IntArray(sw * sh); small.getPixels(px, 0, sw, 0, 0, sw, sh)
                if (small !== bmp) small.recycle()
                lumaStd(px)
            } catch (e: Throwable) { -1.0 }
            if (redact != null && redact.length() > 0 && vw > 0) {
                val kk = bmp.width.toDouble() / vw   // CSS px -> bitmap px
                val c = Canvas(bmp); val paint = Paint().apply { color = Color.BLACK; style = Paint.Style.FILL }
                for (i in 0 until redact.length()) {
                    val r = redact.optJSONArray(i) ?: continue
                    if (r.length() < 4) continue
                    val l = (r.optDouble(0) * kk - 2).toFloat(); val t = (r.optDouble(1) * kk - 2).toFloat()
                    val rw = (r.optDouble(2) * kk + 4).toFloat(); val rh = (r.optDouble(3) * kk + 4).toFloat()
                    if (rw > 0 && rh > 0) c.drawRect(l, t, l + rw, t + rh, paint)
                }
            }
            val out = ByteArrayOutputStream()
            bmp.compress(Bitmap.CompressFormat.JPEG, JPEG_Q, out)
            if (bmp !== full) bmp.recycle()
            full.recycle()
            out.toByteArray()
        } catch (e: Throwable) { lastError = "bitmap:" + e.javaClass.simpleName; null }
    }

    /** One step: snapshot (always, when the page answers), bitmap (when allowed), then the POST. Returns whether the
     *  server stored it; never throws, never longer than the page's own js timeout + the HTTP timeout. */
    suspend fun step(api: Api, p: Page, run: CaptureRun, step: String, ok: Boolean?, note: String,
                     allowBitmap: Boolean, scope: String = "page", appVersion: String = ""): Boolean {
        val seq = run.seq++
        val body = JSONObject().put("run_id", run.id).put("flow", run.flow).put("step", stepName(step)).put("seq", seq)
            .put("ok", ok ?: JSONObject.NULL).put("note", note.take(300)).put("ticket_id", run.ticket.take(80))
            .put("app_version", appVersion.take(24)).put("page", if (p === fgPage) "fg" else "bg")
        var snap: JSONObject? = null
        try { p.ensure(); snap = p.obj("__ex.snapshot(${JSONObject.quote(scope)}, $MAX_NODES)") } catch (e: Exception) { lastError = "snap:" + e.javaClass.simpleName }
        if (snap != null) body.put("dom", snap)
        // FAIL CLOSED: the redaction boxes come from the snapshot of the SAME page. No snapshot = no redaction list = no image
        // (an unredacted bitmap would show balances); the DOM-less step is still posted as evidence.
        if (allowBitmap && snap != null) {
            lastStd = -1.0
            val jpg = bitmap(p.web, snap?.optJSONArray("redact"), snap?.optDouble("vw", 0.0) ?: 0.0)
            if (jpg != null) {
                val b64 = withContext(Dispatchers.Default) { Base64.encodeToString(jpg, Base64.NO_WRAP) }
                body.put("png_b64", b64).put("png_type", "image/jpeg")
                if (lastStd >= 0) body.put("img_std", Math.round(lastStd * 10) / 10.0)
            }
        }
        body.put("img_why", when {
            body.has("png_b64") -> "drawn"
            !allowBitmap -> "credential_screen"
            snap == null -> "no_snapshot"
            else -> "draw_failed:" + lastError.take(40)
        })
        val r = api.capture(body)
        val stored = r?.optBoolean("ok") == true
        if (stored) { run.posted += 1; posted += 1 } else { run.failed += 1; lastError = "post:" + (r?.optString("why")?.ifEmpty { "http " + r.optInt("http") } ?: "unreachable") }
        return stored
    }

    /** The kiosk page, set by MainActivity so a capture can label fg vs bg without a back-reference. */
    @Volatile var fgPage: Page? = null
}

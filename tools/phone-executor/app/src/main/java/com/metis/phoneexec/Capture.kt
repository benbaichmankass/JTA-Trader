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
 *       only while the terminal reads logged in and FLAG_SECURE is off). The redaction rectangles exec.js returns
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

    /** The server's step charset ([a-z][a-z0-9_]{1,39}). */
    fun stepName(s: String): String {
        val x = s.lowercase().replace(Regex("[^a-z0-9_]"), "_").trimStart('_', '0', '1', '2', '3', '4', '5', '6', '7', '8', '9')
        return (if (x.length < 2) "step_$x" else x).take(40)
    }

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
        if (allowBitmap) {
            val jpg = bitmap(p.web, snap?.optJSONArray("redact"), snap?.optDouble("vw", 0.0) ?: 0.0)
            if (jpg != null) {
                val b64 = withContext(Dispatchers.Default) { Base64.encodeToString(jpg, Base64.NO_WRAP) }
                body.put("png_b64", b64).put("png_type", "image/jpeg")
            }
        }
        val r = api.capture(body)
        val stored = r?.optBoolean("ok") == true
        if (stored) { run.posted += 1; posted += 1 } else { run.failed += 1; lastError = "post:" + (r?.optString("why")?.ifEmpty { "http " + r.optInt("http") } ?: "unreachable") }
        return stored
    }

    /** The kiosk page, set by MainActivity so a capture can label fg vs bg without a back-reference. */
    @Volatile var fgPage: Page? = null
}

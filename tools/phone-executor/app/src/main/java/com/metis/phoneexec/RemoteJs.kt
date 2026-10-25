package com.metis.phoneexec

import android.content.Context
import net.i2p.crypto.eddsa.EdDSAEngine
import net.i2p.crypto.eddsa.EdDSAPublicKey
import net.i2p.crypto.eddsa.spec.EdDSANamedCurveTable
import net.i2p.crypto.eddsa.spec.EdDSAPublicKeySpec
import org.json.JSONObject
import java.io.File
import java.security.MessageDigest

/**
 * SIGNED REMOTE LOGIC (PHONE-EXEC-OBSERVABLE-1018, piece 4; operator 2026-10-18): exec.js -- the page-side logic,
 * where every one of the last four guess-fixes lived -- is fetched from OUR OWN API at startup and every
 * [REFRESH_MS], pinned by version, verified with the ed25519 public key embedded in this APK, and swapped in
 * without a reinstall. The bundled copy is the fallback at every step (absent key, unreachable server, bad
 * signature, older version). Native / Kotlin changes still need an APK.
 *
 * Contract (server: GET /api/bot/prop/phone/exec.js?have=<version>, per-device bearer; signing: CI, key in
 * Actions secrets, phone-exec-js-sign.yml):
 *   message = "metis-exec-js\n" + version + "\n" + sha256hex(js bytes)
 *   sig     = ed25519(message), base64
 *   pubkey  = the raw 32-byte ed25519 public key, base64, in assets/exec_pubkey.b64 (written by the APK job; an
 *             APK built without it runs the bundled copy only: "disabled")
 * The version is the `var EXEC_VERSION = "YYYY-MM-DD.N";` line inside exec.js itself, so file and version cannot
 * drift apart; the same version is never injected twice (exec.js checks window.__ex.version).
 *
 * [ExecJs] holds the source every Page injects (Page.ensure re-injects when the page's __ex.version differs), so
 * a verified update takes effect on the next page call of every WebView without a restart.
 */
object ExecJs {
    @Volatile var src: String = ""
    @Volatile var version: String = ""
    @Volatile var source: String = "bundled"   // bundled | remote
}

object RemoteJs {
    const val PUBKEY_ASSET = "exec_pubkey.b64"
    const val CACHE_JS = "exec.remote.js"
    const val CACHE_META = "exec.remote.meta.json"
    const val REFRESH_MS = 30 * 60_000L
    private val VERSION_RE = Regex("""var EXEC_VERSION = "(\d{4}-\d{2}-\d{2}\.\d+)";""")
    private val VERSION_SHAPE = Regex("""^\d{4}-\d{2}-\d{2}\.\d+$""")

    /** The `var EXEC_VERSION = "..."` pin inside a script, or "" when absent (then the script is never accepted). */
    fun versionOf(src: String): String = VERSION_RE.find(src)?.groupValues?.get(1) ?: ""

    fun message(version: String, sha256Hex: String): String = "metis-exec-js\n$version\n$sha256Hex"

    fun sha256Hex(s: String): String =
        MessageDigest.getInstance("SHA-256").digest(s.toByteArray(Charsets.UTF_8)).joinToString("") { "%02x".format(it) }

    /** `a` is strictly newer than `b`: by date, then by the counter. Malformed versions are never newer. */
    fun newer(a: String, b: String): Boolean {
        if (!VERSION_SHAPE.matches(a)) return false
        if (!VERSION_SHAPE.matches(b)) return true
        val (da, na) = a.split("."); val (db, nb) = b.split(".")
        return if (da != db) da > db else na.toInt() > nb.toInt()
    }

    /** ed25519 verify of [message] against the raw 32-byte public key (base64) and the base64 signature. False on
     *  anything malformed; never throws. */
    fun verify(pubKeyB64: String, message: String, sigB64: String): Boolean = try {
        val pub = java.util.Base64.getDecoder().decode(pubKeyB64.trim())
        val sig = java.util.Base64.getDecoder().decode(sigB64.trim())
        if (pub.size != 32 || sig.size != 64) false else {
            val spec = EdDSANamedCurveTable.getByName(EdDSANamedCurveTable.ED_25519)
            val key = EdDSAPublicKey(EdDSAPublicKeySpec(pub, spec))
            val eng = EdDSAEngine(MessageDigest.getInstance(spec.hashAlgorithm))
            eng.initVerify(key); eng.update(message.toByteArray(Charsets.UTF_8)); eng.verify(sig)
        }
    } catch (e: Exception) { false }

    /** Accept a candidate script: version pinned inside it, signature over (version, sha256) valid for [pubKeyB64]. */
    fun accept(pubKeyB64: String, js: String, version: String, sigB64: String): Boolean {
        if (pubKeyB64.isEmpty() || js.isEmpty() || version.isEmpty()) return false
        if (versionOf(js) != version) return false
        return verify(pubKeyB64, message(version, sha256Hex(js)), sigB64)
    }

    class Loaded(val src: String, val version: String, val source: String)

    fun pubKey(c: Context): String = try { c.assets.open(PUBKEY_ASSET).bufferedReader().readText().trim() } catch (e: Exception) { "" }

    /** Startup: the bundled script, or the cached remote one when it re-verifies and is newer. */
    fun load(c: Context, bundled: String): Loaded {
        val bv = versionOf(bundled)
        var out = Loaded(bundled, bv, "bundled")
        val pk = pubKey(c)
        if (pk.isNotEmpty()) try {
            val js = File(c.filesDir, CACHE_JS).takeIf { it.exists() }?.readText()
            val meta = File(c.filesDir, CACHE_META).takeIf { it.exists() }?.readText()?.let { JSONObject(it) }
            if (js != null && meta != null) {
                val v = meta.optString("version"); val sig = meta.optString("sig")
                if (accept(pk, js, v, sig) && newer(v, bv)) out = Loaded(js, v, "remote")
            }
        } catch (e: Exception) { /* a bad cache is ignored; the bundled copy runs */ }
        ExecJs.src = out.src; ExecJs.version = out.version; ExecJs.source = out.source
        return out
    }

    /** One refresh: ask the server for a newer signed script than [ExecJs.version]; verify, cache, swap. Returns a
     *  short diag token: disabled | unreachable | unchanged | unsigned | bad_sig | not_newer | updated <v>. */
    suspend fun refresh(c: Context, api: Api): String {
        val pk = pubKey(c)
        if (pk.isEmpty()) return "disabled"
        val r = api.execJs(ExecJs.version) ?: return "unreachable"
        if (!r.optBoolean("ok")) return r.optString("why").ifEmpty { "refused" }.take(24)
        if (r.optBoolean("unchanged")) return "unchanged"
        val js = r.optString("js"); val v = r.optString("version"); val sig = r.optString("sig")
        if (js.isEmpty() || v.isEmpty()) return "unsigned"
        if (!accept(pk, js, v, sig)) return "bad_sig"
        if (!newer(v, ExecJs.version)) return "not_newer"
        try {
            File(c.filesDir, CACHE_JS).writeText(js)
            File(c.filesDir, CACHE_META).writeText(JSONObject().put("version", v).put("sig", sig).put("sha256", sha256Hex(js)).toString())
        } catch (e: Exception) { /* not cached: it still runs this process */ }
        ExecJs.src = js; ExecJs.version = v; ExecJs.source = "remote"
        return "updated $v"
    }
}

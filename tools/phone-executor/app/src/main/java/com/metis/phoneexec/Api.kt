package com.metis.phoneexec

import android.content.Context
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONArray
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL

/** The VM contract (the /api/bot/prop/phone routes), per-device bearer. HTTPS only. Errors return null (fail closed). */
class Api(private val c: Context) {
    private fun base(): String = (Store.get(c, Store.API) ?: Store.DEFAULT_API).trimEnd('/')

    suspend fun post(path: String, body: JSONObject = JSONObject()): JSONObject? = withContext(Dispatchers.IO) {
        try {
            val u = URL(base() + "/api/bot/prop/phone/" + path)
            if (u.protocol != "https") return@withContext null
            val conn = u.openConnection() as HttpURLConnection
            conn.requestMethod = "POST"
            conn.connectTimeout = 10000; conn.readTimeout = 20000
            conn.setRequestProperty("Content-Type", "application/json")
            conn.setRequestProperty("Authorization", "Bearer " + Store.token(c))
            conn.doOutput = true
            conn.outputStream.use { it.write(body.toString().toByteArray()) }
            val code = conn.responseCode
            val txt = (if (code in 200..299) conn.inputStream else conn.errorStream)?.bufferedReader()?.readText() ?: ""
            if (code !in 200..299) JSONObject().put("ok", false).put("http", code) else JSONObject(txt)
        } catch (e: Exception) { null }
    }

    /** A GET on the phone routes with the per-device bearer; null on anything but 2xx JSON (fail closed). */
    suspend fun get(pathAndQuery: String): JSONObject? = withContext(Dispatchers.IO) {
        try {
            val u = URL(base() + "/api/bot/prop/phone/" + pathAndQuery)
            if (u.protocol != "https") return@withContext null
            val conn = u.openConnection() as HttpURLConnection
            conn.connectTimeout = 10000; conn.readTimeout = 20000
            conn.setRequestProperty("Authorization", "Bearer " + Store.token(c))
            if (conn.responseCode !in 200..299) null else JSONObject(conn.inputStream.bufferedReader().readText())
        } catch (e: Exception) { null }
    }

    /** What waits for this device, read while the Activity is backgrounded (claims nothing). */
    class Pending(val n: Int, val statusAgeH: Double?, val drill: String?)

    /** READ-ONLY peek used while the Activity is backgrounded: tickets waiting for this device's account, or null
     *  when the VM is unreachable / refused. Claims nothing (the claim happens only once the Activity is resumed).
     *  [Pending.statusAgeH]: the VM's account_status age in hours (null when the server did not say; older servers
     *  don't), so the backgrounded app brings itself forward to check its login when that age is stale.
     *  [Pending.drill] (PHONE-EXEC-OBSERVABLE-1018): the id of a REHEARSAL drill the server wants run, else null. */
    suspend fun pendingInfo(amends: Boolean = true): Pending? {
        // accepts=amend: this build executes trail amends (PROP-TRAIL-PHONE), so a waiting amend wakes it too.
        // amends=false (PHONE-FGS-EXEC step 2): entry tickets only; the difference is the amend count.
        val j = get("pending" + if (amends) "?accepts=amend" else "") ?: return null
        val n = j.optInt("pending", -1)
        if (n < 0) return null
        val drill = j.optJSONObject("drill")?.optString("id")?.takeIf { it.isNotEmpty() }
        return Pending(n, if (j.isNull("status_age_hours")) null else j.optDouble("status_age_hours").takeIf { !it.isNaN() }, drill)
    }

    /** PHONE-EXEC-OBSERVABLE-1018: one step capture (Capture.kt); the body carries the snapshot + the JPEG. */
    suspend fun capture(body: JSONObject): JSONObject? = post("capture", body)

    /** The signed page-side script newer than [have], or {ok, unchanged} (RemoteJs). */
    suspend fun execJs(have: String): JSONObject? = get("exec.js?have=" + java.net.URLEncoder.encode(have, "UTF-8"))

    /** Claim the pending REHEARSAL drill (atomic, one run per request id); {ok, drill:{...}} or drill null. */
    suspend fun drillClaim(): JSONObject? = post("drill/claim")

    /** The drill's per-step result + the capture run id. */
    suspend fun drillResult(body: JSONObject): JSONObject? = post("drill/result", body)

    suspend fun event(kind: String, reason: String = "", ticket: String = "") =
        post("event", JSONObject().put("event", kind).put("reason", reason.take(150)).put("ticket_id", ticket))

    /** Heartbeat: the on-screen status line + the app's own state (quiet; latest kept server-side). */
    suspend fun heartbeat(statusLine: String, state: JSONObject) =
        post("event", JSONObject().put("event", "heartbeat").put("reason", statusLine.take(150)).put("state", state))

    /** "terminal did not load": the page's control texts (our own UI labels, digits masked page-side). */
    suspend fun terminalMiss(reason: String, controls: JSONArray) =
        post("event", JSONObject().put("event", "terminal_miss").put("reason", reason.take(150)).put("controls", controls))

    /** Account panel read (balance / equity as MEASURED off the terminal). Null fields stay absent, never 0.
     *  PROP-TRACKING (2026-10-12): plus the terminal's own unrealized P&L when it labels one, the Positions read
     *  (state + rows: symbol, side, qty, entry, mark, uPnL) and the Closed orders read. The server owns every derivation
     *  (account uPnL, journal reconcile); the phone only reports what the page showed and the state of each read. */
    suspend fun accountStatus(balance: Double?, equity: Double?, equityLabel: String,
                              unrealized: Double? = null, positions: JSONObject? = null, closed: JSONObject? = null) =
        post("report", JSONObject().put("kind", "account_status").put("source", "phone_executor")
            .put("provenance", "MEASURED").put("equity_label", equityLabel)
            .put("balance", balance ?: JSONObject.NULL).put("equity", equity ?: JSONObject.NULL)
            .apply { if (unrealized != null) put("unrealized", unrealized) }
            .put("positions_state", positions?.optString("state")?.ifEmpty { null } ?: "not_read")
            .apply {
                // side_unread (BREAKOUT-POS-UNPARSED): every row parsed but its side; the server may take the side
                // from the journal (ESTIMATED) or keep the read as a label
                if (positions != null && positions.optString("state") in listOf("read", "side_unread")) {
                    put("positions", positions.optJSONArray("rows") ?: JSONArray())
                    if (positions.has("count") && !positions.isNull("count")) put("positions_count", positions.optInt("count"))
                }
                if (closed != null && closed.optString("state") == "read") put("closed_orders", closed.optJSONArray("rows") ?: JSONArray())
            })

    /** Positions read that was NOT "read": the state + digit-masked headers / control texts (no value), so the next
     *  build can be fixed from the dump. The server keeps the latest per account. An unparsed read also sends its first
     *  failing row as digit-masked key:shape cells (BREAKOUT-POS-UNPARSED). */
    suspend fun positionsMiss(state: String, headers: JSONArray, controls: JSONArray, cells: JSONArray = JSONArray()) =
        post("event", JSONObject().put("event", "positions_miss").put("reason", state.take(40))
            .put("headers", headers).put("controls", controls).put("cells", cells))
}

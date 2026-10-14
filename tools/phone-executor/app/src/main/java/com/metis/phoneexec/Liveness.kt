package com.metis.phoneexec

import android.content.Context

/**
 * LIVENESS (PHONE-KEEPALIVE, operator 2026-10-13: "the executor must know how to stay open INDEFINITELY").
 *
 * MEASURED 2026-10-13: breakout_2's heartbeat stopped at ~15:16Z and the next event was `app_started` at 18:48Z, when the
 * operator reopened the app (~3.5 h). The tick loop lived in MainActivity's coroutine scope; `onDestroy` cancels it, and
 * KeepAliveService (START_STICKY) only ever relaunched the Activity on boot/update. So once the Activity (or the whole
 * process) was gone, the foreground service could stay "alive" or be restarted by the OS while NOTHING was ticking.
 *
 * The fix is a watchdog the loop does not own: the service (and an AlarmManager chain) check this record, and when the
 * loop has not ticked for LOOP_STALE_MS they restart it or relaunch the Activity. Everything here is non-secret
 * (timestamps and short reasons), so plain SharedPreferences, not the encrypted Store.
 *
 * The decision itself is a pure function ([decide]) so it is unit-tested on the JVM.
 */
object Liveness {
    /** The loop ticks every 30 s and every long job heartbeats; 10 min of nothing is a wedge, not a slow phone. */
    const val LOOP_STALE_MS = 10 * 60_000L
    /** An Activity launch is not repeated before this (it takes a moment to create and mark its first tick). */
    const val RELAUNCH_MIN_MS = 90_000L
    const val SERVICE_CHECK_MS = 60_000L
    const val ALARM_MS = 5 * 60_000L
    private const val KEEP = 40
    private const val DAY_MS = 24 * 3_600_000L

    enum class Action { OK, RESTART_LOOP, LAUNCH_ACTIVITY }

    /** Pure. [activityAlive] = the Activity object exists in this process (its loop can be restarted in place). */
    fun decide(now: Long, lastTickMs: Long, activityAlive: Boolean, lastLaunchMs: Long): Action {
        if (!activityAlive) return if (now - lastLaunchMs >= RELAUNCH_MIN_MS) Action.LAUNCH_ACTIVITY else Action.OK
        // never ticked (0) counts as stale: a fresh Activity marks its first tick in onCreate, so this is a real wedge
        return if (now - lastTickMs > LOOP_STALE_MS) Action.RESTART_LOOP else Action.OK
    }

    /** Pure. Entries are "epochMs|reason"; counts those inside the last 24 h. */
    fun restartsIn24h(entries: List<String>, now: Long): Int =
        entries.count { (it.substringBefore('|').toLongOrNull() ?: 0L) > now - DAY_MS }

    /** Pure. Appends and trims to the newest KEEP entries. */
    fun appendRestart(entries: List<String>, now: Long, reason: String): List<String> =
        (entries + "$now|${reason.replace('|', '/').replace('\n', ' ').take(48)}").takeLast(KEEP)

    // ---- process-wide state (the service and the Activity share one process) ----
    @Volatile var fgsRunning = false

    private fun p(c: Context) = c.getSharedPreferences("exec_live", Context.MODE_PRIVATE)

    fun markTick(c: Context) { p(c).edit().putLong("tick", System.currentTimeMillis()).apply() }
    fun lastTick(c: Context): Long = p(c).getLong("tick", 0L)
    fun markLaunch(c: Context) { p(c).edit().putLong("launch", System.currentTimeMillis()).apply() }
    fun lastLaunch(c: Context): Long = p(c).getLong("launch", 0L)

    @Synchronized fun recordRestart(c: Context, reason: String) {
        val cur = (p(c).getString("restarts", "") ?: "").split(',').filter { it.isNotBlank() }
        p(c).edit().putString("restarts", appendRestart(cur, System.currentTimeMillis(), reason).joinToString(",")).apply()
    }

    private fun entries(c: Context) = (p(c).getString("restarts", "") ?: "").split(',').filter { it.isNotBlank() }
    fun restarts24h(c: Context): Int = restartsIn24h(entries(c), System.currentTimeMillis())
    fun lastRestartReason(c: Context): String = entries(c).lastOrNull()?.substringAfter('|') ?: ""
}

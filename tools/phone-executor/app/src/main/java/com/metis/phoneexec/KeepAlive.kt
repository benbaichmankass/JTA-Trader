package com.metis.phoneexec

import android.app.AlarmManager
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.net.Uri
import android.os.Build
import android.os.IBinder
import android.os.PowerManager
import android.provider.Settings
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch

/** Visible foreground service: keeps the process alive and is the WATCHDOG for the tick loop (PHONE-KEEPALIVE).
 *
 *  Every [Liveness.SERVICE_CHECK_MS] (and on every start, including the OS's sticky restart and the AlarmManager
 *  chain below) it asks [Liveness.decide]: loop wedged -> restart it in place; Activity gone -> relaunch it (allowed
 *  because the operator granted "Display over other apps"). It also keeps a persistent notification up, naming the
 *  exact thing to tap, for as long as battery exemption or the overlay permission is missing. */
class KeepAliveService : Service() {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main)
    private var watch: Job? = null

    override fun onBind(i: Intent?): IBinder? = null

    override fun onCreate() { super.onCreate(); Liveness.fgsRunning = true }

    override fun onDestroy() { Liveness.fgsRunning = false; scope.cancel(); super.onDestroy() }

    override fun onStartCommand(i: Intent?, flags: Int, startId: Int): Int {
        val nm = getSystemService(NotificationManager::class.java)
        nm.createNotificationChannel(NotificationChannel("exec", "Executor", NotificationManager.IMPORTANCE_LOW))
        nm.createNotificationChannel(NotificationChannel("exec_attn", "Executor needs a tap", NotificationManager.IMPORTANCE_HIGH))
        val open = PendingIntent.getActivity(this, 0, Intent(this, MainActivity::class.java)
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK), PendingIntent.FLAG_IMMUTABLE)
        val n = Notification.Builder(this, "exec").setContentTitle("Metis executor running")
            .setContentText(i?.getStringExtra("status") ?: "kiosk active").setSmallIcon(android.R.drawable.stat_notify_sync)
            .setOngoing(true).setContentIntent(open).build()
        if (Build.VERSION.SDK_INT >= 34) startForeground(1, n, ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE)
        else startForeground(1, n)
        scheduleAlarm(this)
        // null intent = the OS restarted a killed service (START_STICKY): the Activity (and with it the loop) is gone
        val reason = i?.getStringExtra("reason") ?: if (i == null) "service_sticky_restart" else null
        if (reason != null && reason != "alarm" && reason != "app") Liveness.recordRestart(this, reason)
        if (i?.getBooleanExtra("launch", false) == true) { Liveness.markLaunch(this); launchActivity(this, watchdog = false) }
        else watchdog(reason ?: "start")
        if (watch?.isActive != true) watch = scope.launch { while (true) { delay(Liveness.SERVICE_CHECK_MS); watchdog("service_tick") } }
        return START_STICKY
    }

    /** One watchdog pass. Runs on the main thread (the Activity's loop is restarted from there). */
    private fun watchdog(why: String) {
        attention()
        val act = MainActivity.instance
        val now = System.currentTimeMillis()
        when (Liveness.decide(now, Liveness.lastTick(this), act != null, Liveness.lastLaunch(this))) {
            Liveness.Action.OK -> {}
            Liveness.Action.RESTART_LOOP -> { Liveness.recordRestart(this, "loop_stale($why)"); act?.restartLoop("watchdog") }
            Liveness.Action.LAUNCH_ACTIVITY -> {
                if (!Settings.canDrawOverlays(this)) return   // attention() already says what to tap; nothing else can start it
                Liveness.recordRestart(this, "activity_missing($why)"); Liveness.markLaunch(this); launchActivity(this, watchdog = true)
            }
        }
    }

    /** Persistent "tap here" notifications, one per missing grant; they clear themselves once the grant is given. */
    private fun attention() {
        val nm = getSystemService(NotificationManager::class.java)
        val pm = getSystemService(PowerManager::class.java)
        fun post(id: Int, ok: Boolean, title: String, text: String, intent: Intent) {
            if (ok) { nm.cancel(id); return }
            val pi = PendingIntent.getActivity(this, id, intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK), PendingIntent.FLAG_IMMUTABLE)
            nm.notify(id, Notification.Builder(this, "exec_attn").setContentTitle(title).setContentText(text)
                .setStyle(Notification.BigTextStyle().bigText(text)).setSmallIcon(android.R.drawable.stat_sys_warning)
                .setOngoing(true).setContentIntent(pi).build())
        }
        post(2, pm.isIgnoringBatteryOptimizations(packageName), "Executor: allow unrestricted battery",
            "Tap this, then tap ALLOW on the prompt. Without it Android can stop the executor while the screen is off.",
            Intent(Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS, Uri.parse("package:$packageName")))
        post(3, Settings.canDrawOverlays(this), "Executor: allow display over other apps",
            "Tap this, find Metis Executor and switch ON \"Allow display over other apps\". Without it the executor cannot restart itself.",
            Intent(Settings.ACTION_MANAGE_OVERLAY_PERMISSION, Uri.parse("package:$packageName")))
    }

    companion object {
        fun start(c: Context, launch: Boolean, reason: String? = null) {
            c.startForegroundService(Intent(c, KeepAliveService::class.java).putExtra("launch", launch).apply {
                if (reason != null) putExtra("reason", reason)
            })
        }

        /** Bring the kiosk Activity (and its loop) back. [watchdog] = it goes to the back again unless touched. */
        fun launchActivity(c: Context, watchdog: Boolean) {
            if (!Settings.canDrawOverlays(c)) return
            try { c.startActivity(Intent(c, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK).putExtra("watchdog", watchdog)) }
            catch (e: Exception) { /* the next check retries */ }
        }

        /** The independent chain: fires even if the service and the Activity are both gone. Exact when the OS lets this
         *  app use exact alarms, else the Doze-tolerant inexact one (delivered within a maintenance window). */
        fun scheduleAlarm(c: Context) {
            try {
                val am = c.getSystemService(AlarmManager::class.java)
                val pi = PendingIntent.getBroadcast(c, 77, Intent(c, WatchdogReceiver::class.java),
                    PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
                val at = System.currentTimeMillis() + Liveness.ALARM_MS
                if (exactAlarmOk(c)) am.setExactAndAllowWhileIdle(AlarmManager.RTC_WAKEUP, at, pi)
                else am.setAndAllowWhileIdle(AlarmManager.RTC_WAKEUP, at, pi)
            } catch (e: Exception) { /* the service's own 60 s loop still runs */ }
        }

        fun exactAlarmOk(c: Context): Boolean =
            Build.VERSION.SDK_INT < 31 || c.getSystemService(AlarmManager::class.java).canScheduleExactAlarms()
    }
}

/** AlarmManager callback: re-arm FIRST (so the chain survives anything below), then make sure the service is up. */
class WatchdogReceiver : BroadcastReceiver() {
    override fun onReceive(c: Context, i: Intent) {
        KeepAliveService.scheduleAlarm(c)
        try { KeepAliveService.start(c, launch = false, reason = "alarm") }
        catch (e: Exception) {
            // a background FGS start can be refused; the Activity relaunch (overlay) is the other way back
            if (MainActivity.instance == null &&
                Liveness.decide(System.currentTimeMillis(), Liveness.lastTick(c), false, Liveness.lastLaunch(c)) == Liveness.Action.LAUNCH_ACTIVITY) {
                Liveness.recordRestart(c, "activity_missing(alarm_no_fgs)"); Liveness.markLaunch(c)
                KeepAliveService.launchActivity(c, watchdog = true)
            }
        }
    }
}

class BootReceiver : BroadcastReceiver() {
    override fun onReceive(c: Context, i: Intent) {
        if (i.action == Intent.ACTION_BOOT_COMPLETED || i.action == Intent.ACTION_MY_PACKAGE_REPLACED) {
            KeepAliveService.scheduleAlarm(c)
            KeepAliveService.start(c, launch = true, reason = if (i.action == Intent.ACTION_BOOT_COMPLETED) "boot" else "app_update")
        }
    }
}

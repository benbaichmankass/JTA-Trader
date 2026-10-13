package com.metis.phoneexec

import org.junit.Assert.assertEquals
import org.junit.Test

class LivenessTest {
    private val now = 10_000_000_000L
    private val min = 60_000L

    @Test fun freshTickIsOk() =
        assertEquals(Liveness.Action.OK, Liveness.decide(now, now - 2 * min, true, 0L))

    @Test fun staleTickRestartsTheLoopInPlace() =
        assertEquals(Liveness.Action.RESTART_LOOP, Liveness.decide(now, now - 11 * min, true, 0L))

    @Test fun exactlyAtThresholdIsStillOk() =
        assertEquals(Liveness.Action.OK, Liveness.decide(now, now - Liveness.LOOP_STALE_MS, true, 0L))

    @Test fun neverTickedWithALiveActivityIsAWedge() =
        assertEquals(Liveness.Action.RESTART_LOOP, Liveness.decide(now, 0L, true, 0L))

    @Test fun noActivityLaunchesIt() =
        assertEquals(Liveness.Action.LAUNCH_ACTIVITY, Liveness.decide(now, now - 1 * min, false, now - 5 * min))

    @Test fun launchIsNotRepeatedInsideTheGrace() =
        assertEquals(Liveness.Action.OK, Liveness.decide(now, 0L, false, now - 30_000L))

    @Test fun restartsAreCountedOverTheLastDayOnly() {
        val day = 24 * 60 * min
        val e = listOf("${now - day - 1}|old", "${now - 3 * 60 * min}|loop_stale", "${now - min}|activity_missing", "garbage")
        assertEquals(2, Liveness.restartsIn24h(e, now))
    }

    @Test fun appendTrimsAndSanitises() {
        var l = emptyList<String>()
        for (i in 0 until 60) l = Liveness.appendRestart(l, now + i, "r|$i\nx")
        assertEquals(40, l.size)
        assertEquals(false, l.last().substringAfter('|').contains('|'))
        assertEquals(false, l.last().contains('\n'))
    }
}

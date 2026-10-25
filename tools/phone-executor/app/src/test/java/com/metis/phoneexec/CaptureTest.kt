package com.metis.phoneexec

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.util.Date

/** The capture naming rules (PHONE-EXEC-OBSERVABLE-1018): run ids and step names inside the server's charsets. */
class CaptureTest {
    private val runRe = Regex("^[A-Za-z0-9][A-Za-z0-9._-]{2,79}$")
    private val stepRe = Regex("^[a-z][a-z0-9_]{1,39}$")

    @Test fun runIdIsInTheServerCharsetAndCarriesTheAmendId() {
        val at = Date.from(java.time.Instant.parse("2026-10-18T12:00:00Z"))
        val id = Capture.runId("amend", "prop-manual-c1dba3c376b3#a7", at)
        assertEquals("amend-prop-manual-c1dba3c376b3-a7-20261018T120000Z", id)
        assertTrue(runRe.matches(id))
        assertTrue(runRe.matches(Capture.runId("drill", "drill-2026-10-18-abc", at)))
        assertTrue(runRe.matches(Capture.runId("entry", "", at)))
        assertTrue(runRe.matches(Capture.runId("", "weird ticket!!/..", at)))
        assertTrue(Capture.runId("positions", "x".repeat(200), at).length <= 80)
    }

    @Test fun stepNamesAreInTheServerCharset() {
        for (s in listOf("positions_tab", "child_entry/native", "Sheet Open", "9lives", "", "tap:child_tpsl", "x".repeat(60))) {
            assertTrue("'$s' -> '${Capture.stepName(s)}'", stepRe.matches(Capture.stepName(s)))
        }
        assertEquals("child_entry_native", Capture.stepName("child_entry/native"))
        assertEquals("sheet_open", Capture.stepName("Sheet Open"))
    }
}

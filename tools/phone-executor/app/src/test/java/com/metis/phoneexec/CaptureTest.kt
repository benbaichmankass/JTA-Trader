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

    // PHONE-SELF-SCREENSHOTS: the ONLY bitmap gate is "is this a credential screen".
    @Test fun credentialScreensAreNeverCaptured() {
        val host = "trade.breakoutprop.com"
        assertTrue(Capture.credentialScreen(host, pw = true, email = false, codeWait = false, challenged = false))
        assertTrue(Capture.credentialScreen(host, pw = false, email = true, codeWait = false, challenged = false))
        assertTrue(Capture.credentialScreen(host, pw = false, email = false, codeWait = true, challenged = false))
        assertTrue(Capture.credentialScreen(host, pw = false, email = false, codeWait = false, challenged = true))
        assertTrue("the portal / login host", Capture.credentialScreen("breakoutprop.com", false, false, false, false))
        assertTrue("an unrelated host", Capture.credentialScreen("evil.example", false, false, false, false))
        assertTrue("a look-alike suffix", Capture.credentialScreen("nottrade.breakoutprop.com.evil.io", false, false, false, false))
        assertTrue("an unreadable page has no host", Capture.credentialScreen("", false, false, false, false))
    }

    @Test fun anUnrecognisedTerminalIsCapturedBecauseNoReadyOrLoginStateGatesIt() {
        // the 2026-11-07 case: logged in on the trade host, no password / code field, the terminal NOT ready
        assertEquals(false, Capture.credentialScreen("trade.breakoutprop.com", pw = false, email = false, codeWait = false, challenged = false))
    }

    @Test fun anomalyCaptureIsOncePerShapeThenSlow() {
        val every = 1_800_000L
        assertTrue("first shape", Capture.anomalyDue("shape:a5b22a08", "", 1_000L, 0L, every))
        assertEquals("same shape a minute later", false, Capture.anomalyDue("shape:a5b22a08", "shape:a5b22a08", 61_000L, 1_000L, every))
        assertTrue("a new layout at once", Capture.anomalyDue("shape:deadbeef", "shape:a5b22a08", 62_000L, 1_000L, every))
        assertTrue("same shape after 30 min", Capture.anomalyDue("shape:a5b22a08", "shape:a5b22a08", 1_801_000L, 1_000L, every))
    }

    @Test fun shapeIsTheHashLineOnly() {
        assertEquals("shape:a5b22a08", Capture.shapeOf("shape:a5b22a08"))
        assertEquals("", Capture.shapeOf("Trade"))
        assertEquals("", Capture.shapeOf("shape:zzzzzzzz"))
        assertEquals("", Capture.shapeOf(""))
    }

    @Test fun lumaStdSeparatesABlankDrawFromAPage() {
        assertEquals(0.0, Capture.lumaStd(IntArray(500) { 0xFFFFFFFF.toInt() }), 1e-9)
        assertEquals(0.0, Capture.lumaStd(IntArray(500) { 0xFF000000.toInt() }), 1e-9)
        assertEquals(0.0, Capture.lumaStd(IntArray(0)), 1e-9)
        // half dark, half light: a real page has text and panels
        val page = IntArray(500) { if (it % 2 == 0) 0xFF202833.toInt() else 0xFFE0E0E0.toInt() }
        assertTrue(Capture.lumaStd(page) > Capture.BLANK_STD)
    }
}

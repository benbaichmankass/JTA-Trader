package com.metis.phoneexec

import org.junit.Assert.assertEquals
import org.junit.Test

class BgTicketTest {
    private val now = 10_000_000_000L

    @Test fun engineIsTheDefault() =
        assertEquals(BgTicket.Route.ENGINE, BgTicket.route(now, 0, 0L))

    @Test fun twoUnansweredEngineJobsGoToTheFront() =
        assertEquals(BgTicket.Route.FRONT, BgTicket.route(now, 2, 0L))

    @Test fun aFallbackWindowGoesToTheFrontThenExpires() {
        assertEquals(BgTicket.Route.FRONT, BgTicket.route(now, 0, now + 1))
        assertEquals(BgTicket.Route.ENGINE, BgTicket.route(now, 0, now))
    }

    @Test fun cleanEndsDoNotCount() {
        for (s in listOf(null, "dry_filled", "placed", "skipped")) assertEquals(s, false, BgTicket.countsAgainst("entry", s))
        for (s in listOf("amended", "dry_amended", "no_position", "human_moved")) assertEquals(s, false, BgTicket.countsAgainst("amend", s))
    }

    @Test fun entryRefusalsAndMidFillStopsCount() {
        for (s in listOf("refused", "contained", "intended", "submitted", "unconfirmed", "?")) assertEquals(s, true, BgTicket.countsAgainst("entry", s))
    }

    @Test fun amendRefusalsAreExpectedButPageFailuresCount() {
        assertEquals(false, BgTicket.countsAgainst("amend", "refused"))
        for (s in listOf("intended", "submitted", "unconfirmed")) assertEquals(s, true, BgTicket.countsAgainst("amend", s))
    }

    @Test fun amendsGoToTheFrontEntriesStay() {
        assertEquals(false, BgTicket.frontForAmends(0, 0))
        assertEquals(false, BgTicket.frontForAmends(null, null))
        assertEquals(false, BgTicket.frontForAmends(2, 2))   // entries only: the engine
        assertEquals(true, BgTicket.frontForAmends(1, 0))    // one amend
        assertEquals(true, BgTicket.frontForAmends(3, 2))    // an amend among entries: the front handles both
        assertEquals(true, BgTicket.frontForAmends(1, null)) // kinds unread: the front
    }
}

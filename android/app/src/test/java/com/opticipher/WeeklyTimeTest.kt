package com.opticipher

import org.junit.Assert.assertEquals
import org.junit.Test
import java.time.ZonedDateTime

class WeeklyTimeTest {
    @Test fun laterInTheWeekDoesNotSkipAWeek() {
        val monday = ZonedDateTime.parse("2026-11-16T10:00:00-05:00[America/New_York]")
        assertEquals("2026-11-22T09:15-05:00[America/New_York]", WeeklyTime(1, 9, 15).nextAfter(monday).toString())
    }

    @Test fun aPastOrExactlyDueTimeUsesTheFollowingWeek() {
        val now = ZonedDateTime.parse("2026-11-16T10:00:00Z")
        assertEquals(now.plusWeeks(1), WeeklyTime(2, 10, 0).nextAfter(now))
        assertEquals(now.plusWeeks(1), WeeklyTime(2, 10, 0).nextAfter(now.plusMinutes(40)))
    }

    @Test fun weeklyTimeReturnsToTheChosenHourAfterDaylightSaving() {
        val now = ZonedDateTime.parse("2026-03-07T12:00:00-05:00[America/New_York]")
        val time = WeeklyTime(1, 2, 30)
        val shifted = time.nextAfter(now)
        assertEquals("2026-03-08T03:30-04:00[America/New_York]", shifted.toString())
        assertEquals("2026-03-15T02:30-04:00[America/New_York]", time.nextAfter(shifted).toString())
    }

    @Test fun aRepeatedHourIsScheduledOnce() {
        val now = ZonedDateTime.parse("2026-11-01T01:30:00-04:00[America/New_York]")
        assertEquals("2026-11-08T01:30-05:00[America/New_York]", WeeklyTime(1, 1, 30).nextAfter(now).toString())
    }
}

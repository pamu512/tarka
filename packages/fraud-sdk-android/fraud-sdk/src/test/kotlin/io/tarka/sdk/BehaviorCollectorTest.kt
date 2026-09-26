package io.tarka.sdk

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * P3.2 mobile parity: BehaviorCollector emits the SAME JSON keys as the TS SDK
 * so `extract_behavior_tags` on the server works unchanged.
 *
 * Assertions read the typed summary maps directly (JSON boxing of Int/Double
 * differs between android.jar and org.json:json - the parity contract is the
 * KEY NAMES and values, not the JVM box types).
 */
class BehaviorCollectorTest {

    @Test
    fun summaryUsesTSParityKeys() {
        val c = BehaviorCollector()
        c.recordKeyDown(0.0); c.recordKeyUp(0.06)
        c.recordKeyDown(0.5); c.recordKeyUp(0.56)   // kd->kd gap exactly 500ms
        c.recordKeyDown(1.0); c.recordKeyUp(1.05)   // kd->kd gap exactly 500ms
        c.recordClick(1.2)
        c.recordClick(1.6)
        c.recordScroll(1.8)

        val s = c.summary()
        val typing = s.typing
        assertNotNull("typing summary missing - server extracts behavior:* from it", typing)
        assertTrue("avg_inter_key_ms" in typing)
        assertEquals(3, typing["key_count"])
        // kd->kd gaps are exactly 500ms each (>= threshold), so 2 hesitation events.
        assertEquals(2, typing["hesitation_events_gt_500ms"])

        val session = s.session
        assertNotNull(session)
        assertEquals(2, session["click_count"])

        val bot = s.botIndicators
        assertNotNull("bot_indicators is the server tag source", bot)
        // Mouse events present -> zero_mouse_movement false; we scrolled -> no_scroll false.
        assertFalse(bot.getValue("zero_mouse_movement"))
        assertFalse(bot.getValue("no_scroll"))

        // JSON shape: same key names serialize.
        val json = s.toJson()
        assertNotNull(json.optJSONObject("typing"))
        assertNotNull(json.optJSONObject("session"))
        assertNotNull(json.optJSONObject("bot_indicators"))
    }

    @Test
    fun botIndicatorsTripOnEmptyWindows() {
        val c = BehaviorCollector()
        val bot = c.summary().botIndicators
        assertTrue(bot.getValue("zero_mouse_movement"))
        assertTrue(bot.getValue("no_scroll"))
    }

    @Test
    fun interKeyStatsCompute() {
        val c = BehaviorCollector()
        c.recordKeyDown(0.0); c.recordKeyUp(0.05)
        c.recordKeyDown(0.1); c.recordKeyUp(0.15)   // kd->kd gap 100ms
        c.recordKeyDown(0.4); c.recordKeyUp(0.45)   // kd->kd gap 300ms
        val t = c.summary().typing
        assertEquals(3, t["key_count"])
        assertEquals(200.0, t["avg_inter_key_ms"] as Double, 0.001) // (100 + 300) / 2
    }
}

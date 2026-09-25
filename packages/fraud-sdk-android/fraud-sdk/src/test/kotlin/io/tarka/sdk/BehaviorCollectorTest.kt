package io.tarka.sdk

import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * P3.2 mobile parity: BehaviorCollector emits the SAME JSON keys as the TS SDK
 * so `extract_behavior_tags` on the server works unchanged.
 */
class BehaviorCollectorTest {

    @Test
    fun summaryUsesTSParityKeys() {
        val c = BehaviorCollector()
        c.recordKeyDown(0.0); c.recordKeyUp(0.06)
        c.recordKeyDown(0.5); c.recordKeyUp(0.56)   // 500ms gap -> hesitation
        c.recordKeyDown(1.0); c.recordKeyUp(1.05)
        c.recordClick(1.2)
        c.recordClick(1.6)
        c.recordScroll(1.8)

        val json = c.summary().toJson()
        val typing = json.optJSONObject("typing")
        assertNotNull("typing summary missing - server extracts behavior:* from it", typing)
        assertEquals(3, typing!!.optInt("key_count"))
        // kd->kd gaps are exactly 500ms each (>= threshold), so 2 hesitation events.
        assertEquals(2, typing.optInt("hesitation_events_gt_500ms"))

        val session = json.optJSONObject("session")
        assertNotNull(session)
        assertEquals(2, session!!.optInt("click_count"))

        val bot = json.optJSONObject("bot_indicators")
        assertNotNull("bot_indicators is the server tag source", bot)
        // Mouse events present -> zero_mouse_movement false; we scrolled -> no_scroll false.
        assertFalse(bot!!.optBoolean("zero_mouse_movement"))
        assertFalse(bot.optBoolean("no_scroll"))
    }

    @Test
    fun botIndicatorsTripOnEmptyWindows() {
        val c = BehaviorCollector()
        val bot = c.summary().toJson().optJSONObject("bot_indicators")!!
        assertTrue(bot.optBoolean("zero_mouse_movement"))
        assertTrue(bot.optBoolean("no_scroll"))
    }

    @Test
    fun interKeyStatsCompute() {
        val c = BehaviorCollector()
        c.recordKeyDown(0.0); c.recordKeyUp(0.05)
        c.recordKeyDown(0.1); c.recordKeyUp(0.15)   // gap 100ms
        c.recordKeyDown(0.4); c.recordKeyUp(0.45)   // gap 250ms
        val t = c.summary().toJson().optJSONObject("typing")!!
        assertEquals(3, t.optInt("key_count"))
        assertEquals(200.0, t.optDouble("avg_inter_key_ms"), 0.001) // keyDown->keyDown gaps (100 + 300) / 2
    }
}

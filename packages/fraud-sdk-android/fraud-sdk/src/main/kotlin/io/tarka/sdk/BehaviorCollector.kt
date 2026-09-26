package io.tarka.sdk

import org.json.JSONObject

/**
 * P3.2 mobile parity: behavior collection with TS-SDK parity keys.
 *
 * The TS SDK (packages/fraud-sdk-typescript/src/behavior.ts) is the reference
 * implementation; this collector emits the SAME summary keys (typing / session /
 * bot_indicators) so `decision_api.extract_behavior_tags` works unchanged.
 * Wire `record*` calls from your View/Compose event handlers; `summary()`
 * produces the sealed-packet payload.
 *
 * Beta: touch/scroll cadence detail is thinner than TS (no scroll-depth or
 * multi-touch stats yet). Docs mark mobile behavior collection beta.
 */
class BehaviorCollector {

    private val keyDownTimes = mutableListOf<Double>()
    private val keyUpTimes = mutableListOf<Double>()
    private val interKeyIntervals = mutableListOf<Double>()
    private var lastKeyDownStart: Double? = null
    private val clickTimes = mutableListOf<Double>()
    private val scrollTimes = mutableListOf<Double>()
    private val touchTimes = mutableListOf<Double>()

    fun recordKeyDown(t: Double) {
        // TS parity: interval = keyDown -> next keyDown.
        lastKeyDownStart?.let { prev -> interKeyIntervals.add(t - prev) }
        keyDownTimes.add(t)
    }

    fun recordKeyUp(t: Double) {
        keyUpTimes.add(t)
    }

    fun recordClick(t: Double) { clickTimes.add(t) }
    fun recordScroll(t: Double) { scrollTimes.add(t) }
    fun recordTouch(t: Double) { touchTimes.add(t) }

    fun summary(): BehaviorSummary {
        val intervals = interKeyIntervals.toList()
        val keyCount = keyDownTimes.size

        val avgInterKey = if (intervals.isEmpty()) 0.0 else intervals.average()
        val stdInterKey = if (intervals.isEmpty()) 0.0 else kotlin.math.sqrt(
            intervals.map { (it - avgInterKey) * (it - avgInterKey) }.average()
        )
        val sorted = intervals.sorted()
        val medianInterKey = if (sorted.isEmpty()) 0.0 else {
            val mid = sorted.size / 2
            if (sorted.size % 2 == 1) sorted[mid] else (sorted[mid - 1] + sorted[mid]) / 2.0
        }

        val holds = keyDownTimes.zip(keyUpTimes).map { maxOf(0.0, it.second - it.first) }
        val avgHold = if (holds.isEmpty()) 0.0 else holds.average()

        val hesitation = intervals.count { it * 1000.0 >= 500.0 }

        val hasTyping = keyCount > 0
        val botIndicators = mapOf(
            "zero_mouse_movement" to clickTimes.isEmpty(),
            "no_scroll" to scrollTimes.isEmpty(),
            "constant_typing_speed" to (hasTyping && intervals.isNotEmpty() && stdInterKey < 0.005),
            "suspiciously_fast" to (hasTyping && avgInterKey in 0.0001..0.025),
        )

        return BehaviorSummary(
            typing = mapOf(
                "avg_inter_key_ms" to avgInterKey * 1000.0,
                "std_inter_key_ms" to stdInterKey * 1000.0,
                "median_inter_key_ms" to medianInterKey * 1000.0,
                "avg_hold_ms" to avgHold * 1000.0,
                "key_count" to keyCount,
                "hesitation_events_gt_500ms" to hesitation,
            ),
            session = mapOf(
                "click_count" to clickTimes.size,
                "scroll_count" to scrollTimes.size,
                "touch_count" to touchTimes.size,
                "duration_s" to ((keyUpTimes.lastOrNull() ?: 0.0) - (keyDownTimes.firstOrNull() ?: 0.0))
                    .coerceAtLeast(0.0),
            ),
            botIndicators = botIndicators,
        )
    }

    data class BehaviorSummary(
        val typing: Map<String, Any>,
        val session: Map<String, Any>,
        val botIndicators: Map<String, Boolean>,
    ) {
        fun toJson(): JSONObject = JSONObject().apply {
            put("typing", JSONObject(typing))
            put("session", JSONObject(session))
            put("bot_indicators", JSONObject(botIndicators))
        }
    }
}

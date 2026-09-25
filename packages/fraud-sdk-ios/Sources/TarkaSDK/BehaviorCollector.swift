import Foundation

/**
 P3.2 mobile parity: behavior collection with TS-SDK parity keys.

 The TS SDK (packages/fraud-sdk-typescript/src/behavior.ts) is the reference
 implementation; this collector emits the SAME summary keys (typing / session /
 bot_indicators) so `decision_api.extract_behavior_tags` works unchanged.
 Wire `record*` calls from your UIKit/SwiftUI event handlers; `summary()`
 produces the sealed-packet payload.

 Beta: touch/scroll cadence detail is thinner than TS (no scroll-depth or
 multi-touch stats yet). Docs mark mobile behavior collection beta.
 */
public final class BehaviorCollector {

    private var keyDownTimes: [Double] = []
    private var keyUpTimes: [Double] = []
    private var interKeyIntervals: [Double] = []
    private var lastKeyDownStart: Double?
    private var clickTimes: [Double] = []
    private var scrollTimes: [Double] = []
    private var touchTimes: [Double] = []

    public init() {}

    // MARK: - Event intake (call from UI event handlers; seconds monotonic)

    public func recordKeyDown(at t: Double) {
        if let prevStart = lastKeyDownStart {
            // TS parity: interval = keyDown -> next keyDown.
            interKeyIntervals.append(t - prevStart)
        }
        lastKeyDownStart = t
        keyDownTimes.append(t)
    }

    public func recordKeyUp(at t: Double) {
        keyUpTimes.append(t)
    }

    public func recordClick(at t: Double) { clickTimes.append(t) }
    public func recordScroll(at t: Double) { scrollTimes.append(t) }
    public func recordTouch(at t: Double) { touchTimes.append(t) }

    // MARK: - Summary (TS parity shape)

    public struct BehaviorSummary {
        public let typing: [String: Any]
        public let session: [String: Any]
        public let botIndicators: [String: Bool]

        public func toJSONDictionary() -> [String: Any] {
            [
                "typing": typing,
                "session": session,
                "bot_indicators": botIndicators,
            ]
        }
    }

    public func summary() -> BehaviorSummary {
        let intervals = interKeyIntervals
        let keyCount = keyDownTimes.count

        let avgInterKey: Double
        let stdInterKey: Double
        let medianInterKey: Double
        if intervals.isEmpty {
            avgInterKey = 0; stdInterKey = 0; medianInterKey = 0
        } else {
            let sorted = intervals.sorted()
            let n = Double(sorted.count)
            avgInterKey = sorted.reduce(0, +) / n
            let mean = avgInterKey
            stdInterKey = (sorted.map { ($0 - mean) * ($0 - mean) }.reduce(0, +) / n).squareRoot()
            let mid = sorted.count / 2
            medianInterKey = sorted.count % 2 == 1 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2.0
        }

        let holds = zip(keyDownTimes, keyUpTimes).map { max(0, $1 - $0) }
        let avgHold: Double = holds.isEmpty ? 0 : holds.reduce(0, +) / Double(holds.count)

        let hesitation = intervals.filter { $0 * 1000.0 >= 500.0 }.count

        let typing: [String: Any] = [
            "avg_inter_key_ms": avgInterKey * 1000.0,
            "std_inter_key_ms": stdInterKey * 1000.0,
            "median_inter_key_ms": medianInterKey * 1000.0,
            "avg_hold_ms": avgHold * 1000.0,
            "key_count": keyCount,
            "hesitation_events_gt_500ms": hesitation,
        ]

        let session: [String: Any] = [
            "click_count": clickTimes.count,
            "scroll_count": scrollTimes.count,
            "touch_count": touchTimes.count,
            "duration_s": (keyDownTimes.first.map { first in
                max(0, (keyUpTimes.last ?? first) - first)
            } ?? 0),
        ]

        let hasTyping = keyCount > 0
        let bot: [String: Bool] = [
            "zero_mouse_movement": clickTimes.isEmpty,
            "no_scroll": scrollTimes.isEmpty,
            "constant_typing_speed": hasTyping && !intervals.isEmpty && stdInterKey < 0.005,
            "suspiciously_fast": hasTyping && avgInterKey > 0 && avgInterKey < 0.025,
        ]

        return BehaviorSummary(typing: typing, session: session, botIndicators: bot)
    }
}

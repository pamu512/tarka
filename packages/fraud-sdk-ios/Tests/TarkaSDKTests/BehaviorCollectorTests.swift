import XCTest
@testable import TarkaSDK

/// P3.2 mobile parity: BehaviorCollector emits the SAME JSON keys as the TS SDK
/// so `extract_behavior_tags` on the server works unchanged.
final class BehaviorCollectorTests: XCTestCase {

    func testSummaryUsesTSParityKeys() throws {
        let collector = BehaviorCollector()
        // Feed synthetic events: 5 keys with pauses, 2 clicks, 1 scroll, no touch.
        collector.recordKeyDown(at: 0.0)
        collector.recordKeyUp(at: 0.06)
        collector.recordKeyDown(at: 0.5)   // 500ms gap -> hesitation event
        collector.recordKeyUp(at: 0.56)
        collector.recordKeyDown(at: 1.0)
        collector.recordKeyUp(at: 1.05)
        collector.recordClick(at: 1.2)
        collector.recordClick(at: 1.6)
        collector.recordScroll(at: 1.8)

        let s = collector.summary()
        let dict = s.toJSONDictionary()

        let typing = dict["typing"] as? [String: Any]
        XCTAssertNotNil(typing, "typing summary missing - server extracts behavior:* from it")
        XCTAssertNotNil(typing?["avg_inter_key_ms"])
        XCTAssertNotNil(typing?["hesitation_events_gt_500ms"])
        // key_count lives inside the typing summary (TS shape); NSNumber bridging.
        XCTAssertEqual((typing?["key_count"] as? NSNumber)?.intValue, 3)
        // kd->kd gaps are exactly 500ms each (>= threshold), so 2 hesitation events.
        XCTAssertEqual((typing?["hesitation_events_gt_500ms"] as? NSNumber)?.intValue, 2)

        let session = dict["session"] as? [String: Any]
        XCTAssertNotNil(session)
        XCTAssertEqual((session?["click_count"] as? NSNumber)?.intValue, 2)

        let bot = dict["bot_indicators"] as? [String: Bool]
        XCTAssertNotNil(bot, "bot_indicators is the server tag source")
        // With mouse events present, zero_mouse_movement must be false.
        XCTAssertEqual(bot?["zero_mouse_movement"], false)
        // No scroll *absence*: we scrolled once, so no_scroll false.
        XCTAssertEqual(bot?["no_scroll"], false)
    }

    func testBotIndicatorsTripOnEmptyWindows() throws {
        let collector = BehaviorCollector()  // nothing recorded
        let dict = collector.summary().toJSONDictionary()
        let bot = dict["bot_indicators"] as? [String: Bool]
        XCTAssertEqual(bot?["zero_mouse_movement"], true)
        XCTAssertEqual(bot?["no_scroll"], true)
    }

    func testInterKeyStatsCompute() throws {
        let c = BehaviorCollector()
        c.recordKeyDown(at: 0.0); c.recordKeyUp(at: 0.05)
        c.recordKeyDown(at: 0.1); c.recordKeyUp(at: 0.15)  // gap 100ms
        c.recordKeyDown(at: 0.4); c.recordKeyUp(at: 0.45)  // gap 250ms
        let t = c.summary().toJSONDictionary()["typing"] as? [String: Any]
        XCTAssertEqual((t?["key_count"] as? NSNumber)?.intValue, 3)
        let avg = t?["avg_inter_key_ms"] as? Double
        XCTAssertNotNil(avg)
        XCTAssertEqual(avg!, 200.0, accuracy: 0.001)  // keyDown->keyDown gaps (100 + 300) / 2
    }
}

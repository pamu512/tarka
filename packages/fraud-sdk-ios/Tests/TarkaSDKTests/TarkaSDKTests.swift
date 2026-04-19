import XCTest
@testable import TarkaSDK

final class TarkaSDKTests: XCTestCase {
    func testPlaceholder() {
        XCTAssertTrue(true)
    }

    func testEvaluateResponseDecodesInferenceContextShape() throws {
        let json = """
        {
          "trace_id": "tr-1",
          "decision": "review",
          "score": 76.2,
          "tags": ["sdk:vpn"],
          "rule_hits": ["velocity_spike"],
          "reasons": ["risk_high"],
          "ml_score": 72.5,
          "inference_context": {
            "schema_version": "3",
            "calibration_profile": "default",
            "expected_calibration_version": 1,
            "confidence_tier_label": "High",
            "driver_explain": [
              { "reason": "ml_score_elevated", "category": "ml", "label": "ML score elevated" }
            ],
            "integrity_confidence": 0.82,
            "tamper_risk": 0.1,
            "network_trust": 0.9,
            "replay_risk": 0.05,
            "geo_consistency_risk": 0.2,
            "top_signals": ["sdk:vpn"],
            "confidence_tier": "high",
            "driver_reasons": ["ml_score_elevated"],
            "colocation_risk": 0.1,
            "copresence_risk": 0.05,
            "impossible_travel_risk": 0.02,
            "velocity_events_5m": 2,
            "velocity_events_1h": 6,
            "velocity_events_24h": 20,
            "ml_top_factors": [
              { "code": "HIGH_AMOUNT", "description": "Big amount", "impact": "high" }
            ],
            "ml_summary": "summary",
            "ml_model": "heuristic-v1"
          },
          "recommended_action": "step_up_mfa"
        }
        """
        let data = Data(json.utf8)
        let decoded = try JSONDecoder().decode(EvaluateResponse.self, from: data)
        XCTAssertEqual(decoded.trace_id, "tr-1")
        XCTAssertEqual(decoded.inference_context.schema_version, "3")
        XCTAssertEqual(decoded.inference_context.driver_explain?.first?.category, "ml")
        XCTAssertEqual(decoded.inference_context.ml_top_factors?.first?.code, "HIGH_AMOUNT")
    }
}

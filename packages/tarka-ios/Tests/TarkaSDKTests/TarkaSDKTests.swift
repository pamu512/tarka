import XCTest
@testable import TarkaSDK

final class TarkaSDKTests: XCTestCase {
    func testJSONValueEncodesPayload() throws {
        let req = EvaluateRequest(
            tenant_id: "t",
            event_type: "login",
            entity_id: "e",
            payload: ["n": .int(1)],
            device_context: nil
        )
        let data = try JSONEncoder().encode(req)
        let obj = try JSONSerialization.jsonObject(with: data) as? [String: Any]
        XCTAssertEqual(obj?["tenant_id"] as? String, "t")
        XCTAssertEqual((obj?["payload"] as? [String: Any])?["n"] as? Int, 1)
    }

    func testDeviceIdStable() {
        let c = DeviceSignalCollector()
        let a = c.computeDeviceId()
        let b = c.computeDeviceId()
        XCTAssertEqual(a, b)
        XCTAssertEqual(a.count, 64)
    }
}

import Foundation
import DeviceCheck
import CryptoKit

public struct DriverExplainEntry: Codable {
    public let reason: String
    public let category: String
    public let label: String
}

public struct InferenceContext: Codable {
    public let schema_version: String
    public let calibration_profile: String
    public let expected_calibration_version: Int
    public let confidence_tier_label: String?
    public let driver_explain: [DriverExplainEntry]?
    public let integrity_confidence: Double
    public let tamper_risk: Double
    public let network_trust: Double
    public let replay_risk: Double
    public let geo_consistency_risk: Double
    public let top_signals: [String]
    public let confidence_tier: String
    public let driver_reasons: [String]
    public let colocation_risk: Double
    public let copresence_risk: Double
    public let impossible_travel_risk: Double
    public let velocity_events_5m: Int
    public let velocity_events_1h: Int
    public let velocity_events_24h: Int
    public let ml_top_factors: [[String: String]]?
    public let ml_summary: String?
    public let ml_model: String?
}

/// Decision API evaluate response contract.
public struct EvaluateResponse: Codable {
    public let trace_id: String
    public let decision: String
    public let score: Double
    public let tags: [String]
    public let rule_hits: [String]?
    public let reasons: [String]?
    public let ml_score: Double?
    public let inference_context: InferenceContext
    public let recommended_action: String?
}

/// Tarka Decision API client with optional **App Attest** attestation on `device_context`.
public final class DecisionClient {
    private let baseURL: URL
    private let apiKey: String
    private let enableAppAttest: Bool

    public init(baseURL: String, apiKey: String = "", enableAppAttest: Bool = true) {
        let trimmed = baseURL.trimmingCharacters(in: CharacterSet(charactersIn: "/"))
        guard let u = URL(string: trimmed) else {
            fatalError("Invalid baseURL")
        }
        self.baseURL = u
        self.apiKey = apiKey
        self.enableAppAttest = enableAppAttest
    }

    public func evaluate(
        tenantId: String,
        eventType: String,
        entityId: String,
        payload: [String: Any] = [:]
    ) async throws -> EvaluateResponse {
        let collected = DeviceSignalCollector.collect()
        guard let deviceId = collected["device_id"] as? String else {
            throw NSError(domain: "TarkaSDK", code: 4, userInfo: [NSLocalizedDescriptionKey: "Missing device_id"])
        }

        let isSimulator = collected["is_simulator"] as? Bool ?? false
        let isVpn = collected["is_vpn"] as? Bool ?? false
        let isRepackaged = collected["is_repackaged"] as? Bool ?? false
        let language = collected["language"] as? String ?? ""
        let platformVersion = collected["os_version"] as? String ?? ""
        let screenRes: String = {
            let v = collected["screen_scale"]
            if let n = v as? NSNumber { return n.stringValue }
            if let d = v as? Double { return String(d) }
            return ""
        }()

        var deviceContext: [String: Any] = [
            "device_id": deviceId,
            "platform": "ios",
            "signals": [
                "is_emulator": isSimulator,
                "is_vpn": isVpn,
                "is_spoofed_location": false,
                "is_bot": false,
                "is_repackaged": isRepackaged,
                "automation_detected": (collected["is_debugger_attached"] as? Bool) ?? false,
                "vpn_interface_detected": isVpn,
                "mock_location_detected": false,
                "screen_res": screenRes,
                "language": language,
                "platform_version": platformVersion,
            ],
        ]

        if enableAppAttest, let attestation = try? await performAppAttest(tenantId: tenantId, deviceId: deviceId) {
            deviceContext["attestation"] = attestation
        }

        let body: [String: Any] = [
            "tenant_id": tenantId,
            "event_type": eventType,
            "entity_id": entityId,
            "payload": payload,
            "device_context": deviceContext,
        ]

        let data = try await post(path: "/v1/decisions/evaluate", body: body)
        return try JSONDecoder().decode(EvaluateResponse.self, from: data)
    }

    // MARK: - App Attest

    private func performAppAttest(tenantId: String, deviceId: String) async throws -> [String: String] {
        let nonce = try await requestChallenge(tenantId: tenantId)
        let service = DCAppAttestService.shared
        guard service.isSupported else { throw NSError(domain: "TarkaSDK", code: 1) }

        let keyId = try await service.generateKey()
        let digest = SHA256.hash(data: Data((nonce + deviceId).utf8))
        let clientDataHash = Data(digest)
        let attestation = try await service.attestKey(keyId, clientDataHash: clientDataHash)
        let token = attestation.base64EncodedString()
        return ["nonce": nonce, "token": token, "provider": "app_attest"]
    }

    private func requestChallenge(tenantId: String) async throws -> String {
        let body: [String: Any] = ["tenant_id": tenantId]
        let data = try await post(path: "/v1/attestation/challenge", body: body)
        let json = try JSONSerialization.jsonObject(with: data) as? [String: Any]
        guard let nonce = json?["nonce"] as? String else { throw NSError(domain: "TarkaSDK", code: 2) }
        return nonce
    }

    private func post(path: String, body: [String: Any]) async throws -> Data {
        var request = URLRequest(url: baseURL.appendingPathComponent(path))
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        if !apiKey.isEmpty { request.setValue(apiKey, forHTTPHeaderField: "X-API-Key") }
        request.httpBody = try JSONSerialization.data(withJSONObject: body)
        let (data, response) = try await URLSession.shared.data(for: request)
        guard let http = response as? HTTPURLResponse, 200 ..< 300 ~= http.statusCode else {
            throw NSError(domain: "TarkaSDK", code: 3, userInfo: ["body": String(data: data, encoding: .utf8) ?? ""])
        }
        return data
    }
}

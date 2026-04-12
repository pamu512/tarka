import Foundation
import DeviceCheck
import CryptoKit

/// Subset of Decision API `POST /v1/decisions/evaluate` JSON. Extra keys (`inference_context`, `recommended_action`, …) are ignored by `JSONDecoder`.
public struct EvaluateResponse: Codable {
    public let trace_id: String
    public let decision: String
    public let score: Double
    public let tags: [String]
    public let rule_hits: [String]?
    public let reasons: [String]?
    public let ml_score: Double?
}

public class FraudStackClient {
    private let baseURL: URL
    private let apiKey: String

    public init(baseURL: String, apiKey: String = "") {
        self.baseURL = URL(string: baseURL.trimmingCharacters(in: CharacterSet(charactersIn: "/")))!
        self.apiKey = apiKey
    }

    // MARK: - Public API

    public func evaluate(
        tenantId: String,
        eventType: String,
        entityId: String,
        payload: [String: Any] = [:]
    ) async throws -> EvaluateResponse {
        let collected = DeviceSignalCollector.collect()
        guard let deviceId = collected["device_id"] as? String else {
            throw NSError(domain: "Tarka", code: 4, userInfo: [NSLocalizedDescriptionKey: "Missing device_id from DeviceSignalCollector"])
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
                "platform_version": platformVersion
            ]
        ]

        // App Attest (best-effort)
        if let attestation = try? await performAppAttest(tenantId: tenantId, deviceId: deviceId) {
            deviceContext["attestation"] = attestation
        }

        let body: [String: Any] = [
            "tenant_id": tenantId,
            "event_type": eventType,
            "entity_id": entityId,
            "payload": payload,
            "device_context": deviceContext
        ]

        let data = try await post(path: "/v1/decisions/evaluate", body: body)
        return try JSONDecoder().decode(EvaluateResponse.self, from: data)
    }

    // MARK: - App Attest

    private func performAppAttest(tenantId: String, deviceId: String) async throws -> [String: String] {
        let nonce = try await requestChallenge(tenantId: tenantId)
        let service = DCAppAttestService.shared
        guard service.isSupported else { throw NSError(domain: "Tarka", code: 1) }

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
        guard let nonce = json?["nonce"] as? String else { throw NSError(domain: "Tarka", code: 2) }
        return nonce
    }

    // MARK: - HTTP

    private func post(path: String, body: [String: Any]) async throws -> Data {
        var request = URLRequest(url: baseURL.appendingPathComponent(path))
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        if !apiKey.isEmpty { request.setValue(apiKey, forHTTPHeaderField: "X-API-Key") }
        request.httpBody = try JSONSerialization.data(withJSONObject: body)
        let (data, response) = try await URLSession.shared.data(for: request)
        guard let http = response as? HTTPURLResponse, 200..<300 ~= http.statusCode else {
            throw NSError(domain: "Tarka", code: 3, userInfo: ["body": String(data: data, encoding: .utf8) ?? ""])
        }
        return data
    }
}

import Foundation
import DeviceCheck
import CryptoKit

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
    private let collector = DeviceSignalCollector()

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
        let signals = collector.collect()
        let deviceId = collector.deviceId()

        var deviceContext: [String: Any] = [
            "device_id": deviceId,
            "platform": "ios",
            "signals": [
                "is_emulator": signals.isEmulator,
                "is_vpn": signals.isVpn,
                "is_spoofed_location": signals.isSpoofedLocation,
                "is_bot": signals.isBot,
                "is_repackaged": signals.isRepackaged,
                "automation_detected": signals.automationDetected,
                "vpn_interface_detected": signals.vpnInterfaceDetected,
                "mock_location_detected": signals.mockLocationDetected,
                "screen_res": signals.screenRes ?? "",
                "language": signals.language ?? "",
                "platform_version": signals.platformVersion ?? ""
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
        let clientDataHash = Data(SHA256.hash(data: Data((nonce + deviceId).utf8)))
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

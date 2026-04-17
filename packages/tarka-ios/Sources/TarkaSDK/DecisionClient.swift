import Foundation

/// HTTP client for the Tarka Decision API (evaluate, attestation challenge, audit).
public final class DecisionClient {
    private let baseURL: URL
    private let apiKey: String
    private let timeout: TimeInterval
    private let autoCollectSignals: Bool
    private let collector: DeviceSignalCollector?

    public init(
        baseUrl: String,
        apiKey: String = "",
        timeout: TimeInterval = 10,
        autoCollectSignals: Bool = true,
        collector: DeviceSignalCollector? = nil
    ) {
        let trimmed = baseUrl.trimmingCharacters(in: CharacterSet(charactersIn: "/"))
        guard let u = URL(string: trimmed) else {
            fatalError("Invalid baseUrl")
        }
        self.baseURL = u
        self.apiKey = apiKey
        self.timeout = timeout
        self.autoCollectSignals = autoCollectSignals
        self.collector = collector ?? DeviceSignalCollector()
    }

    public func requestChallenge(tenantId: String) async throws -> String {
        var req = URLRequest(url: baseURL.appendingPathComponent("v1/attestation/challenge"))
        req.httpMethod = "POST"
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        if !apiKey.isEmpty { req.setValue(apiKey, forHTTPHeaderField: "X-API-Key") }
        let body = ["tenant_id": tenantId] as [String: String]
        req.httpBody = try JSONSerialization.data(withJSONObject: body)
        let (data, resp) = try await URLSession.shared.data(for: req)
        try throwIfNeeded(resp, data)
        let obj = try JSONSerialization.jsonObject(with: data) as? [String: Any]
        guard let nonce = obj?["nonce"] as? String else {
            throw TarkaSDKError.invalidResponse
        }
        return nonce
    }

    public func evaluate(_ request: EvaluateRequest) async throws -> EvaluateResponse {
        var r = request
        if autoCollectSignals, r.device_context == nil, let c = collector {
            let ctx = c.buildDeviceContext()
            r = EvaluateRequest(
                tenant_id: r.tenant_id,
                event_type: r.event_type,
                entity_id: r.entity_id,
                session_id: r.session_id,
                payload: r.payload,
                device_context: ctx,
                metadata: r.metadata
            )
        }
        var req = URLRequest(url: baseURL.appendingPathComponent("v1/decisions/evaluate"))
        req.httpMethod = "POST"
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        if !apiKey.isEmpty { req.setValue(apiKey, forHTTPHeaderField: "X-API-Key") }
        let enc = JSONEncoder()
        req.httpBody = try enc.encode(r)
        let (data, resp) = try await URLSession.shared.data(for: req)
        try throwIfNeeded(resp, data)
        let dec = JSONDecoder()
        return try dec.decode(EvaluateResponse.self, from: data)
    }

    /// Raw audit JSON (snake_case keys as returned by the API).
    public func getAudit(traceId: String, tenantId: String) async throws -> [String: Any] {
        var comp = URLComponents(url: baseURL.appendingPathComponent("v1/audit/\(traceId)"), resolvingAgainstBaseURL: false)!
        comp.queryItems = [URLQueryItem(name: "tenant_id", value: tenantId)]
        guard let url = comp.url else { throw TarkaSDKError.invalidResponse }
        var req = URLRequest(url: url)
        req.httpMethod = "GET"
        if !apiKey.isEmpty { req.setValue(apiKey, forHTTPHeaderField: "X-API-Key") }
        let (data, resp) = try await URLSession.shared.data(for: req)
        try throwIfNeeded(resp, data)
        let obj = try JSONSerialization.jsonObject(with: data) as? [String: Any]
        return obj ?? [:]
    }

    private func throwIfNeeded(_ resp: URLResponse, _ data: Data) throws {
        guard let http = resp as? HTTPURLResponse else { return }
        guard (200 ... 299).contains(http.statusCode) else {
            let msg = String(data: data, encoding: .utf8) ?? "HTTP \(http.statusCode)"
            throw TarkaSDKError.httpError(http.statusCode, msg)
        }
    }
}

public enum TarkaSDKError: Error {
    case invalidResponse
    case httpError(Int, String)
}

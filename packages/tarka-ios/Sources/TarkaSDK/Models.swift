import Foundation

/// Device signals aligned with Decision API / TypeScript SDK (`snake_case` JSON keys).
public struct DeviceSignals: Codable {
    public var is_emulator: Bool
    public var is_vpn: Bool
    public var is_spoofed_location: Bool
    public var is_bot: Bool
    public var is_repackaged: Bool
    public var webdriver_detected: Bool
    public var headless_detected: Bool
    public var automation_detected: Bool
    public var vpn_interface_detected: Bool
    public var mock_location_detected: Bool
    public var timezone_geo_mismatch: Bool
    public var canvas_fp_hash: String?
    public var webgl_renderer: String?
    public var screen_res: String?
    public var touch_support: Bool?
    public var battery_api_present: Bool?
    public var language: String?
    public var platform_version: String?

    public init(
        is_emulator: Bool = false,
        is_vpn: Bool = false,
        is_spoofed_location: Bool = false,
        is_bot: Bool = false,
        is_repackaged: Bool = false,
        webdriver_detected: Bool = false,
        headless_detected: Bool = false,
        automation_detected: Bool = false,
        vpn_interface_detected: Bool = false,
        mock_location_detected: Bool = false,
        timezone_geo_mismatch: Bool = false,
        canvas_fp_hash: String? = nil,
        webgl_renderer: String? = nil,
        screen_res: String? = nil,
        touch_support: Bool? = nil,
        battery_api_present: Bool? = nil,
        language: String? = nil,
        platform_version: String? = nil
    ) {
        self.is_emulator = is_emulator
        self.is_vpn = is_vpn
        self.is_spoofed_location = is_spoofed_location
        self.is_bot = is_bot
        self.is_repackaged = is_repackaged
        self.webdriver_detected = webdriver_detected
        self.headless_detected = headless_detected
        self.automation_detected = automation_detected
        self.vpn_interface_detected = vpn_interface_detected
        self.mock_location_detected = mock_location_detected
        self.timezone_geo_mismatch = timezone_geo_mismatch
        self.canvas_fp_hash = canvas_fp_hash
        self.webgl_renderer = webgl_renderer
        self.screen_res = screen_res
        self.touch_support = touch_support
        self.battery_api_present = battery_api_present
        self.language = language
        self.platform_version = platform_version
    }
}

public struct Attestation: Codable {
    public let nonce: String
    public let token: String
    public let provider: String

    public init(nonce: String, token: String, provider: String) {
        self.nonce = nonce
        self.token = token
        self.provider = provider
    }
}

public struct DeviceContext: Codable {
    public let device_id: String
    public let platform: String
    public let signals: DeviceSignals
    public let attestation: Attestation?

    public init(device_id: String, platform: String = "ios", signals: DeviceSignals, attestation: Attestation? = nil) {
        self.device_id = device_id
        self.platform = platform
        self.signals = signals
        self.attestation = attestation
    }
}

public struct EvaluateRequest: Codable {
    public let tenant_id: String
    public let event_type: String
    public let entity_id: String
    public let session_id: String?
    public let payload: [String: JSONValue]
    public let device_context: DeviceContext?
    public let metadata: [String: JSONValue]?

    public init(
        tenant_id: String,
        event_type: String,
        entity_id: String,
        session_id: String? = nil,
        payload: [String: JSONValue] = [:],
        device_context: DeviceContext? = nil,
        metadata: [String: JSONValue]? = nil
    ) {
        self.tenant_id = tenant_id
        self.event_type = event_type
        self.entity_id = entity_id
        self.session_id = session_id
        self.payload = payload
        self.device_context = device_context
        self.metadata = metadata
    }
}

public enum JSONValue: Codable {
    case string(String)
    case int(Int)
    case double(Double)
    case bool(Bool)
    case object([String: JSONValue])
    case array([JSONValue])
    case null

    public func encode(to encoder: Encoder) throws {
        switch self {
        case .string(let s):
            var c = encoder.singleValueContainer()
            try c.encode(s)
        case .int(let i):
            var c = encoder.singleValueContainer()
            try c.encode(i)
        case .double(let d):
            var c = encoder.singleValueContainer()
            try c.encode(d)
        case .bool(let b):
            var c = encoder.singleValueContainer()
            try c.encode(b)
        case .object(let o):
            var keyed = encoder.container(keyedBy: JSONDynamicKey.self)
            for (k, v) in o {
                try keyed.encode(v, forKey: JSONDynamicKey(stringValue: k)!)
            }
        case .array(let a):
            var unkeyed = encoder.unkeyedContainer()
            for v in a {
                try unkeyed.encode(v)
            }
        case .null:
            var c = encoder.singleValueContainer()
            try c.encodeNil()
        }
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.singleValueContainer()
        if c.decodeNil() {
            self = .null
            return
        }
        if let b = try? c.decode(Bool.self) {
            self = .bool(b)
            return
        }
        if let i = try? c.decode(Int.self) {
            self = .int(i)
            return
        }
        if let d = try? c.decode(Double.self) {
            self = .double(d)
            return
        }
        if let s = try? c.decode(String.self) {
            self = .string(s)
            return
        }
        if var uc = try? decoder.unkeyedContainer() {
            var arr: [JSONValue] = []
            while !uc.isAtEnd {
                arr.append(try uc.decode(JSONValue.self))
            }
            self = .array(arr)
            return
        }
        let oc = try decoder.container(keyedBy: JSONDynamicKey.self)
        var dict: [String: JSONValue] = [:]
        for key in oc.allKeys {
            dict[key.stringValue] = try oc.decode(JSONValue.self, forKey: key)
        }
        self = .object(dict)
    }
}

private struct JSONDynamicKey: CodingKey {
    var stringValue: String
    var intValue: Int?
    init?(stringValue: String) { self.stringValue = stringValue }
    init?(intValue: Int) { return nil }
}

public struct EvaluateResponse: Codable {
    public let trace_id: String
    public let decision: String
    public let score: Double
    public let tags: [String]
    public let inference_context: JSONValue?
    public let recommended_action: String?

    private enum CodingKeys: String, CodingKey {
        case trace_id, decision, score, tags, inference_context, recommended_action
    }
}

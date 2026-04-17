import CryptoKit
import Darwin
import Foundation
#if canImport(UIKit)
import UIKit
#endif

/// Collects iOS environment signals for [DeviceContext].
public final class DeviceSignalCollector {
    public init() {}

    public func collect() -> DeviceSignals {
        #if targetEnvironment(simulator)
        let isEmu = true
        #else
        let isEmu = false
        #endif

        let vpn = Self.isVpnActive()

        #if canImport(UIKit)
        let screen = "\(Int(UIScreen.main.bounds.width))x\(Int(UIScreen.main.bounds.height))"
        #else
        let screen: String? = nil
        #endif

        let lang = Locale.current.identifier

        return DeviceSignals(
            is_emulator: isEmu,
            is_vpn: vpn,
            is_spoofed_location: false,
            is_bot: false,
            is_repackaged: false,
            webdriver_detected: false,
            headless_detected: false,
            automation_detected: false,
            vpn_interface_detected: vpn,
            mock_location_detected: false,
            timezone_geo_mismatch: false,
            canvas_fp_hash: nil,
            webgl_renderer: nil,
            screen_res: screen,
            touch_support: true,
            battery_api_present: true,
            language: lang,
            platform_version: "iOS \(ProcessInfo.processInfo.operatingSystemVersionString)"
        )
    }

    public func computeDeviceId() -> String {
        #if canImport(UIKit)
        let id = UIDevice.current.identifierForVendor?.uuidString ?? "unknown"
        #else
        let id = "unknown"
        #endif
        let raw = "ios|\(id)"
        let digest = SHA256.hash(data: Data(raw.utf8))
        return digest.map { String(format: "%02x", $0) }.joined()
    }

    public func buildDeviceContext() -> DeviceContext {
        DeviceContext(device_id: computeDeviceId(), platform: "ios", signals: collect(), attestation: nil)
    }

    private static func isVpnActive() -> Bool {
        var addrs: UnsafeMutablePointer<ifaddrs>?
        guard getifaddrs(&addrs) == 0, let first = addrs else { return false }
        defer { freeifaddrs(first) }
        var ptr: UnsafeMutablePointer<ifaddrs>? = first
        while let p = ptr {
            let name = String(cString: p.pointee.ifa_name)
            if name.hasPrefix("utun") || name.hasPrefix("ppp") || name.hasPrefix("ipsec") {
                return true
            }
            ptr = p.pointee.ifa_next
        }
        return false
    }
}

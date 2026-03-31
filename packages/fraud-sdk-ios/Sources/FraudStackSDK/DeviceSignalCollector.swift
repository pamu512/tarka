import Foundation
import UIKit
import SystemConfiguration
import MachO
import CryptoKit
import LocalAuthentication
import Darwin

public class DeviceSignalCollector {

    public static func collect() -> [String: Any] {
        return [
            "device_id": getDeviceId(),
            "platform": "ios",
            "os_version": UIDevice.current.systemVersion,
            "model": getDeviceModel(),
            "is_jailbroken": isJailbroken(),
            "is_simulator": isSimulator(),
            "is_vpn": isVpnActive(),
            "is_debugger_attached": isDebuggerAttached(),
            "is_repackaged": isRepackaged(),
            "screen_scale": UIScreen.main.scale,
            "timezone": TimeZone.current.identifier,
            "language": {
                if #available(iOS 16, *) {
                    return Locale.current.language.languageCode?.identifier ?? "unknown"
                } else {
                    return Locale.current.languageCode ?? "unknown"
                }
            }() as String,
            "has_biometrics": hasBiometrics(),
        ]
    }

    // MARK: - Device Identity

    /// SHA-256 of identifierForVendor, which is stable per-vendor per-device.
    /// Falls back to a reproducible hardware-derived string if IDFV is nil
    /// (rare, but possible during device restore).
    private static func getDeviceId() -> String {
        let raw: String
        if let idfv = UIDevice.current.identifierForVendor?.uuidString {
            raw = idfv
        } else {
            raw = "\(getDeviceModel())|\(ProcessInfo.processInfo.processorCount)|\(UIScreen.main.bounds)"
        }
        let hash = SHA256.hash(data: Data(raw.utf8))
        return hash.map { String(format: "%02x", $0) }.joined()
    }

    /// Uses `sysctlbyname("hw.machine")` to get the hardware model identifier
    /// (e.g. "iPhone15,2"). UIDevice.model only returns generic "iPhone".
    private static func getDeviceModel() -> String {
        var size: Int = 0
        sysctlbyname("hw.machine", nil, &size, nil, 0)
        guard size > 0 else { return UIDevice.current.model }
        var machine = [CChar](repeating: 0, count: size)
        sysctlbyname("hw.machine", &machine, &size, nil, 0)
        return String(cString: machine)
    }

    // MARK: - Jailbreak Detection

    /// Multi-vector jailbreak detection:
    /// 1. Known jailbreak file paths (Cydia, Sileo, checkra1n, unc0ver, Electra)
    /// 2. URL scheme check for Cydia
    /// 3. Writable system directories (/ should be read-only on stock iOS)
    /// 4. Ability to fork() — sandboxed apps cannot fork on non-jailbroken devices
    /// 5. Presence of suspicious dylibs (Substrate, libhooker, substitute)
    private static func isJailbroken() -> Bool {
        #if targetEnvironment(simulator)
        return false
        #else

        // 1) Suspicious file paths left by popular jailbreak tools
        let suspiciousPaths = [
            "/Applications/Cydia.app",
            "/Applications/Sileo.app",
            "/Library/MobileSubstrate/MobileSubstrate.dylib",
            "/usr/sbin/sshd",
            "/usr/bin/ssh",
            "/usr/libexec/sftp-server",
            "/etc/apt",
            "/private/var/lib/apt/",
            "/private/var/lib/cydia",
            "/private/var/tmp/cydia.log",
            "/private/var/stash",
            "/usr/lib/TweakInject",
            "/var/binpack",
            "/Library/PreferenceBundles/SubstituteSettings.bundle",
            "/.bootstrapped_electra",
            "/usr/lib/libjailbreak.dylib",
            "/jb/lzma",
            "/.cydia_no_stash",
            "/.installed_unc0ver",
            "/private/var/checkra1n.dmg",
        ]
        for path in suspiciousPaths {
            if FileManager.default.fileExists(atPath: path) {
                return true
            }
        }

        // 2) Cydia URL scheme — only registered on jailbroken devices
        if let url = URL(string: "cydia://package/com.example.package"),
           UIApplication.shared.canOpenURL(url) {
            return true
        }

        // 3) Write test to a system path (should fail in the sandbox)
        let testPath = "/private/jailbreak_test_\(UUID().uuidString)"
        do {
            try "jb_test".write(toFile: testPath, atomically: true, encoding: .utf8)
            try FileManager.default.removeItem(atPath: testPath)
            return true // write succeeded — filesystem is compromised
        } catch {
            // Expected on non-jailbroken devices
        }

        // 4) fork() succeeds only when the sandbox is broken
        let forkResult = fork()
        if forkResult >= 0 {
            if forkResult > 0 {
                // Parent — kill the child immediately
                kill(forkResult, SIGTERM)
            }
            return true
        }

        // 5) Check loaded dylibs for known hooking frameworks
        let hookingLibs = [
            "MobileSubstrate",
            "libhooker",
            "substitute",
            "SubstrateLoader",
            "TweakInject",
            "CydiaSubstrate",
        ]
        for i in 0..<_dyld_image_count() {
            guard let name = _dyld_get_image_name(i) else { continue }
            let imagePath = String(cString: name)
            for lib in hookingLibs where imagePath.contains(lib) {
                return true
            }
        }

        return false
        #endif
    }

    // MARK: - Simulator Detection

    /// Checks compile-time target and runtime environment variables.
    /// Both vectors are needed because compile-time checks can be stripped
    /// by an attacker repackaging for a real device.
    private static func isSimulator() -> Bool {
        #if targetEnvironment(simulator)
        return true
        #else
        if ProcessInfo.processInfo.environment["SIMULATOR_DEVICE_NAME"] != nil {
            return true
        }
        // hw.machine returns "x86_64" or "arm64" on simulators instead of
        // a real device identifier like "iPhone15,2"
        let model = getDeviceModel()
        if model == "x86_64" || model == "i386" {
            return true
        }
        return false
        #endif
    }

    // MARK: - VPN Detection

    /// Inspects network interface names via SCNetworkReachability's proxy
    /// dictionary. Active VPN tunnels create `utun`, `ipsec`, or `ppp`
    /// interfaces in the `__SCOPED__` proxy table.
    private static func isVpnActive() -> Bool {
        guard let cfDict = CFNetworkCopySystemProxySettings()?.takeRetainedValue() as? [String: Any],
              let scoped = cfDict["__SCOPED__"] as? [String: Any] else {
            return false
        }
        // utun = WireGuard/IKEv2 tunnels, ipsec = IPSec, ppp = L2TP/PPTP
        for key in scoped.keys {
            if key.hasPrefix("utun") || key.hasPrefix("ipsec") || key.hasPrefix("ppp") {
                return true
            }
        }
        return false
    }

    // MARK: - Debugger Detection

    /// Uses sysctl with CTL_KERN / KERN_PROC / KERN_PROC_PID to read the
    /// process info flags. If P_TRACED is set, a debugger (lldb/gdb) is
    /// attached. This is the standard Apple-documented technique.
    private static func isDebuggerAttached() -> Bool {
        var info = kinfo_proc()
        var size = MemoryLayout<kinfo_proc>.stride
        var mib: [Int32] = [CTL_KERN, KERN_PROC, KERN_PROC_PID, getpid()]
        let result = sysctl(&mib, UInt32(mib.count), &info, &size, nil, 0)
        guard result == 0 else { return false }
        return (info.kp_proc.p_flag & P_TRACED) != 0
    }

    // MARK: - Repackaging Detection

    /// Two-pronged integrity check:
    /// 1. Verifies embedded.mobileprovision presence — ad-hoc/enterprise
    ///    re-signed apps may alter or remove it.
    /// 2. Checks that the app binary's LC_CODE_SIGNATURE load command is
    ///    present, indicating the Mach-O hasn't been stripped and re-signed
    ///    by a different identity.
    private static func isRepackaged() -> Bool {
        // Provisioning profile check: App Store builds strip this file,
        // so only flag in non-debug builds where it's expected to exist
        // but is missing (enterprise/TestFlight).
        #if !DEBUG
        let provisionPath = Bundle.main.path(forResource: "embedded", ofType: "mobileprovision")
        if provisionPath == nil {
            // App Store apps don't have this file — need a secondary signal
            // to distinguish "App Store" from "sideloaded without profile"
            if !isAppStoreReceipt() {
                return true
            }
        }
        #endif

        // Verify the main executable has a code signature load command
        guard let executablePath = Bundle.main.executablePath else { return true }
        guard FileManager.default.fileExists(atPath: executablePath) else { return true }

        // Walk Mach-O load commands looking for LC_CODE_SIGNATURE (0x1d)
        let header = _dyld_get_image_header(0)
        guard header != nil else { return true }
        var hasCodeSig = false
        var cmdPtr = UnsafeRawPointer(header!).advanced(by: MemoryLayout<mach_header_64>.size)
        for _ in 0..<header!.pointee.ncmds {
            let cmd = cmdPtr.assumingMemoryBound(to: load_command.self).pointee
            if cmd.cmd == LC_CODE_SIGNATURE {
                hasCodeSig = true
                break
            }
            cmdPtr = cmdPtr.advanced(by: Int(cmd.cmdsize))
        }
        return !hasCodeSig
    }

    /// Heuristic: App Store receipts live at a specific bundle path.
    private static func isAppStoreReceipt() -> Bool {
        guard let receiptURL = Bundle.main.appStoreReceiptURL else { return false }
        return FileManager.default.fileExists(atPath: receiptURL.path)
    }

    // MARK: - Biometrics

    /// Queries LocalAuthentication to determine if the device has enrolled
    /// Face ID or Touch ID. Useful as an identity-assurance signal — devices
    /// with biometrics are more likely to belong to a real user.
    private static func hasBiometrics() -> Bool {
        let laContext = LAContext()
        var error: NSError?
        let canEvaluate = laContext.canEvaluatePolicy(.deviceOwnerAuthenticationWithBiometrics, error: &error)
        return canEvaluate
    }
}

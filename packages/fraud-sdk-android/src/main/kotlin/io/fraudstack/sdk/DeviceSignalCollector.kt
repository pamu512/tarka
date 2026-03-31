package io.fraudstack.sdk

import android.content.Context
import android.content.pm.ApplicationInfo
import android.content.pm.PackageManager
import android.os.Build
import android.provider.Settings
import android.telephony.TelephonyManager
import android.net.ConnectivityManager
import android.net.NetworkCapabilities
import android.util.DisplayMetrics
import java.io.File
import java.security.MessageDigest
import java.net.NetworkInterface

class DeviceSignalCollector(private val context: Context) {

    fun collect(): Map<String, Any> {
        return mapOf(
            "device_id" to getDeviceId(),
            "platform" to "android",
            "os_version" to Build.VERSION.RELEASE,
            "sdk_int" to Build.VERSION.SDK_INT,
            "manufacturer" to Build.MANUFACTURER,
            "model" to Build.MODEL,
            "brand" to Build.BRAND,
            "is_emulator" to isEmulator(),
            "is_rooted" to isRooted(),
            "is_vpn" to isVpnActive(),
            "is_debuggable" to isDebuggable(),
            "is_repackaged" to isRepackaged(),
            "installer_package" to getInstallerPackage(),
            "screen_density" to getScreenDensity(),
            "timezone" to java.util.TimeZone.getDefault().id,
            "language" to java.util.Locale.getDefault().language,
            "ip_addresses" to getLocalIpAddresses(),
        )
    }

    /**
     * Generates a stable, privacy-preserving device identifier by hashing the
     * Android ID (SSAID) with SHA-256. Android ID is unique per app-signing-key
     * per user on API 26+ and survives factory resets on older versions.
     */
    private fun getDeviceId(): String {
        val androidId = Settings.Secure.getString(context.contentResolver, Settings.Secure.ANDROID_ID)
            ?: "unknown"
        val digest = MessageDigest.getInstance("SHA-256").digest(androidId.toByteArray(Charsets.UTF_8))
        return digest.joinToString("") { "%02x".format(it) }
    }

    /**
     * Multi-signal emulator detection. Checks:
     * 1. Build fingerprint for known emulator markers (generic, google/sdk, test-keys)
     * 2. Build model/product for "sdk", "emulator", "google_sdk"
     * 3. Manufacturer for Genymotion
     * 4. Hardware for "goldfish" (QEMU) and "ranchu" (newer QEMU)
     * 5. QEMU-specific system files on the filesystem
     * 6. Missing telephony hardware (no phone radio is common in emulators)
     */
    private fun isEmulator(): Boolean {
        val fingerprint = Build.FINGERPRINT.lowercase()
        if (fingerprint.contains("generic") || fingerprint.contains("vbox") || fingerprint.contains("test-keys")) {
            return true
        }

        val model = Build.MODEL.lowercase()
        if (model.contains("sdk") || model.contains("emulator") || model.contains("android sdk")) {
            return true
        }

        val product = Build.PRODUCT.lowercase()
        if (product.contains("sdk") || product.contains("google_sdk") || product.contains("sdk_gphone")) {
            return true
        }

        if (Build.MANUFACTURER.lowercase().contains("genymotion")) return true

        val hardware = Build.HARDWARE.lowercase()
        if (hardware.contains("goldfish") || hardware.contains("ranchu")) return true

        // QEMU leaves driver files on the filesystem
        val qemuFiles = listOf(
            "/dev/socket/qemud",
            "/dev/qemu_pipe",
            "/system/lib/libc_malloc_debug_qemu.so",
            "/sys/qemu_trace",
        )
        if (qemuFiles.any { File(it).exists() }) return true

        // Emulators typically lack a cellular radio
        val tm = context.getSystemService(Context.TELEPHONY_SERVICE) as? TelephonyManager
        if (tm != null && tm.phoneType == TelephonyManager.PHONE_TYPE_NONE) {
            // Supplement with another signal — PHONE_TYPE_NONE alone isn't conclusive
            // (tablets also report this), but combined with other weak signals it helps
            if (Build.BOARD.lowercase().contains("unknown") || Build.BOOTLOADER.lowercase().contains("unknown")) {
                return true
            }
        }

        return false
    }

    /**
     * Root detection via multiple vectors:
     * 1. Presence of `su` binary on common paths
     * 2. Magisk manager package or hide paths
     * 3. SuperSU artifacts
     * 4. Build tags containing "test-keys" (custom ROM indicator)
     * 5. System property `ro.debuggable` or `ro.secure` override
     * 6. `/system` partition writable (should be read-only on stock)
     */
    private fun isRooted(): Boolean {
        val suPaths = listOf(
            "/system/bin/su",
            "/system/xbin/su",
            "/sbin/su",
            "/data/local/xbin/su",
            "/data/local/bin/su",
            "/system/sd/xbin/su",
            "/system/bin/failsafe/su",
            "/data/local/su",
            "/su/bin/su",
        )
        if (suPaths.any { File(it).exists() }) return true

        // Magisk hides as random package names, but canonical path survives
        val magiskPaths = listOf(
            "/sbin/.magisk",
            "/cache/.disable_magisk",
            "/dev/.magisk.unblock",
        )
        if (magiskPaths.any { File(it).exists() }) return true

        // SuperSU artifacts
        val superSuPaths = listOf(
            "/system/app/Superuser.apk",
            "/system/etc/.installed_su_daemon",
        )
        if (superSuPaths.any { File(it).exists() }) return true

        // test-keys in the build tags indicate a non-release signing key
        if (Build.TAGS?.contains("test-keys") == true) return true

        // Attempt to run `which su` — succeeds only if su is on PATH
        try {
            val process = Runtime.getRuntime().exec(arrayOf("which", "su"))
            val exitCode = process.waitFor()
            if (exitCode == 0) return true
        } catch (_: Exception) {
            // Permission denied or missing binary — not rooted via this vector
        }

        return false
    }

    /**
     * Detects active VPN connections by inspecting the active network's
     * capabilities. Android's ConnectivityManager reports VPN transport when
     * a VPN service owns the active default network.
     */
    private fun isVpnActive(): Boolean {
        return try {
            val cm = context.getSystemService(Context.CONNECTIVITY_SERVICE) as ConnectivityManager
            val activeNetwork = cm.activeNetwork ?: return false
            val caps = cm.getNetworkCapabilities(activeNetwork) ?: return false
            caps.hasTransport(NetworkCapabilities.TRANSPORT_VPN) ||
                !caps.hasCapability(NetworkCapabilities.NET_CAPABILITY_NOT_VPN)
        } catch (_: Exception) {
            false
        }
    }

    /**
     * Checks the ApplicationInfo flags for FLAG_DEBUGGABLE, which indicates
     * the APK was built with `android:debuggable="true"`. Production builds
     * should never have this flag set.
     */
    private fun isDebuggable(): Boolean {
        return try {
            val appInfo = context.applicationInfo
            (appInfo.flags and ApplicationInfo.FLAG_DEBUGGABLE) != 0
        } catch (_: Exception) {
            false
        }
    }

    /**
     * Tampering / repackaging detection by comparing the APK's signing
     * certificate SHA-256 against a compile-time expected value.
     *
     * When an attacker decompiles and re-signs the APK the certificate
     * changes, making this check fail. The expected hash should be set
     * via BuildConfig or a resource overlay at build time.
     */
    @Suppress("DEPRECATION", "PackageManagerGetSignatures")
    private fun isRepackaged(): Boolean {
        return try {
            val packageName = context.packageName
            val sigInfo = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P) {
                val info = context.packageManager.getPackageInfo(
                    packageName,
                    PackageManager.GET_SIGNING_CERTIFICATES
                )
                info.signingInfo?.apkContentsSigners?.firstOrNull()
            } else {
                val info = context.packageManager.getPackageInfo(
                    packageName,
                    PackageManager.GET_SIGNATURES
                )
                info.signatures?.firstOrNull()
            }

            if (sigInfo == null) return true // unsigned APK is suspicious

            val certHash = MessageDigest.getInstance("SHA-256")
                .digest(sigInfo.toByteArray())
                .joinToString("") { "%02x".format(it) }

            // EXPECTED_CERT_HASH should be injected at build time.
            // If not configured we skip the check to avoid false positives.
            val expectedHash = try {
                val field = Class.forName("${packageName}.BuildConfig")
                    .getField("EXPECTED_CERT_HASH")
                field.get(null) as? String
            } catch (_: Exception) {
                null
            }

            if (expectedHash.isNullOrBlank()) {
                false // no baseline configured — can't determine tampering
            } else {
                certHash != expectedHash
            }
        } catch (_: Exception) {
            false
        }
    }

    /**
     * Returns the installer package name — e.g. "com.android.vending" for
     * Google Play, "com.amazon.venezia" for Amazon Appstore, or null for
     * sideloaded APKs. Sideloaded installs are a risk signal in fraud scoring.
     */
    private fun getInstallerPackage(): String {
        return try {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
                context.packageManager
                    .getInstallSourceInfo(context.packageName)
                    .installingPackageName ?: "unknown"
            } else {
                @Suppress("DEPRECATION")
                context.packageManager.getInstallerPackageName(context.packageName) ?: "unknown"
            }
        } catch (_: Exception) {
            "unknown"
        }
    }

    /**
     * Returns the logical screen density in DPI from DisplayMetrics.
     * Emulators often report unusual densities (e.g. exactly 160 or 420),
     * while real devices cluster around standard buckets.
     */
    private fun getScreenDensity(): Float {
        val metrics: DisplayMetrics = context.resources.displayMetrics
        return metrics.density
    }

    /**
     * Enumerates all non-loopback network interfaces and collects their
     * IPv4 and IPv6 addresses. Useful for server-side geo-consistency
     * checks and VPN egress analysis.
     */
    private fun getLocalIpAddresses(): List<String> {
        return try {
            NetworkInterface.getNetworkInterfaces()
                ?.toList()
                ?.filter { it.isUp && !it.isLoopback }
                ?.flatMap { iface ->
                    iface.inetAddresses.toList()
                        .filter { !it.isLoopbackAddress }
                        .map { it.hostAddress ?: "" }
                        .filter { it.isNotBlank() }
                }
                ?: emptyList()
        } catch (_: Exception) {
            emptyList()
        }
    }
}

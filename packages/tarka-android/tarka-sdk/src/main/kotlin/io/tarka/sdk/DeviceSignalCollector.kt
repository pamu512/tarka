package io.tarka.sdk

import android.content.Context
import android.content.pm.PackageManager
import android.os.Build
import android.provider.Settings
import java.security.MessageDigest

/**
 * Collects Android environment signals aligned with the Decision API [DeviceSignals] contract.
 * [deviceId] is a stable hash per install (not a hardware serial).
 */
class DeviceSignalCollector(private val context: Context) {

    fun collect(): DeviceSignals {
        val pm = context.packageManager
        val pkg = context.packageName
        val installer = try {
            @Suppress("DEPRECATION")
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
                pm.getInstallSourceInfo(pkg).installingPackageName
            } else {
                pm.getInstallerPackageName(pkg)
            }
        } catch (_: Exception) {
            null
        }
        val expectedInstaller = "com.android.vending"
        val isRepackaged = installer != null && installer != expectedInstaller

        val isEmu = Build.FINGERPRINT.startsWith("generic")
            || Build.FINGERPRINT.startsWith("unknown")
            || Build.MODEL.contains("google_sdk")
            || Build.MODEL.contains("Emulator")
            || Build.MODEL.contains("Android SDK built for x86")
            || Build.MANUFACTURER.contains("Genymotion")
            || Build.BRAND.startsWith("generic") && Build.DEVICE.startsWith("generic")
            || "google_sdk" == Build.PRODUCT

        val devSettings = Settings.Global.getInt(
            context.contentResolver,
            Settings.Global.DEVELOPMENT_SETTINGS_ENABLED,
            0,
        ) == 1

        val vpn = try {
            val cm = context.getSystemService(Context.CONNECTIVITY_SERVICE) as? android.net.ConnectivityManager
            val active = cm?.activeNetwork
            val caps = if (active != null) cm.getNetworkCapabilities(active) else null
            caps?.hasTransport(android.net.NetworkCapabilities.TRANSPORT_VPN) == true
        } catch (_: Exception) {
            false
        }

        val mockLoc = try {
            Settings.Secure.getInt(context.contentResolver, "mock_location", 0) != 0
        } catch (_: Exception) {
            false
        }

        val lang = context.resources.configuration.locales[0]?.toString()

        return DeviceSignals(
            isEmulator = isEmu,
            isVpn = vpn,
            isSpoofedLocation = false,
            isBot = false,
            isRepackaged = isRepackaged,
            webdriverDetected = false,
            headlessDetected = false,
            automationDetected = devSettings,
            vpnInterfaceDetected = vpn,
            mockLocationDetected = mockLoc,
            timezoneGeoMismatch = false,
            canvasFpHash = null,
            webglRenderer = null,
            screenRes = screenResolution(),
            touchSupport = true,
            batteryApiPresent = true,
            language = lang,
            platformVersion = "Android ${Build.VERSION.RELEASE} (SDK ${Build.VERSION.SDK_INT})",
        )
    }

    private fun screenResolution(): String {
        val dm = context.resources.displayMetrics
        return "${dm.widthPixels}x${dm.heightPixels}"
    }

    /**
     * Deterministic device id: SHA-256 hex of package + installer + model + androidId (scoped).
     */
    fun computeDeviceId(): String {
        val androidId = Settings.Secure.getString(context.contentResolver, Settings.Secure.ANDROID_ID) ?: "unknown"
        val raw = listOf(
            context.packageName,
            Build.MODEL,
            Build.MANUFACTURER,
            androidId,
        ).joinToString("|")
        val md = MessageDigest.getInstance("SHA-256")
        val digest = md.digest(raw.toByteArray(Charsets.UTF_8))
        return digest.joinToString("") { "%02x".format(it) }
    }

    fun buildDeviceContext(): DeviceContext {
        val signals = collect()
        val id = computeDeviceId()
        return DeviceContext(deviceId = id, platform = "android", signals = signals, attestation = null)
    }
}

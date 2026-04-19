package io.tarka.sdk

import android.content.Context
import android.os.Build
import android.provider.Settings
import android.net.ConnectivityManager
import android.net.NetworkCapabilities
import java.io.File
import java.security.MessageDigest

/** Collects Android signals for [DeviceContext] (Decision API contract). */
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
        val isRepackaged = installer != null && installer != "com.android.vending"

        val isEmu = Build.FINGERPRINT.startsWith("generic")
            || Build.MODEL.contains("Emulator", ignoreCase = true)
            || Build.PRODUCT.contains("sdk", ignoreCase = true)

        val devSettings = Settings.Global.getInt(
            context.contentResolver,
            Settings.Global.DEVELOPMENT_SETTINGS_ENABLED,
            0,
        ) == 1

        val vpn = try {
            val cm = context.getSystemService(Context.CONNECTIVITY_SERVICE) as? ConnectivityManager
            val active = cm?.activeNetwork
            val caps = if (active != null) cm.getNetworkCapabilities(active) else null
            caps?.hasTransport(NetworkCapabilities.TRANSPORT_VPN) == true
        } catch (_: Exception) {
            false
        }

        val mockLoc = try {
            Settings.Secure.getInt(context.contentResolver, "mock_location", 0) != 0
        } catch (_: Exception) {
            false
        }

        val lang = context.resources.configuration.locales[0]?.toString()
        val dm = context.resources.displayMetrics
        val screen = "${dm.widthPixels}x${dm.heightPixels}"

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
            screenRes = screen,
            touchSupport = true,
            batteryApiPresent = true,
            language = lang,
            platformVersion = "Android ${Build.VERSION.RELEASE} (SDK ${Build.VERSION.SDK_INT})",
            isRooted = isRooted(),
        )
    }

    private fun isRooted(): Boolean {
        val paths = listOf(
            "/system/bin/su",
            "/system/xbin/su",
            "/sbin/su",
        )
        return paths.any { File(it).exists() }
    }

    fun computeDeviceId(): String {
        val androidId = Settings.Secure.getString(context.contentResolver, Settings.Secure.ANDROID_ID) ?: "unknown"
        val raw = listOf(context.packageName, Build.MODEL, Build.MANUFACTURER, androidId).joinToString("|")
        val digest = MessageDigest.getInstance("SHA-256").digest(raw.toByteArray(Charsets.UTF_8))
        return digest.joinToString("") { "%02x".format(it) }
    }

    fun buildDeviceContext(): DeviceContext {
        return DeviceContext(deviceId = computeDeviceId(), platform = "android", signals = collect(), attestation = null)
    }
}

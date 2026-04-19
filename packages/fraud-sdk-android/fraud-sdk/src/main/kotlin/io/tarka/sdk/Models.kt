package io.tarka.sdk

import org.json.JSONObject

data class DeviceSignals(
    val isEmulator: Boolean = false,
    val isVpn: Boolean = false,
    val isSpoofedLocation: Boolean = false,
    val isBot: Boolean = false,
    val isRepackaged: Boolean = false,
    val webdriverDetected: Boolean = false,
    val headlessDetected: Boolean = false,
    val automationDetected: Boolean = false,
    val vpnInterfaceDetected: Boolean = false,
    val mockLocationDetected: Boolean = false,
    val timezoneGeoMismatch: Boolean = false,
    val canvasFpHash: String? = null,
    val webglRenderer: String? = null,
    val screenRes: String? = null,
    val touchSupport: Boolean? = null,
    val batteryApiPresent: Boolean? = null,
    val language: String? = null,
    val platformVersion: String? = null,
    val isRooted: Boolean? = null,
) {
    fun toJsonObject(): JSONObject = JSONObject().apply {
        put("is_emulator", isEmulator)
        put("is_vpn", isVpn)
        put("is_spoofed_location", isSpoofedLocation)
        put("is_bot", isBot)
        put("is_repackaged", isRepackaged)
        put("webdriver_detected", webdriverDetected)
        put("headless_detected", headlessDetected)
        put("automation_detected", automationDetected)
        put("vpn_interface_detected", vpnInterfaceDetected)
        put("mock_location_detected", mockLocationDetected)
        put("timezone_geo_mismatch", timezoneGeoMismatch)
        put("canvas_fp_hash", canvasFpHash ?: JSONObject.NULL)
        put("webgl_renderer", webglRenderer ?: JSONObject.NULL)
        put("screen_res", screenRes ?: JSONObject.NULL)
        touchSupport?.let { put("touch_support", it) } ?: put("touch_support", JSONObject.NULL)
        batteryApiPresent?.let { put("battery_api_present", it) } ?: put("battery_api_present", JSONObject.NULL)
        put("language", language ?: JSONObject.NULL)
        put("platform_version", platformVersion ?: JSONObject.NULL)
        isRooted?.let { put("is_rooted", it) }
    }
}

data class Attestation(
    val nonce: String,
    val token: String,
    val provider: String,
    /** Canonical: obtained | absent | failed | disabled | unsupported */
    val status: String = "obtained",
    /** none | low | medium | high — client hint; server may override after verify */
    val confidenceTier: String = "medium",
    val failureReason: String? = null,
    val attestationSchemaVersion: Int = 1,
) {
    fun toJsonObject(): JSONObject = JSONObject().apply {
        put("nonce", nonce)
        put("token", token)
        put("provider", provider)
        put("status", status)
        put("confidence_tier", confidenceTier)
        failureReason?.let { put("failure_reason", it) } ?: put("failure_reason", JSONObject.NULL)
        put("attestation_schema_version", attestationSchemaVersion)
    }
}

data class DeviceContext(
    val deviceId: String,
    val platform: String = "android",
    val signals: DeviceSignals,
    val attestation: Attestation? = null,
) {
    fun toJsonObject(): JSONObject = JSONObject().apply {
        put("device_id", deviceId)
        put("platform", platform)
        put("signals", signals.toJsonObject())
        attestation?.let { put("attestation", it.toJsonObject()) } ?: put("attestation", JSONObject.NULL)
    }
}

data class EvaluateRequest(
    val tenantId: String,
    val eventType: String,
    val entityId: String,
    val sessionId: String? = null,
    val payload: Map<String, Any?> = emptyMap(),
    val deviceContext: DeviceContext? = null,
    val metadata: Map<String, Any?> = emptyMap(),
) {
    fun toJsonObject(): JSONObject = JSONObject().apply {
        put("tenant_id", tenantId)
        put("event_type", eventType)
        put("entity_id", entityId)
        sessionId?.let { put("session_id", it) }
        put("payload", jsonObjectFromMap(payload))
        deviceContext?.let { put("device_context", it.toJsonObject()) }
        if (metadata.isNotEmpty()) put("metadata", jsonObjectFromMap(metadata))
    }
}

data class EvaluateResponse(
    val traceId: String,
    val decision: String,
    val score: Double,
    val tags: List<String>,
    val inferenceContext: InferenceContext? = null,
    val recommendedAction: String? = null,
)

data class DriverExplainEntry(
    val reason: String,
    val category: String,
    val label: String,
)

data class MlTopFactor(
    val code: String,
    val description: String,
    val impact: String,
)

data class InferenceContext(
    val schemaVersion: String,
    val calibrationProfile: String,
    val expectedCalibrationVersion: Int,
    val integrityConfidence: Double,
    val tamperRisk: Double,
    val networkTrust: Double,
    val replayRisk: Double,
    val geoConsistencyRisk: Double,
    val topSignals: List<String>,
    val confidenceTier: String,
    val driverReasons: List<String>,
    val colocationRisk: Double,
    val copresenceRisk: Double,
    val impossibleTravelRisk: Double,
    val velocityEvents5m: Int,
    val velocityEvents1h: Int,
    val velocityEvents24h: Int,
    val confidenceTierLabel: String? = null,
    val driverExplain: List<DriverExplainEntry> = emptyList(),
    val mlTopFactors: List<MlTopFactor> = emptyList(),
    val mlSummary: String? = null,
    val mlModel: String? = null,
)

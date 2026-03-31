package io.fraudstack.sdk

import android.content.Context
import com.google.android.play.core.integrity.IntegrityManagerFactory
import com.google.android.play.core.integrity.IntegrityTokenRequest
import okhttp3.*
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONObject
import java.io.IOException
import kotlin.coroutines.resume
import kotlin.coroutines.resumeWithException
import kotlin.coroutines.suspendCoroutine

class FraudStackClient(
    private val baseUrl: String,
    private val apiKey: String = "",
    private val ctx: Context
) {
    private val http = OkHttpClient()
    private val collector = DeviceSignalCollector(ctx)
    private val json = "application/json".toMediaType()

    /** Request an attestation nonce from the server */
    suspend fun requestChallenge(tenantId: String): String {
        val body = JSONObject().put("tenant_id", tenantId).toString().toRequestBody(json)
        val req = Request.Builder().url("$baseUrl/v1/attestation/challenge").post(body).build()
        val resp = suspendCall(req)
        return JSONObject(resp).getString("nonce")
    }

    /** Full evaluate with device signals + Play Integrity attestation */
    suspend fun evaluate(tenantId: String, eventType: String, entityId: String, payload: JSONObject = JSONObject()): JSONObject {
        val signals = collector.collect()
        val deviceId = collector.deviceId()

        val signalsJson = JSONObject().apply {
            put("is_emulator", signals.isEmulator)
            put("is_vpn", signals.isVpn)
            put("is_spoofed_location", signals.isSpoofedLocation)
            put("is_bot", signals.isBot)
            put("is_repackaged", signals.isRepackaged)
            put("automation_detected", signals.automationDetected)
            put("vpn_interface_detected", signals.vpnInterfaceDetected)
            put("mock_location_detected", signals.mockLocationDetected)
            put("screen_res", signals.screenRes)
            put("language", signals.language)
            put("platform_version", signals.platformVersion)
        }

        val deviceContext = JSONObject().apply {
            put("device_id", deviceId)
            put("platform", "android")
            put("signals", signalsJson)
        }

        // Play Integrity attestation (best-effort)
        try {
            val nonce = requestChallenge(tenantId)
            val token = requestPlayIntegrity(nonce)
            deviceContext.put("attestation", JSONObject().apply {
                put("nonce", nonce)
                put("token", token)
                put("provider", "play_integrity")
            })
        } catch (_: Exception) { /* attestation optional */ }

        val reqBody = JSONObject().apply {
            put("tenant_id", tenantId)
            put("event_type", eventType)
            put("entity_id", entityId)
            put("payload", payload)
            put("device_context", deviceContext)
        }

        val httpReq = Request.Builder()
            .url("$baseUrl/v1/decisions/evaluate")
            .addHeader("Content-Type", "application/json")
            .also { if (apiKey.isNotEmpty()) it.addHeader("X-API-Key", apiKey) }
            .post(reqBody.toString().toRequestBody(json))
            .build()

        return JSONObject(suspendCall(httpReq))
    }

    // TODO: Replace with real Play Integrity integration
    private suspend fun requestPlayIntegrity(nonce: String): String {
        val manager = IntegrityManagerFactory.create(ctx)
        val request = IntegrityTokenRequest.builder().setNonce(nonce).build()
        return suspendCoroutine { cont ->
            manager.requestIntegrityToken(request)
                .addOnSuccessListener { resp -> cont.resume(resp.token()) }
                .addOnFailureListener { e -> cont.resumeWithException(e) }
        }
    }

    private suspend fun suspendCall(req: Request): String = suspendCoroutine { cont ->
        http.newCall(req).enqueue(object : Callback {
            override fun onFailure(call: Call, e: IOException) = cont.resumeWithException(e)
            override fun onResponse(call: Call, response: Response) {
                val body = response.body?.string() ?: ""
                if (!response.isSuccessful) cont.resumeWithException(IOException("HTTP ${response.code}: $body"))
                else cont.resume(body)
            }
        })
    }
}

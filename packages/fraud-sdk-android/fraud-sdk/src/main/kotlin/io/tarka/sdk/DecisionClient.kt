package io.tarka.sdk

import android.content.Context
import com.google.android.gms.tasks.Tasks
import com.google.android.play.core.integrity.IntegrityManagerFactory
import com.google.android.play.core.integrity.IntegrityTokenRequest
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONObject
import java.util.concurrent.TimeUnit

/**
 * Tarka Decision API client: evaluate, attestation challenge, optional Play Integrity.
 */
class DecisionClient(
    baseUrl: String,
    private val apiKey: String = "",
    private val timeoutMs: Long = 10_000L,
    private val autoCollectSignals: Boolean = true,
    private val enablePlayIntegrity: Boolean = true,
    context: Context? = null,
) {
    private val base = baseUrl.trimEnd('/')
    private var appContext: Context? = context?.applicationContext

    private val http = OkHttpClient.Builder()
        .connectTimeout(timeoutMs, TimeUnit.MILLISECONDS)
        .readTimeout(timeoutMs, TimeUnit.MILLISECONDS)
        .writeTimeout(timeoutMs, TimeUnit.MILLISECONDS)
        .build()

    private var collector: DeviceSignalCollector? = appContext?.let { DeviceSignalCollector(it) }

    fun setContextForSignals(ctx: Context) {
        appContext = ctx.applicationContext
        collector = DeviceSignalCollector(ctx.applicationContext)
    }

    private val json = "application/json; charset=utf-8".toMediaType()

    private fun headers(): okhttp3.Headers {
        val b = okhttp3.Headers.Builder().add("Content-Type", "application/json")
        if (apiKey.isNotEmpty()) b.add("X-API-Key", apiKey)
        return b.build()
    }

    fun requestChallenge(tenantId: String): String {
        val body = JSONObject().put("tenant_id", tenantId).toString()
        val req = Request.Builder()
            .url("$base/v1/attestation/challenge")
            .post(body.toRequestBody(json))
            .headers(headers())
            .build()
        http.newCall(req).execute().use { resp ->
            if (!resp.isSuccessful) error(resp.body?.string() ?: "challenge failed")
            return JSONObject(resp.body!!.string()).getString("nonce")
        }
    }

    /** Synchronous Play Integrity token (uses Tasks.await; call from worker if needed). */
    fun requestPlayIntegrityToken(nonce: String, ctx: Context): String {
        val mgr = IntegrityManagerFactory.create(ctx.applicationContext)
        val req = IntegrityTokenRequest.builder().setNonce(nonce).build()
        val task = mgr.requestIntegrityToken(req)
        return Tasks.await(task).token()
    }

    fun evaluate(request: EvaluateRequest): EvaluateResponse {
        var req = request
        if (autoCollectSignals && req.deviceContext == null && collector != null) {
            val built = collector!!.buildDeviceContext()
            req = req.copy(deviceContext = maybeAttest(built, req.tenantId))
        } else if (req.deviceContext != null) {
            req = req.copy(deviceContext = maybeAttest(req.deviceContext!!, req.tenantId))
        }

        val body = req.toJsonObject().toString()
        val httpReq = Request.Builder()
            .url("$base/v1/decisions/evaluate")
            .post(body.toRequestBody(json))
            .headers(headers())
            .build()
        http.newCall(httpReq).execute().use { resp ->
            if (!resp.isSuccessful) error(resp.body?.string() ?: "evaluate failed")
            return parseEvaluateResponse(JSONObject(resp.body!!.string()))
        }
    }

    private fun maybeAttest(dc: DeviceContext, tenantId: String): DeviceContext {
        if (!enablePlayIntegrity || dc.attestation != null) return dc
        val ctx = appContext ?: return dc
        return try {
            val nonce = requestChallenge(tenantId)
            val token = requestPlayIntegrityToken(nonce, ctx)
            dc.copy(
                attestation = Attestation(
                    nonce = nonce,
                    token = token,
                    provider = "play_integrity",
                    status = "obtained",
                    confidenceTier = "medium",
                ),
            )
        } catch (_: Exception) {
            dc.copy(
                attestation = Attestation(
                    nonce = "",
                    token = "",
                    provider = "play_integrity",
                    status = "failed",
                    confidenceTier = "none",
                    failureReason = "client_error",
                ),
            )
        }
    }
}

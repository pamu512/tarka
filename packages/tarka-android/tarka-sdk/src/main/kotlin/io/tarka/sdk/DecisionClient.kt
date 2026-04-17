package io.tarka.sdk

import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONObject
import java.util.concurrent.TimeUnit

/**
 * HTTP client for the Tarka Decision API — mirrors [packages/fraud-sdk-typescript] evaluate flow.
 *
 * Pass [context] to enable automatic [DeviceSignalCollector] device_context attachment.
 */
class DecisionClient(
    baseUrl: String,
    private val apiKey: String = "",
    private val timeoutMs: Long = 10_000L,
    private val autoCollectSignals: Boolean = true,
    context: android.content.Context? = null,
) {
    private val base = baseUrl.trimEnd('/')
    private val http: OkHttpClient = OkHttpClient.Builder()
        .connectTimeout(timeoutMs, TimeUnit.MILLISECONDS)
        .readTimeout(timeoutMs, TimeUnit.MILLISECONDS)
        .writeTimeout(timeoutMs, TimeUnit.MILLISECONDS)
        .build()

    private var collector: DeviceSignalCollector? = context?.let { DeviceSignalCollector(it.applicationContext) }

    fun setContextForSignals(ctx: android.content.Context) {
        collector = DeviceSignalCollector(ctx.applicationContext)
    }

    fun requestChallenge(tenantId: String): String {
        val body = JSONObject().put("tenant_id", tenantId).toString()
        val req = Request.Builder()
            .url("$base/v1/attestation/challenge")
            .post(body.toRequestBody(JSON))
            .headers(headers())
            .build()
        http.newCall(req).execute().use { resp ->
            if (!resp.isSuccessful) error(resp.body?.string() ?: "challenge failed")
            val json = JSONObject(resp.body!!.string())
            return json.getString("nonce")
        }
    }

    /**
     * Evaluate with optional [deviceContext]. When null and [autoCollectSignals] and [collector] are set,
     * builds context and attaches best-effort browser-style attestation is skipped on Android —
     * use [PlayIntegrityAttestation] for Play Integrity tokens.
     */
    fun evaluate(request: EvaluateRequest): EvaluateResponse {
        var req = request
        if (autoCollectSignals && req.deviceContext == null && collector != null) {
            val ctx = collector!!.buildDeviceContext()
            req = req.copy(deviceContext = ctx)
        }
        val body = req.toJsonObject().toString()
        val httpReq = Request.Builder()
            .url("$base/v1/decisions/evaluate")
            .post(body.toRequestBody(JSON))
            .headers(headers())
            .build()
        http.newCall(httpReq).execute().use { resp ->
            if (!resp.isSuccessful) error(resp.body?.string() ?: "evaluate failed")
            return parseEvaluate(JSONObject(resp.body!!.string()))
        }
    }

    fun getAudit(traceId: String, tenantId: String): JSONObject {
        val url = "$base/v1/audit/$traceId?tenant_id=${java.net.URLEncoder.encode(tenantId, Charsets.UTF_8.name())}"
        val req = Request.Builder().url(url).get().headers(headers()).build()
        http.newCall(req).execute().use { resp ->
            if (!resp.isSuccessful) error(resp.body?.string() ?: "audit failed")
            return JSONObject(resp.body!!.string())
        }
    }

    private fun headers(): okhttp3.Headers {
        val b = okhttp3.Headers.Builder().add("Content-Type", "application/json")
        if (apiKey.isNotEmpty()) b.add("X-API-Key", apiKey)
        return b.build()
    }

    private fun parseEvaluate(o: JSONObject): EvaluateResponse {
        val inf = if (o.has("inference_context") && !o.isNull("inference_context")) {
            jsonObjectToMap(o.getJSONObject("inference_context"))
        } else {
            null
        }
        val tags = mutableListOf<String>()
        val arr = o.optJSONArray("tags")
        if (arr != null) {
            for (i in 0 until arr.length()) tags.add(arr.getString(i))
        }
        return EvaluateResponse(
            traceId = o.getString("trace_id"),
            decision = o.getString("decision"),
            score = o.getDouble("score"),
            tags = tags,
            inferenceContext = inf,
            recommendedAction = if (o.has("recommended_action") && !o.isNull("recommended_action")) {
                o.getString("recommended_action")
            } else {
                null
            },
        )
    }

    companion object {
        private val JSON = "application/json; charset=utf-8".toMediaType()
    }
}

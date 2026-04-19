package io.tarka.sdk

import org.json.JSONArray
import org.json.JSONObject

internal fun jsonObjectFromMap(map: Map<String, Any?>): JSONObject {
    val o = JSONObject()
    for ((k, v) in map) {
        when (v) {
            null -> o.put(k, JSONObject.NULL)
            is Map<*, *> @Suppress("UNCHECKED_CAST") -> o.put(k, jsonObjectFromMap(v as Map<String, Any?>))
            is List<*> -> o.put(k, jsonArrayFromList(v))
            is Boolean -> o.put(k, v)
            is Number -> o.put(k, v)
            is String -> o.put(k, v)
            else -> o.put(k, v.toString())
        }
    }
    return o
}

private fun jsonArrayFromList(list: List<*>): JSONArray {
    val a = JSONArray()
    for (v in list) {
        when (v) {
            null -> a.put(JSONObject.NULL)
            is Map<*, *> @Suppress("UNCHECKED_CAST") -> a.put(jsonObjectFromMap(v as Map<String, Any?>))
            is List<*> -> a.put(jsonArrayFromList(v))
            is Boolean -> a.put(v)
            is Number -> a.put(v)
            is String -> a.put(v)
            else -> a.put(v.toString())
        }
    }
    return a
}

internal fun parseEvaluateResponse(json: JSONObject): EvaluateResponse {
    val tags = mutableListOf<String>()
    val arr = json.optJSONArray("tags")
    if (arr != null) {
        for (i in 0 until arr.length()) tags.add(arr.getString(i))
    }
    val inf = if (json.has("inference_context") && !json.isNull("inference_context")) {
        parseInferenceContext(json.getJSONObject("inference_context"))
    } else {
        null
    }
    return EvaluateResponse(
        traceId = json.getString("trace_id"),
        decision = json.getString("decision"),
        score = json.getDouble("score"),
        tags = tags,
        inferenceContext = inf,
        recommendedAction = if (json.has("recommended_action") && !json.isNull("recommended_action")) {
            json.getString("recommended_action")
        } else {
            null
        },
    )
}

private fun parseInferenceContext(o: JSONObject): InferenceContext {
    fun s(name: String, d: String = ""): String = if (o.has(name) && !o.isNull(name)) o.optString(name, d) else d
    fun d(name: String): Double = if (o.has(name) && !o.isNull(name)) o.optDouble(name, 0.0) else 0.0
    fun i(name: String): Int = if (o.has(name) && !o.isNull(name)) o.optInt(name, 0) else 0
    fun sl(name: String): List<String> {
        val a = o.optJSONArray(name) ?: return emptyList()
        val out = ArrayList<String>(a.length())
        for (idx in 0 until a.length()) {
            if (!a.isNull(idx)) out.add(a.optString(idx))
        }
        return out
    }
    fun mlTopFactors(name: String): List<MlTopFactor> {
        val a = o.optJSONArray(name) ?: return emptyList()
        val out = ArrayList<MlTopFactor>(a.length())
        for (idx in 0 until a.length()) {
            val item = a.optJSONObject(idx) ?: continue
            out.add(
                MlTopFactor(
                    code = item.optString("code", ""),
                    description = item.optString("description", ""),
                    impact = item.optString("impact", ""),
                ),
            )
        }
        return out
    }
    fun driverExplain(name: String): List<DriverExplainEntry> {
        val a = o.optJSONArray(name) ?: return emptyList()
        val out = ArrayList<DriverExplainEntry>(a.length())
        for (idx in 0 until a.length()) {
            val item = a.optJSONObject(idx) ?: continue
            out.add(
                DriverExplainEntry(
                    reason = item.optString("reason", ""),
                    category = item.optString("category", ""),
                    label = item.optString("label", ""),
                ),
            )
        }
        return out
    }
    return InferenceContext(
        schemaVersion = s("schema_version"),
        calibrationProfile = s("calibration_profile", "default"),
        expectedCalibrationVersion = i("expected_calibration_version").coerceAtLeast(1),
        integrityConfidence = d("integrity_confidence"),
        tamperRisk = d("tamper_risk"),
        networkTrust = d("network_trust"),
        replayRisk = d("replay_risk"),
        geoConsistencyRisk = d("geo_consistency_risk"),
        topSignals = sl("top_signals"),
        confidenceTier = s("confidence_tier"),
        driverReasons = sl("driver_reasons"),
        colocationRisk = d("colocation_risk"),
        copresenceRisk = d("copresence_risk"),
        impossibleTravelRisk = d("impossible_travel_risk"),
        velocityEvents5m = i("velocity_events_5m"),
        velocityEvents1h = i("velocity_events_1h"),
        velocityEvents24h = i("velocity_events_24h"),
        confidenceTierLabel = if (o.has("confidence_tier_label") && !o.isNull("confidence_tier_label")) s("confidence_tier_label") else null,
        driverExplain = driverExplain("driver_explain"),
        mlTopFactors = mlTopFactors("ml_top_factors"),
        mlSummary = if (o.has("ml_summary") && !o.isNull("ml_summary")) s("ml_summary") else null,
        mlModel = if (o.has("ml_model") && !o.isNull("ml_model")) s("ml_model") else null,
    )
}

private fun jsonObjectToMap(o: JSONObject): Map<String, Any?> {
    val out = linkedMapOf<String, Any?>()
    val keys = o.keys()
    while (keys.hasNext()) {
        val k = keys.next()
        val v = o.get(k)
        out[k] = when (v) {
            JSONObject.NULL -> null
            is JSONObject -> jsonObjectToMap(v)
            is org.json.JSONArray -> jsonArrayToList(v)
            else -> v
        }
    }
    return out
}

private fun jsonArrayToList(a: org.json.JSONArray): List<Any?> {
    val out = ArrayList<Any?>(a.length())
    for (i in 0 until a.length()) {
        val v = a.get(i)
        out.add(
            when (v) {
                JSONObject.NULL -> null
                is JSONObject -> jsonObjectToMap(v)
                is org.json.JSONArray -> jsonArrayToList(v)
                else -> v
            },
        )
    }
    return out
}

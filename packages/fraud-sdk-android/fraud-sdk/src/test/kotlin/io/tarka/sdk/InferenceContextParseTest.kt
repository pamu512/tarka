package io.tarka.sdk

import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Test

class InferenceContextParseTest {
    @Test
    fun parseEvaluateResponse_inferenceContextTyped() {
        val body = JSONObject(
            """
            {
              "trace_id":"tr1",
              "decision":"review",
              "score":72.5,
              "tags":["sdk:vpn"],
              "inference_context":{
                "schema_version":"3",
                "calibration_profile":"default",
                "expected_calibration_version":1,
                "integrity_confidence":0.63,
                "tamper_risk":0.1,
                "network_trust":0.4,
                "replay_risk":0.2,
                "geo_consistency_risk":0.3,
                "top_signals":["sdk:vpn"],
                "confidence_tier":"medium",
                "driver_reasons":["hostile_or_anonymous_network_path"],
                "colocation_risk":0.0,
                "copresence_risk":0.0,
                "impossible_travel_risk":0.0,
                "velocity_events_5m":1,
                "velocity_events_1h":3,
                "velocity_events_24h":9,
                "confidence_tier_label":"Medium",
                "driver_explain":[{"reason":"hostile_or_anonymous_network_path","category":"network","label":"Network path"}]
              }
            }
            """.trimIndent(),
        )
        val resp = parseEvaluateResponse(body)
        assertEquals("tr1", resp.traceId)
        assertNotNull(resp.inferenceContext)
        assertEquals("3", resp.inferenceContext!!.schemaVersion)
        assertEquals("medium", resp.inferenceContext!!.confidenceTier)
        assertEquals(1, resp.inferenceContext!!.driverExplain.size)
    }
}

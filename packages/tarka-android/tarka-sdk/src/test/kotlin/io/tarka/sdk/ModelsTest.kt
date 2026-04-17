package io.tarka.sdk

import org.junit.Assert.assertEquals
import org.junit.Test

class ModelsTest {
    @Test
    fun evaluateRequest_serializesPayload() {
        val req = EvaluateRequest(
            tenantId = "t",
            eventType = "login",
            entityId = "e",
            payload = mapOf("amount" to 10.0),
        )
        val o = req.toJsonObject()
        assertEquals("t", o.getString("tenant_id"))
        assertEquals(10.0, o.getJSONObject("payload").getDouble("amount"), 0.001)
    }
}

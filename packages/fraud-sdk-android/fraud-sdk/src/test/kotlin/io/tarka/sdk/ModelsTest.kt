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

    @Test
    fun deviceSignals_serializesIsRootedWhenPresent() {
        val signals = DeviceSignals(isRooted = true)
        val o = signals.toJsonObject()
        assertEquals(true, o.getBoolean("is_rooted"))
    }

    @Test
    fun deviceSignals_omitsIsRootedWhenNull() {
        val signals = DeviceSignals()
        val o = signals.toJsonObject()
        assertEquals(false, o.has("is_rooted"))
    }
}

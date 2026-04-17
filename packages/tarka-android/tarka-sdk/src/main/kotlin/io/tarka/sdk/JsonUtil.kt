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

internal fun jsonObjectToMap(o: JSONObject): Map<String, Any?> {
    val out = linkedMapOf<String, Any?>()
    val keys = o.keys()
    while (keys.hasNext()) {
        val k = keys.next()
        val v = o.get(k)
        out[k] = when (v) {
            JSONObject.NULL -> null
            is JSONObject -> jsonObjectToMap(v)
            is JSONArray -> jsonArrayToList(v)
            else -> v
        }
    }
    return out
}

private fun jsonArrayToList(a: JSONArray): List<Any?> {
    val out = ArrayList<Any?>(a.length())
    for (i in 0 until a.length()) {
        val v = a.get(i)
        out.add(
            when (v) {
                JSONObject.NULL -> null
                is JSONObject -> jsonObjectToMap(v)
                is JSONArray -> jsonArrayToList(v)
                else -> v
            },
        )
    }
    return out
}

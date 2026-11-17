package dev.subg.app

import org.json.JSONArray
import org.json.JSONObject
import kotlin.math.ln

/** CC1101 packet-mode metadata (demodulated bytes + RSSI/LQI), NOT raw RF. */
data class Packet(
    val n: Int, val tsUs: Long, val frequencyHz: Long, val modulation: String, val data: ByteArray,
    val rssiDbm: Double, val lqi: Int, val crcOk: Boolean, val hostTimeMs: Long,
    var protocol: String = "unknown", var classification: String = "",
) {
    val hex: String get() = data.toHex()

    fun toJson(): JSONObject = JSONObject().put("n", n).put("ts_us", tsUs).put("frequency_hz", frequencyHz)
        .put("modulation", modulation).put("len", data.size).put("data", hex).put("rssi_dbm", rssiDbm).put("lqi", lqi)
        .put("crc_ok", crcOk).put("host_time", hostTimeMs / 1000.0).put("protocol", protocol).put("classification", classification)

    companion object {
        fun fromEvent(e: JSONObject) = Packet(
            e.optInt("n"), e.optLong("ts_us"), e.optLong("frequency_hz"), e.optString("modulation"),
            e.optString("data").hexToBytes(), e.optDouble("rssi_dbm"), e.optInt("lqi"), e.optBoolean("crc_ok", true),
            System.currentTimeMillis())
    }
}

class Analyzer(private val rssiCapacity: Int = 300) {
    val packets = ArrayList<Packet>()
    val rssi = ArrayDeque<Double>()
    private val byPayload = HashMap<String, Int>()

    private data class Sig(val name: String, val prefix: String, val len: Int)
    private val sigs = listOf(
        Sig("RFB lab test pattern", "5246422D544553542D", 12),
        Sig("RFB simulator frame", "A5014217", 6),
    )

    @Synchronized fun addRssi(v: Double) {
        rssi.addLast(v)
        while (rssi.size > rssiCapacity) rssi.removeFirst()
    }

    @Synchronized fun add(p: Packet): Packet {
        p.protocol = sigs.firstOrNull { p.hex.startsWith(it.prefix) && p.data.size == it.len }?.name ?: "unknown"
        val count = (byPayload[p.hex] ?: 0) + 1
        byPayload[p.hex] = count
        p.classification = when {
            p.protocol != "unknown" -> "identified"
            !p.crcOk -> "crc-failed"
            count >= 2 -> "repeating-fixed"
            packets.takeLast(50).any { it.data.size == p.data.size && hamming(it.data, p.data) in 1..8 } -> "repeating-variable"
            p.data.size >= 8 && entropy(p.data) > 0.85 * log2(minOf(256, p.data.size).toDouble()) -> "high-entropy"
            else -> "structured-unknown"
        }
        packets.add(p)
        addRssi(p.rssiDbm)
        return p
    }

    @Synchronized fun clear() { packets.clear(); rssi.clear(); byPayload.clear() }

    @Synchronized fun uniqueCount() = byPayload.size

    @Synchronized fun summary(): JSONObject {
        val classes = JSONObject()
        packets.groupingBy { it.classification }.eachCount().forEach { (k, v) -> classes.put(k, v) }
        val repeated = JSONArray()
        byPayload.filter { it.value >= 2 }.entries.sortedByDescending { it.value }.take(20)
            .forEach { repeated.put(JSONObject().put("data", it.key).put("count", it.value)) }
        val iv = packets.zipWithNext { a, b -> (b.tsUs - a.tsUs) / 1000.0 }
        return JSONObject().put("packets", packets.size).put("unique_payloads", byPayload.size).put("classes", classes)
            .put("repeated", repeated)
            .put("mean_interval_ms", if (iv.isEmpty()) JSONObject.NULL else iv.average())
            .put("note", "CC1101 packet-mode metadata only; no raw RF waveform/IQ is captured.")
    }

    companion object {
        fun hamming(a: ByteArray, b: ByteArray) = a.indices.sumOf { Integer.bitCount((a[it].toInt() xor b[it].toInt()) and 0xFF) }
        fun log2(x: Double) = ln(x) / ln(2.0)
        fun entropy(d: ByteArray): Double {
            val n = d.size.toDouble()
            return d.groupBy { it }.values.sumOf { val p = it.size / n; -p * log2(p) }
        }
    }
}

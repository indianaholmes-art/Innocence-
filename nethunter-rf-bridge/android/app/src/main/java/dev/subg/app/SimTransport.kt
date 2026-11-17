package dev.subg.app

import org.json.JSONObject
import kotlin.random.Random

/** In-app simulator speaking firmware protocol v1, for use without hardware. */
class SimTransport : Transport {
    override val name = "Simulator"
    @Volatile override var isOpen = false
        private set
    private var onLine: ((String) -> Unit)? = null
    private var thread: Thread? = null
    private val rng = Random(System.nanoTime())
    private val t0 = System.nanoTime()
    private val lock = Any()
    private var seq = 0
    private var packets = 0
    private var rx = false
    private var rssiMs = 0
    private var freq = 433_920_000L
    private var modulation = "ASK/OOK"
    private var dataRate = 4.8
    private var syncWord = "D391"

    private fun tUs() = (System.nanoTime() - t0) / 1000

    private fun emit(o: JSONObject) {
        o.put("seq", seq++)
        onLine?.invoke(o.toString())
    }

    private fun event(type: String, o: JSONObject) { o.put("type", type); o.put("t_us", tUs()); emit(o) }

    override fun open(onLine: (String) -> Unit, onClosed: (String) -> Unit) {
        this.onLine = onLine
        isOpen = true
        event("hello", JSONObject().put("fw", "nethunter-rf-bridge").put("version", "1.0.0-sim").put("proto", 1)
            .put("radio", "SIM-CC1101").put("radio_present", true))
        thread = Thread({
            var nextPkt = System.currentTimeMillis() + 800
            var nextRssi = 0L
            var nextHb = System.currentTimeMillis() + 5000
            while (isOpen) {
                val now = System.currentTimeMillis()
                synchronized(lock) {
                    if (rx && now >= nextPkt) { event("packet", makePacket()); nextPkt = now + 500 + rng.nextLong(1200) }
                    if (rssiMs > 0 && now >= nextRssi) {
                        event("rssi", JSONObject().put("rssi_dbm", rssi()).put("frequency_hz", freq)); nextRssi = now + rssiMs
                    }
                    if (now >= nextHb) {
                        event("heartbeat", JSONObject().put("state", if (rx) "receiving" else "idle").put("packets", packets))
                        nextHb = now + 5000
                    }
                }
                Thread.sleep(10)
            }
            onClosed("closed")
        }, "subg-sim").apply { isDaemon = true; start() }
    }

    private fun rssi() = Math.round((-105 + rng.nextDouble() * 8) * 10) / 10.0

    private fun makePacket(): JSONObject {
        packets++
        val data = if (packets % 3 != 0) byteArrayOf(0xA5.toByte(), 0x01, 0x42, 0x17, (packets / 10).toByte(), 0x5A)
        else ByteArray(4 + rng.nextInt(12)).also { rng.nextBytes(it) }
        return JSONObject().put("n", packets).put("ts_us", tUs()).put("frequency_hz", freq).put("modulation", modulation)
            .put("len", data.size).put("rssi_dbm", Math.round((-60 - rng.nextDouble() * 30) * 10) / 10.0)
            .put("lqi", rng.nextInt(48)).put("crc_ok", true).put("data", data.toHex())
    }

    private fun status() = JSONObject().put("chip", "SIM-CC1101").put("present", true)
        .put("state", if (rx) "receiving" else "idle").put("frequency_hz", freq).put("modulation", modulation)
        .put("data_rate_kbps", dataRate).put("deviation_khz", 47.6).put("rx_bandwidth_khz", 203.0)
        .put("sync_word", syncWord).put("sync_required", true).put("crc", false).put("max_packet_len", 61)
        .put("packets", packets).put("crc_errors", 0).put("rssi_stream_ms", rssiMs)

    override fun writeLine(line: String) {
        val req = try { JSONObject(line) } catch (e: Exception) { JSONObject().put("cmd", line.trim()) }
        val cmd = req.optString("cmd")
        val args = req.optJSONObject("args") ?: JSONObject()
        val resp = JSONObject().put("type", "response").put("cmd", cmd).put("ok", true)
        if (req.has("id")) resp.put("id", req.getInt("id"))
        fun fail(code: String, msg: String) { resp.put("ok", false).put("error", JSONObject().put("code", code).put("message", msg)) }
        val d = JSONObject()
        synchronized(lock) {
            when (cmd) {
                "PING" -> d.put("pong", true)
                "GET_VERSION" -> d.put("fw", "nethunter-rf-bridge").put("version", "1.0.0-sim").put("proto", 1)
                "DEVICE_INFO" -> d.put("fw", "nethunter-rf-bridge").put("version", "1.0.0-sim").put("proto", 1)
                    .put("board", "SIMULATOR").put("chip_model", "ESP32-S3 (simulated)").put("radio", "SIM-CC1101")
                    .put("simulation", true)
                    .put("pins", JSONObject().put("sck", 12).put("mosi", 11).put("miso", 13).put("cs", 10).put("gdo0", 4).put("gdo2", 5))
                "RADIO_STATUS" -> copyInto(status(), d)
                "SET_FREQUENCY" -> {
                    val hz = if (args.has("hz")) args.getLong("hz") else Math.round(args.optDouble("mhz", 0.0) * 1e6)
                    if (!Bands.supported(hz)) fail("UNSUPPORTED_FREQUENCY", "CC1101 bands: 300-348, 387-464, 779-928 MHz")
                    else { freq = hz; d.put("frequency_hz", hz) }
                }
                "SET_CONFIG", "SET_MODULATION" -> {
                    if (args.has("modulation")) modulation = args.getString("modulation")
                    if (args.has("data_rate_kbps")) dataRate = args.getDouble("data_rate_kbps")
                    if (args.has("sync_word")) syncWord = args.getString("sync_word").uppercase()
                    copyInto(status(), d)
                }
                "START_RECEIVE" -> { rx = true; d.put("state", "receiving") }
                "STOP_RECEIVE" -> { rx = false; d.put("state", "idle") }
                "GET_RSSI" -> d.put("rssi_dbm", rssi()).put("frequency_hz", freq)
                "RSSI_STREAM" -> { rssiMs = args.optInt("interval_ms", 0); d.put("interval_ms", rssiMs) }
                "RESET_RADIO" -> { rx = false; copyInto(status(), d) }
                "TX_TEST" -> if (!args.optBoolean("confirm_authorized")) fail("NOT_AUTHORIZED", "confirm_authorized required")
                    else d.put("sent", args.optInt("count", 1))
                else -> fail("UNKNOWN_COMMAND", "unknown cmd: $cmd")
            }
            if (resp.getBoolean("ok")) resp.put("data", d)
            emit(resp)
        }
    }

    private fun copyInto(src: JSONObject, dst: JSONObject) { for (k in src.keys()) dst.put(k, src.get(k)) }

    override fun close() { isOpen = false; thread?.join(300) }
}

object Bands {
    fun supported(hz: Long) = hz in 300_000_000L..348_000_000L || hz in 387_000_000L..464_000_000L || hz in 779_000_000L..928_000_000L
}

fun ByteArray.toHex(): String = joinToString("") { "%02X".format(it.toInt() and 0xFF) }
fun String.hexToBytes(): ByteArray = ByteArray(length / 2) { substring(it * 2, it * 2 + 2).toInt(16).toByte() }

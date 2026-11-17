package dev.subg.app

import org.json.JSONObject
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicInteger

class DeviceException(val code: String, message: String) : Exception("$code: $message")

/**
 * Protocol v1 client (see docs/PROTOCOL.md). [command] blocks, so call it off
 * the main thread. Events are delivered on the transport's reader thread.
 */
class BridgeClient(val transport: Transport, private val onEvent: (JSONObject) -> Unit, private val onDisconnect: (String) -> Unit) {
    private val ids = AtomicInteger(1)
    private class Pending { val latch = CountDownLatch(1); @Volatile var resp: JSONObject? = null }
    private val pending = ConcurrentHashMap<Int, Pending>()
    @Volatile var badLines = 0
        private set

    fun connect(): JSONObject {
        transport.open(::onLine) { reason ->
            pending.values.forEach { it.resp = JSONObject().put("ok", false).put("error", JSONObject().put("code", "DISCONNECTED").put("message", reason)); it.latch.countDown() }
            onDisconnect(reason)
        }
        val v = command("GET_VERSION")
        if (v.optString("fw") != "nethunter-rf-bridge") throw DeviceException("NOT_RF_BRIDGE", "device answered as '${v.optString("fw")}'")
        return v
    }

    private fun onLine(line: String) {
        val msg = try { JSONObject(line) } catch (e: Exception) { badLines++; return }  // boot chatter etc.
        if (msg.optString("type") == "response" && msg.has("id")) {
            pending[msg.getInt("id")]?.let { it.resp = msg; it.latch.countDown() }
            return
        }
        onEvent(msg)
    }

    fun command(cmd: String, args: JSONObject? = null, timeoutMs: Long = 3000): JSONObject {
        val id = ids.getAndIncrement()
        val p = Pending()
        pending[id] = p
        try {
            val req = JSONObject().put("id", id).put("cmd", cmd)
            if (args != null) req.put("args", args)
            transport.writeLine(req.toString())
            if (!p.latch.await(timeoutMs, TimeUnit.MILLISECONDS)) throw DeviceException("TIMEOUT", "no response to $cmd")
            val r = p.resp!!
            if (!r.optBoolean("ok")) {
                val e = r.optJSONObject("error") ?: JSONObject()
                throw DeviceException(e.optString("code", "ERROR"), e.optString("message"))
            }
            return r.optJSONObject("data") ?: JSONObject()
        } finally {
            pending.remove(id)
        }
    }

    fun close() = transport.close()
}

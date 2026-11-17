package dev.subg.app

import android.app.Activity
import android.app.AlertDialog
import android.app.PendingIntent
import android.content.BroadcastReceiver
import android.content.ContentValues
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.graphics.Color
import android.graphics.Typeface
import android.hardware.usb.UsbDevice
import android.hardware.usb.UsbManager
import android.os.Build
import android.os.Bundle
import android.os.Environment
import android.os.Handler
import android.os.Looper
import android.provider.MediaStore
import android.text.InputType
import android.view.Gravity
import android.view.View
import android.view.ViewGroup.LayoutParams.MATCH_PARENT
import android.view.ViewGroup.LayoutParams.WRAP_CONTENT
import android.widget.AdapterView
import android.widget.ArrayAdapter
import android.widget.Button
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.Spinner
import android.widget.TextView
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.concurrent.Executors

/**
 * subGdev: standalone Android controller for the ESP32-S3 + CC1101 RF Bridge.
 * Talks to the board through the Android USB Host API, so it needs no root,
 * no NetHunter chroot and no kernel serial driver.
 */
class MainActivity : Activity() {
    companion object {
        private const val ACTION_USB_PERMISSION = "dev.subg.app.USB_PERMISSION"
        private val MODULATIONS = arrayOf("ASK/OOK", "2-FSK", "GFSK", "4-FSK", "MSK")
        private const val MAX_LOG_ROWS = 200
    }

    private val ui = Handler(Looper.getMainLooper())
    private val io = Executors.newSingleThreadExecutor()
    private lateinit var usb: UsbManager
    private var client: BridgeClient? = null
    private val analyzer = Analyzer()
    private var receiving = false
    private var deviceInfo = JSONObject()
    private var radioStatus = JSONObject()
    private var suppressSpinner = true

    private lateinit var tvLink: TextView
    private lateinit var tvInfo: TextView
    private lateinit var tvStats: TextView
    private lateinit var tvLog: TextView
    private lateinit var etFreq: EditText
    private lateinit var spMod: Spinner
    private lateinit var btnConnect: Button
    private lateinit var btnRx: Button
    private lateinit var graph: RssiGraphView
    private val logRows = ArrayDeque<String>()

    // ------------------------------------------------------------------ USB events
    private val usbReceiver = object : BroadcastReceiver() {
        override fun onReceive(ctx: Context, intent: Intent) {
            val dev: UsbDevice? = if (Build.VERSION.SDK_INT >= 33) intent.getParcelableExtra(UsbManager.EXTRA_DEVICE, UsbDevice::class.java)
            else @Suppress("DEPRECATION") intent.getParcelableExtra(UsbManager.EXTRA_DEVICE)
            when (intent.action) {
                ACTION_USB_PERMISSION -> {
                    if (dev != null && intent.getBooleanExtra(UsbManager.EXTRA_PERMISSION_GRANTED, false)) connectUsb(dev)
                    else setLink("USB permission denied - tap Connect and allow access", Color.RED)
                }
                UsbManager.ACTION_USB_DEVICE_DETACHED -> {
                    if (client?.transport is UsbCdcTransport) { disconnect(); setLink("Device unplugged", Color.YELLOW) }
                }
            }
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        usb = getSystemService(Context.USB_SERVICE) as UsbManager
        buildUi()
        val f = IntentFilter().apply { addAction(ACTION_USB_PERMISSION); addAction(UsbManager.ACTION_USB_DEVICE_DETACHED) }
        if (Build.VERSION.SDK_INT >= 33) registerReceiver(usbReceiver, f, Context.RECEIVER_NOT_EXPORTED)
        else @Suppress("UnspecifiedRegisterReceiverFlag") registerReceiver(usbReceiver, f)
        handleIntent(intent)
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        handleIntent(intent)
    }

    private fun handleIntent(intent: Intent?) {
        if (intent?.action == UsbManager.ACTION_USB_DEVICE_ATTACHED && client == null) findAndConnect()
    }

    override fun onDestroy() {
        unregisterReceiver(usbReceiver)
        val c = client
        client = null
        io.execute { try { if (receiving) c?.command("STOP_RECEIVE") } catch (_: Exception) {}; c?.close() }
        io.shutdown()
        super.onDestroy()
    }

    // --------------------------------------------------------------------------- UI
    private fun dp(v: Int) = (v * resources.displayMetrics.density).toInt()

    private fun button(label: String, onClick: () -> Unit) = Button(this).apply {
        text = label; isAllCaps = false; setOnClickListener { onClick() }
        layoutParams = LinearLayout.LayoutParams(0, WRAP_CONTENT, 1f)
    }

    private fun row(vararg views: View) = LinearLayout(this).apply {
        orientation = LinearLayout.HORIZONTAL; gravity = Gravity.CENTER_VERTICAL
        views.forEach { addView(it) }
    }

    private fun mono(size: Float) = TextView(this).apply { typeface = Typeface.MONOSPACE; textSize = size; setTextColor(Color.rgb(220, 230, 235)) }

    private fun buildUi() {
        tvLink = TextView(this).apply { textSize = 15f; setTypeface(typeface, Typeface.BOLD) }
        tvInfo = mono(12f)
        tvStats = mono(12f)
        tvLog = mono(11f)
        graph = RssiGraphView(this).apply { layoutParams = LinearLayout.LayoutParams(MATCH_PARENT, dp(140)) }
        etFreq = EditText(this).apply {
            hint = "MHz"; setText("433.92")
            inputType = InputType.TYPE_CLASS_NUMBER or InputType.TYPE_NUMBER_FLAG_DECIMAL
            layoutParams = LinearLayout.LayoutParams(0, WRAP_CONTENT, 1.2f)
        }
        spMod = Spinner(this).apply {
            adapter = ArrayAdapter(this@MainActivity, android.R.layout.simple_spinner_dropdown_item, MODULATIONS)
            layoutParams = LinearLayout.LayoutParams(0, WRAP_CONTENT, 1.3f)
            onItemSelectedListener = object : AdapterView.OnItemSelectedListener {
                override fun onItemSelected(p: AdapterView<*>?, v: View?, pos: Int, id: Long) {
                    if (!suppressSpinner) runCmd("SET_CONFIG", JSONObject().put("modulation", MODULATIONS[pos])) { refreshStatus() }
                }
                override fun onNothingSelected(p: AdapterView<*>?) {}
            }
        }
        btnConnect = button("Connect") { if (client == null) findAndConnect() else disconnect() }
        btnRx = button("Start RX") { toggleRx() }

        val root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(12), dp(12), dp(12), dp(12))
            setBackgroundColor(Color.rgb(10, 14, 18))
            addView(TextView(this@MainActivity).apply { text = "subGdev · sub-GHz RF Bridge"; textSize = 20f; setTextColor(Color.rgb(61, 220, 132)) })
            addView(tvLink)
            addView(row(btnConnect, button("Simulator") { connectSim() }))
            addView(tvInfo)
            addView(row(etFreq, button("Set freq") { setFreq() }, spMod))
            addView(row(btnRx, button("Save") { save() }, button("Clear") { analyzer.clear(); logRows.clear(); render() }))
            addView(row(button("Lab TX test") { txTest() }, button("Diagnostics") { showDiag() }))
            addView(graph)
            addView(tvStats)
            addView(tvLog)
        }
        setContentView(ScrollView(this).apply { addView(root) })
        setLink("Disconnected - plug the RF Bridge into USB-C (OTG)", Color.LTGRAY)
        render()
    }

    private fun setLink(msg: String, color: Int) = ui.post { tvLink.text = msg; tvLink.setTextColor(color) }

    private fun toast(msg: String) = ui.post { tvStats.text = msg + "\n" + tvStats.text }

    private fun render() {
        val s = radioStatus
        tvInfo.text = buildString {
            if (deviceInfo.length() > 0) append("${deviceInfo.optString("board")} · fw ${deviceInfo.optString("version")} · ${deviceInfo.optString("radio")}\n")
            if (s.length() > 0) {
                append("%s  %.4f MHz  %s  %.1f kBaud\n".format(s.optString("state"), s.optLong("frequency_hz") / 1e6,
                    s.optString("modulation"), s.optDouble("data_rate_kbps")))
                append("BW %.0f kHz · sync %s · crc %s".format(s.optDouble("rx_bandwidth_khz"), s.optString("sync_word"), s.optBoolean("crc")))
                if (s.has("last_error")) append("\n⚠ ${s.optString("last_error")}")
            }
        }
        btnRx.text = if (receiving) "Stop RX" else "Start RX"
        btnConnect.text = if (client == null) "Connect" else "Disconnect"
        synchronized(analyzer) {
            graph.setValues(analyzer.rssi.toList())
            tvStats.text = "packets ${analyzer.packets.size} · unique ${analyzer.uniqueCount()}\n" +
                "Packet mode: only frames matching modulation/rate/sync are received (not raw RF)."
        }
        tvLog.text = logRows.joinToString("\n")
    }

    // ---------------------------------------------------------------- connection
    private fun findAndConnect() {
        val devs = usb.deviceList.values.filter { UsbCdcTransport.isCandidate(it) }
        if (devs.isEmpty()) {
            val all = usb.deviceList.values.joinToString { "%04X:%04X".format(it.vendorId, it.productId) }
            setLink(if (all.isEmpty()) "No USB device. Check OTG cable / enable OTG in settings" else "Unsupported USB device(s): $all", Color.RED)
            return
        }
        val dev = devs.first()
        if (usb.hasPermission(dev)) connectUsb(dev)
        else {
            val flags = if (Build.VERSION.SDK_INT >= 31) PendingIntent.FLAG_MUTABLE else 0
            val pi = PendingIntent.getBroadcast(this, 0, Intent(ACTION_USB_PERMISSION).setPackage(packageName), flags)
            usb.requestPermission(dev, pi)
            setLink("Requesting USB permission…", Color.YELLOW)
        }
    }

    private fun connectUsb(dev: UsbDevice) = connect(UsbCdcTransport(usb, dev))

    private fun connectSim() { if (client != null) disconnect(); connect(SimTransport()) }

    private fun connect(t: Transport) {
        setLink("Connecting to ${t.name}…", Color.YELLOW)
        io.execute {
            val c = BridgeClient(t, ::onEvent) { reason -> ui.post { if (client?.transport === t) { client = null; receiving = false; setLink("Link lost: $reason", Color.RED); render() } } }
            try {
                c.connect()
                client = c
                deviceInfo = c.command("DEVICE_INFO")
                radioStatus = c.command("RADIO_STATUS")
                receiving = radioStatus.optString("state") == "receiving"
                c.command("RSSI_STREAM", JSONObject().put("interval_ms", 250))
                setLink("Connected: ${t.name}" + if (deviceInfo.optBoolean("simulation")) " (simulation)" else "", Color.rgb(61, 220, 132))
                ui.post { syncControls(); render() }
            } catch (e: Exception) {
                c.close()
                client = null
                setLink("Connect failed: ${e.message}", Color.RED)
            }
        }
    }

    private fun disconnect() {
        val c = client ?: return
        client = null
        io.execute { try { if (receiving) c.command("STOP_RECEIVE"); c.command("RSSI_STREAM", JSONObject().put("interval_ms", 0)) } catch (_: Exception) {}; c.close() }
        receiving = false
        setLink("Disconnected", Color.LTGRAY)
        render()
    }

    private fun syncControls() {
        etFreq.setText("%.4f".format(Locale.US, radioStatus.optLong("frequency_hz", 433_920_000) / 1e6))
        suppressSpinner = true
        val i = MODULATIONS.indexOf(radioStatus.optString("modulation"))
        if (i >= 0) spMod.setSelection(i)
        ui.postDelayed({ suppressSpinner = false }, 300)
    }

    private fun onEvent(ev: JSONObject) {
        when (ev.optString("type")) {
            "packet" -> {
                val p = analyzer.add(Packet.fromEvent(ev))
                val row = "#%-4d len %-2d %6.1fdBm lqi%-3d %s %s".format(p.n, p.data.size, p.rssiDbm, p.lqi,
                    if (p.protocol != "unknown") p.protocol else p.classification, p.hex)
                ui.post { logRows.addFirst(row); while (logRows.size > MAX_LOG_ROWS) logRows.removeLast(); render() }
            }
            "rssi" -> { analyzer.addRssi(ev.optDouble("rssi_dbm")); ui.post { render() } }
            "hello" -> if (receiving) runCmd("START_RECEIVE") {}  // board rebooted: restore RX
        }
    }

    /** Runs a device command on the I/O thread; [then] runs on the UI thread on success. */
    private fun runCmd(cmd: String, args: JSONObject? = null, then: (JSONObject) -> Unit) {
        val c = client ?: run { toast("Not connected"); return }
        io.execute {
            try { val r = c.command(cmd, args); ui.post { then(r) } }
            catch (e: Exception) { toast("$cmd failed: ${e.message}") }
        }
    }

    private fun refreshStatus() = runCmd("RADIO_STATUS") { radioStatus = it; receiving = it.optString("state") == "receiving"; render() }

    // ------------------------------------------------------------------- actions
    private fun toggleRx() = runCmd(if (receiving) "STOP_RECEIVE" else "START_RECEIVE") { refreshStatus() }

    private fun setFreq() {
        val mhz = etFreq.text.toString().toDoubleOrNull()
        if (mhz == null || !Bands.supported(Math.round(mhz * 1e6))) {
            toast("CC1101 bands: 300-348, 387-464, 779-928 MHz (use your module's band)")
            return
        }
        runCmd("SET_FREQUENCY", JSONObject().put("hz", Math.round(mhz * 1e6))) { refreshStatus() }
    }

    private fun txTest() {
        AlertDialog.Builder(this)
            .setTitle("Lab test transmission")
            .setMessage("Sends 3 fixed 'RFB-TEST-nnn' frames at about -10 dBm on %.4f MHz.\n\nOnly continue if you are permitted to transmit on this frequency (e.g. licence-free ISM band, shielded test setup)."
                .format(radioStatus.optLong("frequency_hz") / 1e6))
            .setPositiveButton("I am authorized") { _, _ ->
                runCmd("TX_TEST", JSONObject().put("count", 3).put("confirm_authorized", true)) { toast("Sent ${it.optInt("sent")} test frames") }
            }
            .setNegativeButton("Cancel", null)
            .show()
    }

    private fun showDiag() {
        val c = client
        io.execute {
            val d = JSONObject()
            d.put("app", "subGdev 1.0.0").put("android", Build.VERSION.RELEASE).put("model", Build.MODEL)
            val devs = JSONArray()
            usb.deviceList.values.forEach {
                devs.put(JSONObject().put("name", it.deviceName).put("vid", "%04X".format(it.vendorId)).put("pid", "%04X".format(it.productId))
                    .put("interfaces", it.interfaceCount).put("permission", usb.hasPermission(it)).put("supported", UsbCdcTransport.isCandidate(it)))
            }
            d.put("usb_devices", devs)
            if (c != null) {
                d.put("bad_lines", c.badLines)
                try { d.put("device_info", c.command("DEVICE_INFO")); d.put("radio_status", c.command("RADIO_STATUS")) }
                catch (e: Exception) { d.put("error", e.message) }
            }
            ui.post {
                AlertDialog.Builder(this).setTitle("Diagnostics").setMessage(d.toString(2))
                    .setPositiveButton("Save") { _, _ -> io.execute { writeFile("subgdev-diag", "json", d.toString(2)) } }
                    .setNegativeButton("Close", null).show()
            }
        }
    }

    private fun save() {
        io.execute {
            val pk: List<Packet>
            val summary: JSONObject
            synchronized(analyzer) { pk = analyzer.packets.toList(); summary = analyzer.summary() }
            val json = JSONObject().put("format", "nethunter-rf-capture").put("format_version", 1)
                .put("host_version", "subGdev-1.0.0").put("capture_type", "cc1101-packet-metadata (not raw RF)")
                .put("meta", JSONObject().put("device", deviceInfo).put("radio", radioStatus))
                .put("packets", JSONArray().apply { pk.forEach { put(it.toJson()) } })
                .put("analysis", summary)
            val csv = StringBuilder("n,host_time,ts_us,frequency_hz,modulation,len,rssi_dbm,lqi,crc_ok,protocol,classification,data\n")
            pk.forEach { p ->
                csv.append("${p.n},${p.hostTimeMs / 1000.0},${p.tsUs},${p.frequencyHz},${p.modulation},${p.data.size},${p.rssiDbm},${p.lqi},${if (p.crcOk) "True" else "False"},\"${p.protocol}\",${p.classification},${p.hex}\n")
            }
            val stamp = SimpleDateFormat("yyyyMMdd-HHmmss", Locale.US).format(Date())
            val a = writeFile("capture-$stamp", "json", json.toString(2))
            writeFile("capture-$stamp", "csv", csv.toString())
            toast("Saved ${pk.size} packets → $a (+ .csv)")
        }
    }

    /** Writes to Download/subGdev (Android 10+) or the app's external files dir. Same format as the NetHunter CLI. */
    private fun writeFile(stem: String, ext: String, content: String): String {
        val name = "$stem.$ext"
        return try {
            if (Build.VERSION.SDK_INT >= 29) {
                val values = ContentValues().apply {
                    put(MediaStore.MediaColumns.DISPLAY_NAME, name)
                    put(MediaStore.MediaColumns.MIME_TYPE, if (ext == "csv") "text/csv" else "application/json")
                    put(MediaStore.MediaColumns.RELATIVE_PATH, Environment.DIRECTORY_DOWNLOADS + "/subGdev")
                }
                val uri = contentResolver.insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI, values) ?: error("MediaStore insert failed")
                contentResolver.openOutputStream(uri)!!.use { it.write(content.toByteArray()) }
                "Download/subGdev/$name"
            } else {
                val f = File(getExternalFilesDir(null), name)
                f.writeText(content)
                f.absolutePath
            }
        } catch (e: Exception) {
            toast("Save failed: ${e.message}")
            "(failed)"
        }
    }
}

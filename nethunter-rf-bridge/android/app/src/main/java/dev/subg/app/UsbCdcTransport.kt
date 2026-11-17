package dev.subg.app

import android.hardware.usb.UsbConstants
import android.hardware.usb.UsbDevice
import android.hardware.usb.UsbDeviceConnection
import android.hardware.usb.UsbEndpoint
import android.hardware.usb.UsbInterface
import android.hardware.usb.UsbManager
import java.io.ByteArrayOutputStream
import java.io.IOException

/**
 * USB CDC-ACM driver implemented directly on the Android USB Host API.
 * Needs no root, no kernel cdc_acm driver and no chroot: Android hands the
 * app raw access to the device once the user grants permission.
 *
 * Supports the ESP32-S3 native USB (and any standard CDC-ACM device).
 */
class UsbCdcTransport(private val manager: UsbManager, private val device: UsbDevice) : Transport {

    override val name: String = "USB %04X:%04X %s".format(device.vendorId, device.productId, device.productName ?: "")
    @Volatile override var isOpen = false
        private set

    private var conn: UsbDeviceConnection? = null
    private var ctrlIface: UsbInterface? = null
    private var dataIface: UsbInterface? = null
    private var epIn: UsbEndpoint? = null
    private var epOut: UsbEndpoint? = null
    private var reader: Thread? = null
    private val writeLock = Any()

    companion object {
        const val ESPRESSIF_VID = 0x303A
        private const val SET_LINE_CODING = 0x20
        private const val SET_CONTROL_LINE_STATE = 0x22
        private const val REQTYPE_HOST_TO_IFACE = 0x21

        fun isCandidate(d: UsbDevice): Boolean {
            if (d.vendorId == ESPRESSIF_VID) return true
            for (i in 0 until d.interfaceCount) if (d.getInterface(i).interfaceClass == UsbConstants.USB_CLASS_CDC_DATA) return true
            return false
        }
    }

    override fun open(onLine: (String) -> Unit, onClosed: (String) -> Unit) {
        val c = manager.openDevice(device) ?: throw IOException("openDevice failed (permission not granted?)")
        // Locate CDC control (class 2) and data (class 10) interfaces.
        for (i in 0 until device.interfaceCount) {
            val itf = device.getInterface(i)
            when (itf.interfaceClass) {
                UsbConstants.USB_CLASS_COMM -> if (ctrlIface == null) ctrlIface = itf
                UsbConstants.USB_CLASS_CDC_DATA -> if (dataIface == null) dataIface = itf
            }
        }
        val data = dataIface ?: run {
            c.close()
            throw IOException("No CDC data interface: unsupported device (CH340/CP210x boards need the native USB port)")
        }
        for (e in 0 until data.endpointCount) {
            val ep = data.getEndpoint(e)
            if (ep.type != UsbConstants.USB_ENDPOINT_XFER_BULK) continue
            if (ep.direction == UsbConstants.USB_DIR_IN) epIn = ep else epOut = ep
        }
        if (epIn == null || epOut == null) { c.close(); throw IOException("CDC bulk endpoints not found") }
        ctrlIface?.let { c.claimInterface(it, true) }
        if (!c.claimInterface(data, true)) { c.close(); throw IOException("claimInterface failed (device busy?)") }

        val ctrlIndex = ctrlIface?.id ?: 0
        // 115200 8N1 (ignored by native USB, needed by some CDC bridges)
        val coding = byteArrayOf(0x00, 0xC2.toByte(), 0x01, 0x00, 0, 0, 8)
        c.controlTransfer(REQTYPE_HOST_TO_IFACE, SET_LINE_CODING, 0, ctrlIndex, coding, coding.size, 500)
        // DTR=1 RTS=0: TinyUSB/Arduino CDC only sends once DTR is asserted.
        c.controlTransfer(REQTYPE_HOST_TO_IFACE, SET_CONTROL_LINE_STATE, 0x01, ctrlIndex, null, 0, 500)

        conn = c
        isOpen = true
        reader = Thread({ readLoop(onLine, onClosed) }, "subg-usb-reader").apply { isDaemon = true; start() }
    }

    private fun readLoop(onLine: (String) -> Unit, onClosed: (String) -> Unit) {
        val buf = ByteArray(epIn!!.maxPacketSize.coerceAtLeast(64) * 8)
        val line = ByteArrayOutputStream()
        var reason = "closed"
        while (isOpen) {
            val c = conn ?: break
            val n = c.bulkTransfer(epIn, buf, buf.size, 200)
            if (n < 0) {
                // -1 = timeout or error; a detached device is caught by the ACTION_USB_DEVICE_DETACHED receiver.
                continue
            }
            for (i in 0 until n) {
                val b = buf[i]
                if (b == '\n'.code.toByte()) {
                    val s = line.toString(Charsets.UTF_8.name()).trim()
                    line.reset()
                    if (s.isNotEmpty()) onLine(s)
                } else if (b != '\r'.code.toByte()) {
                    if (line.size() < 65536) line.write(b.toInt()) else line.reset()
                }
            }
        }
        if (!isOpen) reason = "closed"
        onClosed(reason)
    }

    override fun writeLine(line: String) {
        val c = conn ?: throw IOException("not connected")
        val bytes = (line + "\n").toByteArray(Charsets.UTF_8)
        synchronized(writeLock) {
            var off = 0
            val mps = epOut!!.maxPacketSize
            while (off < bytes.size) {
                val len = minOf(mps, bytes.size - off)
                val chunk = bytes.copyOfRange(off, off + len)
                val n = c.bulkTransfer(epOut, chunk, len, 1000)
                if (n < 0) throw IOException("USB write failed")
                off += n
            }
        }
    }

    override fun close() {
        if (!isOpen && conn == null) return
        isOpen = false
        reader?.join(500)
        conn?.let { c ->
            try { c.controlTransfer(REQTYPE_HOST_TO_IFACE, SET_CONTROL_LINE_STATE, 0, ctrlIface?.id ?: 0, null, 0, 200) } catch (_: Exception) {}
            dataIface?.let { c.releaseInterface(it) }
            ctrlIface?.let { c.releaseInterface(it) }
            c.close()
        }
        conn = null
    }
}

package dev.subg.app

import android.content.Context
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.graphics.Path
import android.view.View

/** Scrolling RSSI history plot, -110..-20 dBm. */
class RssiGraphView(context: Context) : View(context) {
    private var values: List<Double> = emptyList()
    private val line = Paint(Paint.ANTI_ALIAS_FLAG).apply { color = Color.rgb(61, 220, 132); strokeWidth = 4f; style = Paint.Style.STROKE }
    private val grid = Paint().apply { color = Color.argb(60, 255, 255, 255); strokeWidth = 1f }
    private val text = Paint(Paint.ANTI_ALIAS_FLAG).apply { color = Color.LTGRAY; textSize = 26f }
    private val lo = -110.0
    private val hi = -20.0

    fun setValues(v: List<Double>) { values = v; invalidate() }

    override fun onDraw(canvas: Canvas) {
        canvas.drawColor(Color.rgb(16, 24, 32))
        val w = width.toFloat()
        val h = height.toFloat()
        for (db in listOf(-100, -80, -60, -40)) {
            val y = y(db.toDouble(), h)
            canvas.drawLine(0f, y, w, y, grid)
            canvas.drawText("$db", 4f, y - 4f, text)
        }
        if (values.size < 2) return
        val step = w / (values.size - 1).coerceAtLeast(1)
        val p = Path()
        values.forEachIndexed { i, v -> val x = i * step; if (i == 0) p.moveTo(x, y(v, h)) else p.lineTo(x, y(v, h)) }
        canvas.drawPath(p, line)
        canvas.drawText("%.1f dBm".format(values.last()), w - 170f, 30f, text)
    }

    private fun y(v: Double, h: Float) = (h - ((v.coerceIn(lo, hi) - lo) / (hi - lo) * h)).toFloat()
}

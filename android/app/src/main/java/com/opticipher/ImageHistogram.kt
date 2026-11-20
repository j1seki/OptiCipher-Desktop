package com.opticipher

import android.content.Context
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.view.View

internal class ImageHistogram(context: Context) : View(context) {
    private val paint = Paint()
    private var counts = IntArray(0)

    fun setChannel(label: String, channel: Int, histogram: IntArray) {
        contentDescription = "$label histogram, pixel values 0 to 255"
        paint.color = listOf(Color.rgb(219, 68, 68), Color.rgb(0, 153, 102),
            Color.rgb(46, 122, 219), Color.rgb(140, 102, 187))[channel]
        counts = histogram
        invalidate()
    }

    override fun onDraw(canvas: Canvas) {
        super.onDraw(canvas)
        val max = counts.maxOrNull() ?: return
        if (max == 0) return
        val bucket = width / counts.size.toFloat()
        val scale = height / max.toFloat()
        for ((index, count) in counts.withIndex()) {
            canvas.drawRect(index * bucket, height - count * scale, (index + 1) * bucket, height.toFloat(), paint)
        }
    }
}

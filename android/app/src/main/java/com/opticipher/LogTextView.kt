package com.opticipher

import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.os.PersistableBundle
import android.graphics.Typeface
import android.util.AttributeSet
import android.view.Gravity
import android.view.MotionEvent
import android.widget.Toast
import androidx.appcompat.widget.AppCompatEditText

/** Selectable log text with independent vertical and horizontal scrolling. */
class LogTextView @JvmOverloads constructor(context: Context, attrs: AttributeSet? = null) :
    AppCompatEditText(context, attrs) {
    init {
        keyListener = null
        showSoftInputOnFocus = false
        setTextIsSelectable(true)
        isCursorVisible = false
        typeface = Typeface.MONOSPACE
        gravity = Gravity.TOP or Gravity.START
        isVerticalScrollBarEnabled = true
    }

    fun wrapLines(wrap: Boolean) {
        setHorizontallyScrolling(!wrap)
        isHorizontalScrollBarEnabled = !wrap
        if (wrap) scrollTo(0, scrollY)
    }

    override fun onTouchEvent(event: MotionEvent): Boolean {
        parent.requestDisallowInterceptTouchEvent(event.actionMasked != MotionEvent.ACTION_UP &&
            event.actionMasked != MotionEvent.ACTION_CANCEL)
        return super.onTouchEvent(event)
    }

    private fun textForCopy(): String {
        val content = text?.toString().orEmpty()
        val start = minOf(selectionStart, selectionEnd).coerceAtLeast(0)
        val end = maxOf(selectionStart, selectionEnd).coerceIn(0, content.length)
        return if (start < end) content.substring(start, end) else content
    }

    internal fun copySelection(label: Int) {
        val clip = ClipData.newPlainText(context.getString(label), textForCopy())
        // Explicit copies can contain private filenames. Hide their preview on newer Android versions.
        clip.description.extras = PersistableBundle().apply { putBoolean("android.content.extra.IS_SENSITIVE", true) }
        context.getSystemService(ClipboardManager::class.java).setPrimaryClip(clip)
        Toast.makeText(context, R.string.logs_copied, Toast.LENGTH_SHORT).show()
    }
}

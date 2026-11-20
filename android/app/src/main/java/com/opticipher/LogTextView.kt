package com.opticipher

import android.content.Context
import android.graphics.Typeface
import android.util.AttributeSet
import android.view.Gravity
import android.view.MotionEvent
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
}

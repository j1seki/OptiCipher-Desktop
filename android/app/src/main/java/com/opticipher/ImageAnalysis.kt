package com.opticipher

import kotlin.math.abs
import kotlin.math.log2
import kotlin.math.sqrt
import kotlin.random.Random

internal data class ChannelMetrics(val histogram: IntArray, val entropy: Double, val correlation: DoubleArray)
internal data class ImageAnalysis(
    val channels: List<ChannelMetrics>,
    val npcr: Double? = null,
    val uaci: Double? = null,
)

internal fun analyzeImages(first: ImageData, second: ImageData? = null): ImageAnalysis {
    val histograms = Array(first.channels) { IntArray(256) }
    for (offset in first.pixels.indices step first.channels) {
        for (channel in histograms.indices) histograms[channel][first.pixels[offset + channel].toInt() and 255]++
    }
    val total = first.width.toDouble() * first.height
    val channels = histograms.mapIndexed { channel, counts ->
        val entropy = counts.sumOf { count ->
            if (count == 0) 0.0 else (count / total).let { probability -> -probability * log2(probability) }
        }
        val correlation = doubleArrayOf(
            adjacentCorrelation(first, channel, 1, 0),
            adjacentCorrelation(first, channel, 0, 1),
            adjacentCorrelation(first, channel, 1, 1),
        )
        ChannelMetrics(counts, entropy, correlation)
    }
    if (second == null) return ImageAnalysis(channels)
    val count = comparableBytes(first, second)
    var changed = 0
    var difference = 0L
    for (index in 0 until count) {
        val delta = abs((first.pixels[index].toInt() and 255) - (second.pixels[index].toInt() and 255))
        if (delta > 0) changed++
        difference += delta
    }
    return ImageAnalysis(channels, changed * 100.0 / count, difference * 100.0 / (count * 255.0))
}

private fun comparableBytes(a: ImageData, b: ImageData): Int {
    require(a.width == b.width && a.channels == b.channels) { "The two images need matching dimensions and channels." }
    if (a.height == b.height) return a.pixels.size
    val (smaller, larger) = if (a.height < b.height) a to b else b to a
    val header = inspectImage(larger)
    require(header?.width == smaller.width && header.height == smaller.height &&
        header.channels == smaller.channels && smaller.height + header.stripRows == larger.height) {
        "Choose matching images or an original and its OptiCipher ciphertext."
    }
    return smaller.pixels.size
}

private fun adjacentCorrelation(image: ImageData, channel: Int, dx: Int, dy: Int): Double {
    val width = image.width - dx
    val height = image.height - dy
    if (width <= 0 || height <= 0) return 0.0
    val maxPairs = 10_000
    val count = minOf(maxPairs, width * height)
    val random = Random(0)
    var sumA = 0.0
    var sumB = 0.0
    var squareA = 0.0
    var squareB = 0.0
    var product = 0.0
    repeat(count) { index ->
        val pair = if (count == width * height) index else random.nextInt(width * height)
        val offset = (pair / width * image.width + pair % width) * image.channels + channel
        val other = offset + (dy * image.width + dx) * image.channels
        val a = (image.pixels[offset].toInt() and 255).toDouble()
        val b = (image.pixels[other].toInt() and 255).toDouble()
        sumA += a
        sumB += b
        squareA += a * a
        squareB += b * b
        product += a * b
    }
    val denominator = sqrt((count * squareA - sumA * sumA) * (count * squareB - sumB * sumB))
    return if (denominator > 0) (count * product - sumA * sumB) / denominator else 0.0
}

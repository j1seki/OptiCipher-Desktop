package com.opticipher

import java.util.Locale

object ImageFormats {
    val googlePhotosExtensions = setOf(
        ".jpg", ".jpeg", ".heic", ".heif", ".png", ".webp", ".gif", ".avif",
        ".dng", ".cr2", ".cr3", ".crw", ".nef", ".nrw", ".arw", ".sr2", ".srf",
        ".raf", ".rw2", ".rwl", ".orf", ".ori", ".pef", ".srw", ".mrw", ".iiq",
        ".mos", ".3fr", ".fff", ".kdc", ".dcr", ".dcs", ".erf", ".mef", ".x3f",
        ".ari", ".gpr", ".k25", ".obm"
    )
    val rawExtensions = googlePhotosExtensions - setOf(
        ".jpg", ".jpeg", ".heic", ".heif", ".png", ".webp", ".gif", ".avif"
    )
    fun isSupported(name: String?): Boolean {
        val lower = name?.lowercase(Locale.ROOT) ?: return false
        return googlePhotosExtensions.any(lower::endsWith)
    }
    fun isRaw(name: String?): Boolean {
        val lower = name?.lowercase(Locale.ROOT) ?: return false
        return rawExtensions.any(lower::endsWith)
    }
}

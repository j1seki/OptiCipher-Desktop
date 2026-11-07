package com.opticipher

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class ImageFormatsTest {
    @Test fun acceptsGooglePhotosPhotoFormatsCaseInsensitively() {
        listOf("photo.jpg", "photo.HEIC", "photo.heif", "photo.png", "photo.webp",
            "photo.gif", "photo.avif", "photo.dng", "photo.CR3", "photo.NEF").forEach {
            assertTrue("expected $it to be accepted", ImageFormats.isSupported(it))
        }
    }

    @Test fun rejectsNonImageFiles() {
        listOf("notes.txt", "archive.zip", "video.mp4", "photo").forEach {
            assertFalse("expected $it to be rejected", ImageFormats.isSupported(it))
        }
    }
}

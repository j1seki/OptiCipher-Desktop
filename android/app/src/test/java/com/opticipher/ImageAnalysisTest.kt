package com.opticipher

import org.junit.Assert.*
import org.junit.Test

class ImageAnalysisTest {
    @Test fun measuresChannelHistogramEntropyAndDifference() {
        val source = ImageData(byteArrayOf(0, 0, 0, -1, 0, 0), 2, 1, 3)
        val same = analyzeImages(source, source)
        assertEquals(1.0, same.channels.first().entropy, 0.0001)
        assertEquals(1, same.channels.first().histogram[255])
        assertEquals(0.0, same.npcr!!, 0.0001)
        assertEquals(0.0, same.uaci!!, 0.0001)
    }

    @Test fun comparesAnOriginalAgainstCiphertextWithoutHeaderRows() {
        val source = ImageData(ByteArray(32 * 4 * 3) { it.toByte() }, 32, 4, 3)
        val encrypted = encryptImage(source, "sample", 1_000)
        val forward = analyzeImages(source, encrypted)
        val reverse = analyzeImages(encrypted, source)
        assertEquals(forward.npcr, reverse.npcr)
        assertEquals(forward.uaci, reverse.uaci)
        assertTrue(forward.npcr!! > 0)
        assertThrows(IllegalArgumentException::class.java) {
            analyzeImages(source, source.copy(width = 2))
        }
    }

    @Test fun parsesSftpDestinationWithoutCredentialsInAddress() {
        val target = SftpTarget.parse("sftp://alice@host.local:2222/backups/")
        assertEquals("host.local", target.host)
        assertEquals(2222, target.port)
        assertEquals("/backups/photo.png", target.remote("photo.png"))
        assertThrows(IllegalArgumentException::class.java) { SftpTarget.parse("sftp://alice:secret@host.local") }
        assertThrows(IllegalArgumentException::class.java) { SftpProfile.parseHostKey("accept any key") }
    }
}

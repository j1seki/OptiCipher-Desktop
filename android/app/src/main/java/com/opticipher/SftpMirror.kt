package com.opticipher

import android.content.Context
import android.net.Uri
import com.jcraft.jsch.ChannelSftp
import com.jcraft.jsch.JSch
import com.jcraft.jsch.SftpException
import java.net.URI
import java.util.UUID

internal data class SftpTarget(val host: String, val user: String, val port: Int, val directory: String) {
    companion object {
        fun parse(text: String): SftpTarget {
            val url = URI(text.trim())
            require(url.scheme.equals("sftp", ignoreCase = true) && url.host != null) {
                "Use sftp://user@host/path."
            }
            val user = url.userInfo.orEmpty()
            require(user.isNotBlank() && ':' !in user && url.query == null && url.fragment == null) {
                "Use sftp://user@host/path. Enter the password separately."
            }
            val port = if (url.port == -1) 22 else url.port
            require(port in 1..65535) { "Invalid SSH port." }
            val directory = url.path.ifEmpty { "/" }.trimEnd('/').ifEmpty { "/" }
            require(!directory.any { it.isISOControl() }) { "Invalid remote folder." }
            return SftpTarget(url.host.removeSurrounding("[", "]"), user, port, directory)
        }
    }

    fun remote(name: String) = "${directory.trimEnd('/')}/$name"
}

internal class SftpProfile(
    val target: SftpTarget,
    val address: String,
    val hostKey: String,
    val password: String,
    val identity: Uri?,
) {
    companion object {
        private val hostKeyTypes = setOf(
            "ssh-ed25519", "ssh-rsa", "ecdsa-sha2-nistp256", "ecdsa-sha2-nistp384", "ecdsa-sha2-nistp521",
        )

        fun parseHostKey(text: String): String {
            val tokens = text.trim().split(Regex("\\s+"))
            require(tokens.size >= 2 && tokens[0] in hostKeyTypes && tokens[1].matches(Regex("[A-Za-z0-9+/]+={0,2}"))) {
                "Paste the trusted server public key as a key type followed by its Base64 data."
            }
            return "${tokens[0]} ${tokens[1]}"
        }
    }
}

internal object SftpMirror {
    fun upload(context: Context, profile: SftpProfile, name: String, png: ByteArray): String {
        val target = profile.target
        val ssh = JSch()
        val knownHost = if (target.port == 22) target.host else "[${target.host}]:${target.port}"
        ssh.setKnownHosts("$knownHost ${profile.hostKey}\n".byteInputStream())
        profile.identity?.let { uri ->
            val key = context.contentResolver.openInputStream(uri)?.use { stream ->
                val buffer = ByteArray(64 * 1024 + 1)
                var used = 0
                while (used < buffer.size) {
                    val count = stream.read(buffer, used, buffer.size - used)
                    if (count <= 0) break
                    used += count
                }
                require(used in 1 until buffer.size) { "Invalid SSH private key size." }
                buffer.copyOf(used).also { buffer.fill(0) }
            } ?: error("Cannot open the SSH private key.")
            val secret = profile.password.takeIf { it.isNotEmpty() }?.toByteArray()
            try {
                ssh.addIdentity("OptiCipher", key, null, secret)
            } finally {
                key.fill(0)
                secret?.fill(0)
            }
        }
        val session = ssh.getSession(target.user, target.host, target.port)
        session.setConfig("StrictHostKeyChecking", "yes")
        session.setConfig("PreferredAuthentications", if (profile.identity == null) "password" else "publickey")
        if (profile.identity == null) session.setPassword(profile.password)
        session.timeout = 30_000
        try {
            session.connect(15_000)
            val channel = session.openChannel("sftp") as ChannelSftp
            try {
                channel.connect(15_000)
                createRemoteDirectories(channel, target.directory)
                val output = target.remote(name)
                val staging = target.remote(".opticipher-${UUID.randomUUID()}.part")
                try {
                    png.inputStream().use { channel.put(it, staging) }
                    check(channel.stat(staging).size == png.size.toLong()) { "Remote copy size does not match." }
                    channel.rename(staging, output)
                } catch (error: Exception) {
                    runCatching { channel.rm(staging) }
                    throw error
                }
                return output
            } finally {
                channel.disconnect()
            }
        } finally {
            session.disconnect()
            ssh.removeAllIdentity()
        }
    }

    private fun createRemoteDirectories(channel: ChannelSftp, directory: String) {
        var path = ""
        for (part in directory.split('/').filter { it.isNotEmpty() }) {
            path += "/$part"
            try {
                check(channel.stat(path).isDir) { "$path is not a folder." }
            } catch (error: SftpException) {
                if (error.id != ChannelSftp.SSH_FX_NO_SUCH_FILE) throw error
                channel.mkdir(path)
            }
        }
    }
}

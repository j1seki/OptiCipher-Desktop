package com.opticipher

import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.provider.Settings
import androidx.core.content.FileProvider
import org.json.JSONObject
import java.io.File
import java.net.HttpURLConnection
import java.net.URL
import java.security.MessageDigest

/**
 * Checks the project's GitHub Releases for a newer Android APK, downloads it
 * and hands it to the system package installer. No data leaves the device
 * except the release-metadata request.
 */
object Updater {
    private const val REPO = "j1seki/OptiCipher-Desktop"
    private const val API_URL = "https://api.github.com/repos/$REPO/releases/latest"
    private const val ASSET_NAME = "OptiCipher-android.apk"
    private const val USER_AGENT = "OptiCipher-Android-Updater"

    data class Release(
        val version: String,
        val notes: String,
        val downloadUrl: String,
        val size: Long,
        val sha256: String?
    )

    data class CheckResult(
        val currentVersion: String,
        val release: Release?,
        val newer: Boolean
    )

    fun currentVersion(context: Context): String = try {
        context.packageManager.getPackageInfo(context.packageName, 0).versionName ?: "?"
    } catch (_: Exception) {
        "?"
    }

    fun check(context: Context): CheckResult {
        val current = currentVersion(context)
        val connection = (URL(API_URL).openConnection() as HttpURLConnection).apply {
            connectTimeout = 15_000
            readTimeout = 20_000
            setRequestProperty("Accept", "application/vnd.github+json")
            setRequestProperty("User-Agent", USER_AGENT)
        }
        return try {
            val code = connection.responseCode
            if (code != HttpURLConnection.HTTP_OK) error("GitHub returned HTTP $code")
            val json = JSONObject(connection.inputStream.bufferedReader().use { it.readText() })
            val tag = json.optString("tag_name").trim().removePrefix("v")
            val notes = json.optString("body", "")
            val assets = json.optJSONArray("assets")
            var release: Release? = null
            if (assets != null) {
                for (index in 0 until assets.length()) {
                    val asset = assets.getJSONObject(index)
                    if (asset.optString("name") == ASSET_NAME) {
                        val digest = asset.optString("digest")
                            .takeIf { it.startsWith("sha256:") }
                            ?.removePrefix("sha256:")
                        release = Release(
                            version = tag,
                            notes = notes,
                            downloadUrl = asset.optString("browser_download_url"),
                            size = asset.optLong("size"),
                            sha256 = digest
                        )
                        break
                    }
                }
            }
            CheckResult(current, release, release != null && isNewer(release.version, current))
        } finally {
            connection.disconnect()
        }
    }

    fun isNewer(latest: String, current: String): Boolean = compareVersions(latest, current) > 0

    private fun compareVersions(left: String, right: String): Int {
        val a = left.split('.', '-', '+').mapNotNull { it.toIntOrNull() }
        val b = right.split('.', '-', '+').mapNotNull { it.toIntOrNull() }
        for (index in 0 until maxOf(a.size, b.size)) {
            val x = a.getOrElse(index) { 0 }
            val y = b.getOrElse(index) { 0 }
            if (x != y) return x.compareTo(y)
        }
        return 0
    }

    fun cachedApk(context: Context): File = File(File(context.cacheDir, "updates"), ASSET_NAME)

    /** Reuses a verified download, e.g. after the user enables install permissions. */
    fun reusableApk(context: Context, release: Release): File? {
        val file = cachedApk(context)
        if (!file.exists()) return null
        return try {
            val version = validateApk(context, file)
            if (version.trim() == release.version.trim()) file else null
        } catch (_: Exception) {
            null
        }
    }

    fun download(context: Context, release: Release, onProgress: (Int) -> Unit): File {
        val directory = File(context.cacheDir, "updates").apply { mkdirs() }
        val target = File(directory, ASSET_NAME)
        if (target.exists()) target.delete()
        val connection = (URL(release.downloadUrl).openConnection() as HttpURLConnection).apply {
            instanceFollowRedirects = true
            connectTimeout = 15_000
            readTimeout = 30_000
            setRequestProperty("User-Agent", USER_AGENT)
        }
        try {
            val code = connection.responseCode
            if (code !in 200..299) error("Download failed: HTTP $code")
            val total = connection.contentLengthLong.takeIf { it > 0 } ?: release.size
            var read = 0L
            connection.inputStream.use { input ->
                target.outputStream().use { output ->
                    val buffer = ByteArray(64 * 1024)
                    while (true) {
                        val count = input.read(buffer)
                        if (count < 0) break
                        output.write(buffer, 0, count)
                        read += count
                        if (total > 0) onProgress(((read * 100) / total).toInt().coerceIn(0, 100))
                    }
                }
            }
            if (read <= 0L) error("Downloaded file is empty")
            if (release.size > 0L && read != release.size) error("Downloaded size does not match the release")
            if (release.sha256 != null && !sha256(target).equals(release.sha256, ignoreCase = true)) {
                target.delete()
                error("Downloaded file failed its checksum check")
            }
            return target
        } finally {
            connection.disconnect()
        }
    }

    /**
     * Verifies that [file] is an OptiCipher APK, is not older than the installed
     * build, and is signed with the same key. Returns its version name.
     */
    fun validateApk(context: Context, file: File): String {
        val manager = context.packageManager
        val archive = manager.getPackageArchiveInfo(file.absolutePath, 0)
            ?: error("Downloaded file is not a valid APK")
        if (archive.packageName != context.packageName) {
            error("Downloaded APK belongs to ${archive.packageName}, not ${context.packageName}")
        }
        val installed = manager.getPackageInfo(context.packageName, 0)
        val archiveCode = if (Build.VERSION.SDK_INT >= 28) archive.longVersionCode else @Suppress("DEPRECATION") archive.versionCode.toLong()
        val installedCode = if (Build.VERSION.SDK_INT >= 28) installed.longVersionCode else @Suppress("DEPRECATION") installed.versionCode.toLong()
        if (archiveCode < installedCode) error("Downloaded APK is older than the installed version")
        if (!sameSigner(context, file)) {
            error("Update is signed with a different key. Install the release build once before using in-app updates.")
        }
        return archive.versionName ?: "?"
    }

    private fun sameSigner(context: Context, file: File): Boolean {
        val manager = context.packageManager
        val archiveSignatures = signatures(manager, context.packageName, file)
        val installedSignatures = signatures(manager, context.packageName, null)
        if (archiveSignatures.isEmpty() || installedSignatures.isEmpty()) return false
        return archiveSignatures.any { candidate ->
            installedSignatures.any { installed -> candidate.contentEquals(installed) }
        }
    }

    private fun signatures(manager: PackageManager, packageName: String, file: File?): List<ByteArray> {
        return if (Build.VERSION.SDK_INT >= 28) {
            val flags = PackageManager.GET_SIGNING_CERTIFICATES
            val info = if (file == null) manager.getPackageInfo(packageName, flags)
            else manager.getPackageArchiveInfo(file.absolutePath, flags)
            info?.signingInfo?.apkContentsSigners?.map { it.toByteArray() } ?: emptyList()
        } else {
            @Suppress("DEPRECATION")
            val flags = PackageManager.GET_SIGNATURES
            @Suppress("DEPRECATION")
            val info = if (file == null) manager.getPackageInfo(packageName, flags)
            else manager.getPackageArchiveInfo(file.absolutePath, flags)
            @Suppress("DEPRECATION")
            info?.signatures?.map { it.toByteArray() } ?: emptyList()
        }
    }

    /** Returns false when the user still needs to allow installs from this app. */
    fun install(context: Context, file: File): Boolean {
        if (!context.packageManager.canRequestPackageInstalls()) {
            context.startActivity(
                Intent(Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES, Uri.parse("package:${context.packageName}"))
                    .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            )
            return false
        }
        val uri = FileProvider.getUriForFile(context, "${context.packageName}.provider", file)
        val intent = Intent(Intent.ACTION_VIEW).apply {
            setDataAndType(uri, "application/vnd.android.package-archive")
            addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_ACTIVITY_NEW_TASK)
        }
        // Avoid a chooser when another app (e.g. Termux) also handles APKs.
        listOf("com.google.android.packageinstaller", "com.android.packageinstaller").firstOrNull { pkg ->
            try { context.packageManager.getPackageInfo(pkg, 0); true } catch (_: Exception) { false }
        }?.let { intent.setPackage(it) }
        context.startActivity(intent)
        return true
    }

    private fun sha256(file: File): String {
        val digest = MessageDigest.getInstance("SHA-256")
        file.inputStream().use { input ->
            val buffer = ByteArray(64 * 1024)
            while (true) {
                val count = input.read(buffer)
                if (count < 0) break
                digest.update(buffer, 0, count)
            }
        }
        return digest.digest().joinToString("") { "%02x".format(it.toInt() and 0xFF) }
    }
}

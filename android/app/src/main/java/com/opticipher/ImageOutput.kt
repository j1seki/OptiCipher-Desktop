package com.opticipher

import android.content.Context
import android.net.Uri
import android.provider.DocumentsContract
import androidx.core.content.FileProvider
import androidx.documentfile.provider.DocumentFile
import java.io.File
import java.nio.file.Files
import java.nio.file.StandardCopyOption
import java.util.UUID

internal enum class OutputConflict { KEEP_BOTH, SKIP, OVERWRITE }
internal data class SavedImage(val name: String, val uri: Uri)

internal object ImageOutput {
    @Synchronized
    fun write(
        context: Context,
        treeUri: Uri?,
        name: String,
        png: ByteArray,
        conflict: OutputConflict,
        privateOutput: Boolean = false,
        source: Uri? = null,
    ): SavedImage? {
        require(name == File(name).name && name != "." && name != "..") { "Invalid output filename" }
        if (treeUri != null && !privateOutput) {
            val tree = DocumentFile.fromTreeUri(context, treeUri) ?: error("Output folder unavailable")
            check(tree.isDirectory && tree.canWrite()) { "Output folder unavailable. Choose it again to restore access." }
            val existing = tree.findFile(name)
            if (existing != null && conflict == OutputConflict.SKIP) return null
            if (existing != null && conflict == OutputConflict.OVERWRITE) {
                check(existing.isFile && !sameDocument(source, existing.uri)) { "Output would replace an input or folder" }
                return replaceDocument(context, tree, existing, name, png)
            }
            val finalName = if (existing == null) name else uniqueName(name) { tree.findFile(it) != null }
            val target = tree.createFile("image/png", finalName) ?: error("Cannot create $finalName")
            try {
                writeDocument(context, target, png)
            } catch (error: Exception) {
                runCatching { target.delete() }
                throw error
            }
            return SavedImage(target.name ?: finalName, target.uri)
        }

        val directory = if (privateOutput) File(context.filesDir, "private_outputs") else {
            File(checkNotNull(context.getExternalFilesDir(null)) { "App storage unavailable" }, "OptiCipher")
        }
        check(directory.isDirectory || directory.mkdirs()) { "Cannot create output folder" }
        val target = File(directory, if (conflict == OutputConflict.KEEP_BOTH) {
            uniqueName(name) { File(directory, it).exists() }
        } else name)
        if (target.exists() && conflict == OutputConflict.SKIP) return null
        if (source?.scheme == "file") {
            check(source.path?.let { File(it).canonicalFile } != target.canonicalFile) { "Output would replace the input" }
        }
        val staging = File.createTempFile(".opticipher-", ".part", directory)
        try {
            staging.outputStream().use { stream ->
                stream.write(png)
                stream.fd.sync()
            }
            if (conflict == OutputConflict.OVERWRITE) {
                Files.move(staging.toPath(), target.toPath(), StandardCopyOption.ATOMIC_MOVE, StandardCopyOption.REPLACE_EXISTING)
            } else {
                Files.move(staging.toPath(), target.toPath())
            }
        } finally {
            staging.delete()
        }
        val uri = FileProvider.getUriForFile(context, "${context.packageName}.provider", target)
        return SavedImage(target.name, uri)
    }

    private fun uniqueName(name: String, exists: (String) -> Boolean): String {
        var candidate = name
        var index = 2
        while (exists(candidate)) candidate = "${name.removeSuffix(".png")}_${index++}.png"
        return candidate
    }

    private fun sameDocument(source: Uri?, target: Uri): Boolean =
        source != null && (source == target || (source.authority == target.authority && runCatching {
            DocumentsContract.getDocumentId(source) == DocumentsContract.getDocumentId(target)
        }.getOrDefault(false)))

    private fun writeDocument(context: Context, target: DocumentFile, png: ByteArray) {
        val stream = context.contentResolver.openOutputStream(target.uri, "wt") ?: error("Cannot write ${target.name}")
        stream.use { it.write(png) }
    }

    private fun replaceDocument(context: Context, tree: DocumentFile, original: DocumentFile, name: String, png: ByteArray): SavedImage {
        val id = UUID.randomUUID()
        val staged = tree.createFile("image/png", ".opticipher-$id.png") ?: error("Cannot stage $name")
        val backup = ".opticipher-original-$id.png"
        var movedOriginal = false
        var published = false
        try {
            writeDocument(context, staged, png)
            check(original.renameTo(backup)) { "This folder provider cannot safely replace $name" }
            movedOriginal = true
            check(staged.renameTo(name) && staged.name == name) { "Cannot publish $name" }
            published = true
            if (!original.delete()) FolderWatcher.log(context, "Previous output kept as ${original.name}")
            return SavedImage(name, staged.uri)
        } finally {
            if (!published) {
                runCatching { staged.delete() }
                if (movedOriginal && !original.renameTo(name)) {
                    FolderWatcher.log(context, "Previous output kept as ${original.name ?: backup}")
                }
            }
        }
    }
}

package com.opticipher

import android.database.Cursor
import android.database.MatrixCursor
import android.os.CancellationSignal
import android.os.ParcelFileDescriptor
import android.provider.DocumentsContract.Document
import android.provider.DocumentsContract.Root
import android.provider.DocumentsProvider
import android.webkit.MimeTypeMap
import java.io.File
import java.io.FileNotFoundException

/** App-private files exposed only through Android's user-granted document picker. */
class PrivateDocumentsProvider : DocumentsProvider() {
    private val root: File get() = File(context!!.filesDir, "private_outputs").apply { mkdirs() }.canonicalFile
    override fun onCreate() = true
    private fun file(id: String): File {
        val base = root
        val target = if (id == "root") base else File(base, id.removePrefix("root/")).canonicalFile
        if (id != "root" && (!id.startsWith("root/") || !target.path.startsWith(base.path + File.separator))) throw FileNotFoundException()
        return target
    }
    private fun id(file: File) = if (file == root) "root" else "root/" + file.relativeTo(root).path
    private fun type(f: File): String = if (f.isDirectory) Document.MIME_TYPE_DIR else MimeTypeMap.getSingleton().getMimeTypeFromExtension(f.extension.lowercase()) ?: "application/octet-stream"
    private val docColumns = arrayOf(Document.COLUMN_DOCUMENT_ID, Document.COLUMN_DISPLAY_NAME, Document.COLUMN_MIME_TYPE, Document.COLUMN_FLAGS, Document.COLUMN_SIZE, Document.COLUMN_LAST_MODIFIED)
    private fun add(cursor: MatrixCursor, f: File) {
        val flags = if (f.isDirectory) Document.FLAG_DIR_SUPPORTS_CREATE or Document.FLAG_SUPPORTS_DELETE else Document.FLAG_SUPPORTS_WRITE or Document.FLAG_SUPPORTS_DELETE
        cursor.addRow(arrayOf(id(f), if (f == root) "OptiCipher private" else f.name, type(f), flags, f.length(), f.lastModified()))
    }
    override fun queryRoots(projection: Array<out String>?): Cursor {
        val c = MatrixCursor(projection ?: arrayOf(Root.COLUMN_ROOT_ID, Root.COLUMN_DOCUMENT_ID, Root.COLUMN_TITLE, Root.COLUMN_FLAGS, Root.COLUMN_ICON))
        val row = c.newRow()
        for (column in c.columnNames) row.add(when (column) {
            Root.COLUMN_ROOT_ID, Root.COLUMN_DOCUMENT_ID -> "root"
            Root.COLUMN_TITLE -> "OptiCipher private"
            Root.COLUMN_FLAGS -> Root.FLAG_SUPPORTS_CREATE or Root.FLAG_LOCAL_ONLY
            Root.COLUMN_ICON -> R.drawable.ic_lock
            else -> null
        })
        return c
    }
    override fun queryDocument(documentId: String, projection: Array<out String>?): Cursor {
        val f = file(documentId); if (!f.exists()) throw FileNotFoundException()
        val all = MatrixCursor(docColumns); add(all, f); return project(all, projection)
    }
    override fun queryChildDocuments(parentDocumentId: String, projection: Array<out String>?, sortOrder: String?): Cursor {
        val parent = file(parentDocumentId); if (!parent.isDirectory) throw FileNotFoundException()
        val all = MatrixCursor(docColumns); parent.listFiles()?.sortedBy { it.name.lowercase() }?.forEach { add(all, it) }
        return project(all, projection)
    }
    override fun getDocumentType(documentId: String): String = type(file(documentId))
    private fun project(source: MatrixCursor, columns: Array<out String>?): Cursor {
        if (columns == null) return source
        val result = MatrixCursor(columns)
        while (source.moveToNext()) {
            val row = result.newRow()
            columns.forEach { column ->
                val index = source.getColumnIndex(column)
                row.add(if (index < 0 || source.isNull(index)) null else when (source.getType(index)) {
                    Cursor.FIELD_TYPE_INTEGER -> source.getLong(index)
                    else -> source.getString(index)
                })
            }
        }
        source.close(); return result
    }
    override fun openDocument(documentId: String, mode: String, signal: CancellationSignal?): ParcelFileDescriptor =
        ParcelFileDescriptor.open(file(documentId), ParcelFileDescriptor.parseMode(mode))
    override fun createDocument(parentDocumentId: String, mimeType: String, displayName: String): String {
        require(displayName.isNotBlank() && displayName != "." && displayName != ".." && !displayName.contains('/') && !displayName.contains('\\'))
        val parent = file(parentDocumentId); if (!parent.isDirectory) throw FileNotFoundException()
        var target = File(parent, displayName); var n = 2
        while (target.exists()) target = File(parent, "$displayName (${n++})")
        val created = if (mimeType == Document.MIME_TYPE_DIR) target.mkdir() else target.createNewFile()
        if (!created) throw FileNotFoundException("Cannot create document")
        return id(target)
    }
    override fun deleteDocument(documentId: String) {
        val target = file(documentId)
        if (target == root || !target.delete()) throw FileNotFoundException("Cannot delete document (folder must be empty)")
    }
    override fun isChildDocument(parentDocumentId: String, documentId: String): Boolean {
        val parent = file(parentDocumentId); val child = file(documentId)
        return child.path.startsWith(parent.path + File.separator)
    }
}

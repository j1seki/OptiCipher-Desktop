package com.opticipher

import android.Manifest
import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.provider.DocumentsContract
import android.view.View
import android.widget.*
import androidx.appcompat.app.AppCompatActivity
import androidx.core.app.ActivityCompat
import androidx.core.content.ContextCompat
import androidx.core.content.FileProvider
import androidx.documentfile.provider.DocumentFile
import java.io.File

class MainActivity : AppCompatActivity() {
    private lateinit var passInput: EditText
    private lateinit var iterSeek: SeekBar
    private lateinit var iterLabel: TextView
    private lateinit var results: LinearLayout
    private lateinit var preview: ImageView
    private lateinit var watchStatus: TextView
    private var mode = "encrypt" // or "decrypt" / "verify"
    private var outputTreeUri: Uri? = null
    private val pickFiles = registerForActivityResult(androidx.activity.result.contract.ActivityResultContracts.OpenMultipleDocuments()) { uris -> processUris(uris) }
    private val pickOutputTree = registerForActivityResult(androidx.activity.result.contract.ActivityResultContracts.OpenDocumentTree()) { uri ->
        if (uri != null) { outputTreeUri = uri; takePersistable(uri); FolderWatcher.setOutputTree(this, uri); toast("Output folder set") }
    }
    private val pickWatchInbox = registerForActivityResult(androidx.activity.result.contract.ActivityResultContracts.OpenDocumentTree()) { uri ->
        if (uri != null) { takePersistable(uri); FolderWatcher.setInbox(this, uri); FolderWatcher.startWatching(this); refreshWatchStatus() }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)
        passInput = findViewById(R.id.pass)
        iterSeek = findViewById(R.id.iter); iterLabel = findViewById(R.id.iterLabel)
        results = findViewById(R.id.results); preview = findViewById(R.id.preview)
        watchStatus = findViewById(R.id.watchStatus)
        iterSeek.progress = 200000
        updateIterLabel()
        iterSeek.setOnSeekBarChangeListener(object : SeekBar.OnSeekBarChangeListener {
            override fun onProgressChanged(s: SeekBar?, p: Int, b: Boolean) = updateIterLabel()
            override fun onStartTrackingTouch(s: SeekBar?) {}
            override fun onStopTrackingTouch(s: SeekBar?) {}
        })
        findViewById<RadioGroup>(R.id.modeGroup).setOnCheckedChangeListener { _, id ->
            mode = when (id) { R.id.modeDecrypt -> "decrypt"; R.id.modeVerify -> "verify"; else -> "encrypt" }
            if (mode != "verify") FolderWatcher.setMode(this, mode)
            refreshWatchStatus()
        }
        findViewById<Button>(R.id.pickBtn).setOnClickListener { pickFiles.launch(arrayOf("image/*")) }
        findViewById<Button>(R.id.outputBtn).setOnClickListener { pickOutputTree.launch(null) }
        findViewById<Button>(R.id.watchBtn).setOnClickListener { pickWatchInbox.launch(null) }
        findViewById<Button>(R.id.watchOffBtn).setOnClickListener { FolderWatcher.stopWatching(this); refreshWatchStatus() }
        findViewById<Button>(R.id.permBtn).setOnClickListener { requestPermissionsFlow() }
        findViewById<CheckBox>(R.id.rememberChk).setOnCheckedChangeListener { _, c -> FolderWatcher.setRememberPassphrase(this, c) }
        findViewById<CheckBox>(R.id.moveChk).setOnCheckedChangeListener { _, c -> FolderWatcher.setMoveOriginal(this, c) }
        FolderWatcher.restorePassphraseIfEnabled(this)?.let { passInput.setText(it) }
        refreshWatchStatus()
        requestPermissionsFlow(silent = true)
        handleShareIntent(intent)
    }

    override fun onNewIntent(intent: Intent) { super.onNewIntent(intent); handleShareIntent(intent) }
    private fun handleShareIntent(intent: Intent?) {
        val uris = mutableListOf<Uri>()
        if (intent?.action == Intent.ACTION_SEND) intent.getParcelableExtra<Uri>(Intent.EXTRA_STREAM)?.let { uris.add(it) }
        if (intent?.action == Intent.ACTION_VIEW && intent.data != null) uris.add(intent.data!!)
        if (uris.isNotEmpty()) processUris(uris)
    }

    private fun updateIterLabel() { iterLabel.text = "KDF cost: ${iterSeek.progress} iterations" }
    private fun takePersistable(uri: Uri) {
        try { contentResolver.takePersistableUriPermission(uri, Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_GRANT_WRITE_URI_PERMISSION) } catch (_: Exception) {}
    }
    private fun refreshWatchStatus() {
        val inbox = FolderWatcher.getInbox(this)
        watchStatus.text = if (FolderWatcher.isWatching(this) && inbox != null)
            "Watching: $inbox\nNew images in this folder are queued for ${FolderWatcher.getMode(this)} when the app runs (passphrase remembered = background processing)."
        else "Folder watch: off. Pick a watched folder to auto-encrypt/decrypt new files there."
    }
    private fun requestPermissionsFlow(silent: Boolean = false) {
        val perms = mutableListOf<String>()
        if (Build.VERSION.SDK_INT >= 33) {
            if (ContextCompat.checkSelfPermission(this, Manifest.permission.READ_MEDIA_IMAGES) != PackageManager.PERMISSION_GRANTED) perms.add(Manifest.permission.READ_MEDIA_IMAGES)
            if (ContextCompat.checkSelfPermission(this, Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) perms.add(Manifest.permission.POST_NOTIFICATIONS)
        } else if (Build.VERSION.SDK_INT <= 32) {
            if (ContextCompat.checkSelfPermission(this, Manifest.permission.READ_EXTERNAL_STORAGE) != PackageManager.PERMISSION_GRANTED) perms.add(Manifest.permission.READ_EXTERNAL_STORAGE)
        }
        if (perms.isNotEmpty() && !silent) ActivityCompat.requestPermissions(this, perms.toTypedArray(), 1)
        else if (perms.isNotEmpty()) ActivityCompat.requestPermissions(this, perms.toTypedArray(), 1)
        // Battery optimisation: ask once so WorkManager isn't throttled by OEMs.
        if (!silent) {
            try {
                val pm = getSystemService(android.os.PowerManager::class.java)
                if (pm != null && !pm.isIgnoringBatteryOptimizations(packageName))
                    startActivity(Intent(android.provider.Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS, Uri.parse("package:$packageName")))
            } catch (_: Exception) {}
        }
    }

    private fun processUris(uris: List<Uri>) {
        val pass = passInput.text.toString()
        if (mode != "verify" && pass.isEmpty()) { toast("Enter a passphrase first"); return }
        FolderWatcher.storePassphraseIfEnabled(this, pass)
        Thread {
            for (uri in uris) {
                try {
                    val img = loadImage(uri)
                    val result = when (mode) {
                        "encrypt" -> encryptImage(img, pass, iterSeek.progress)
                        "decrypt" -> decryptImage(img, pass)
                        else -> { showResult(uri.lastPathSegment ?: "file", verifyImage(img, pass.ifEmpty { null }).let { "[${it.status}] ${it.message}" }, null); continue }
                    }
                    val suffix = if (mode == "encrypt") "_encrypted" else "_decrypted"
                    val outFile = writeOutput(result, (uri.lastPathSegment ?: "image").substringBeforeLast('.') + suffix + ".png")
                    showBitmap(result)
                    showResult(uri.lastPathSegment ?: "file", "→ ${outFile.name}", outFile)
                } catch (e: Exception) {
                    showResult(uri.lastPathSegment ?: "file", "ERROR: ${e.message}", null)
                }
            }
        }.start()
    }

    private fun loadImage(uri: Uri): ImageData {
        val bytes = contentResolver.openInputStream(uri)?.use { it.readBytes() } ?: throw IllegalArgumentException("cannot read file")
        // Exact PNG path first (ciphertexts are PNG); BitmapFactory fallback for JPEG/WebP etc.
        if (bytes.size > 8 && bytes[0] == 137.toByte()) try { return decodePNG(bytes) } catch (_: Exception) {}
        val bmp = BitmapFactory.decodeByteArray(bytes, 0, bytes.size) ?: throw IllegalArgumentException("unsupported image format")
        val w = bmp.width; val h = bmp.height
        val argb = IntArray(w * h); bmp.getPixels(argb, 0, w, 0, 0, w, h)
        var opaque = true; for (p in argb) if ((p ushr 24) != 0xff) { opaque = false; break }
        if (opaque) {
            val px = ByteArray(w * h * 3)
            for (i in argb.indices) { px[i * 3] = ((argb[i] ushr 16) and 0xff).toByte(); px[i * 3 + 1] = ((argb[i] ushr 8) and 0xff).toByte(); px[i * 3 + 2] = (argb[i] and 0xff).toByte() }
            return ImageData(px, w, h, 3)
        }
        val px = ByteArray(w * h * 4)
        for (i in argb.indices) { px[i * 4] = ((argb[i] ushr 16) and 0xff).toByte(); px[i * 4 + 1] = ((argb[i] ushr 8) and 0xff).toByte(); px[i * 4 + 2] = (argb[i] and 0xff).toByte(); px[i * 4 + 3] = ((argb[i] ushr 24) and 0xff).toByte() }
        // NOTE: Bitmap is premultiplied internally; semi-transparent RGBA is lossy here.
        return ImageData(px, w, h, 4)
    }

    private fun writeOutput(img: ImageData, name: String): File {
        val png = encodePNG(img.pixels, img.width, img.height, img.channels)
        if (outputTreeUri != null) {
            val tree = DocumentFile.fromTreeUri(this, outputTreeUri!!)!!
            var candidate = tree.createFile("image/png", name) ?: throw IllegalStateException("cannot create output file")
            // Never overwrite: DocumentFile.createFile may reuse; check existence first.
            var finalName = name; var n = 2
            while (tree.findFile(finalName) != null) { finalName = name.substringBeforeLast('.') + "_${n++}.png"; candidate = tree.createFile("image/png", finalName)!! }
            contentResolver.openOutputStream(candidate.uri)?.use { it.write(png) }
            // Return a shareable temp copy for the share sheet.
            val tmp = File(cacheDir, finalName); tmp.writeBytes(png); return tmp
        }
        val dir = File(getExternalFilesDir(null), "OptiCipher"); dir.mkdirs()
        var f = File(dir, name); var n = 2
        while (f.exists()) f = File(dir, name.substringBeforeLast('.') + "_${n++}.png")
        f.writeBytes(png); return f
    }

    private fun showBitmap(img: ImageData) {
        runOnUiThread {
            val bmp = Bitmap.createBitmap(img.width, img.height, Bitmap.Config.ARGB_8888)
            val argb = IntArray(img.width * img.height)
            for (i in argb.indices) {
                val r = img.pixels[i * img.channels].toInt() and 0xff
                val g = img.pixels[i * img.channels + 1].toInt() and 0xff
                val b = img.pixels[i * img.channels + 2].toInt() and 0xff
                val a = if (img.channels == 4) img.pixels[i * img.channels + 3].toInt() and 0xff else 0xff
                argb[i] = (a shl 24) or (r shl 16) or (g shl 8) or b
            }
            bmp.setPixels(argb, 0, img.width, 0, 0, img.width, img.height)
            preview.setImageBitmap(bmp); preview.visibility = View.VISIBLE
        }
    }
    private fun showResult(name: String, msg: String, file: File?) {
        runOnUiThread {
            val tv = TextView(this); tv.text = "$name: $msg"; tv.setPadding(0, 8, 0, 8)
            if (file != null) {
                tv.setOnClickListener {
                    val uri = FileProvider.getUriForFile(this, "$packageName.provider", file)
                    val share = Intent(Intent.ACTION_SEND).apply { type = "image/png"; putExtra(Intent.EXTRA_STREAM, uri); addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION) }
                    startActivity(Intent.createChooser(share, "Share $msg"))
                }
                tv.text = "$name: $msg  (tap to share)"
            }
            results.addView(tv)
        }
    }
    private fun toast(msg: String) = Toast.makeText(this, msg, Toast.LENGTH_LONG).show()
}

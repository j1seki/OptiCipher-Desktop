package com.opticipher

import android.Manifest
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.provider.Settings
import android.view.View
import android.widget.ImageView
import android.widget.LinearLayout
import android.widget.TextView
import android.widget.Toast
import androidx.activity.enableEdgeToEdge
import androidx.appcompat.app.AlertDialog
import androidx.appcompat.app.AppCompatActivity
import androidx.core.app.ActivityCompat
import androidx.core.content.ContextCompat
import androidx.core.content.FileProvider
import androidx.core.view.ViewCompat
import androidx.core.view.WindowInsetsCompat
import androidx.documentfile.provider.DocumentFile
import com.google.android.material.button.MaterialButton
import com.google.android.material.chip.ChipGroup
import com.google.android.material.slider.Slider
import com.google.android.material.textfield.TextInputEditText
import java.io.File

class MainActivity : AppCompatActivity() {
    // ---- Manual batch job state (queue first, process only on Start) ----
    private val queue = mutableListOf<Uri>()
    private var manualOutputUri: Uri? = null

    private lateinit var passInput: TextInputEditText
    private lateinit var iterSlider: Slider
    private lateinit var iterLabel: TextView
    private lateinit var queueView: TextView
    private lateinit var startBtn: MaterialButton
    private lateinit var results: LinearLayout
    private lateinit var preview: ImageView
    private lateinit var manualOutView: TextView

    // ---- Folder watch state (independent passphrase / output / interval) ----
    private lateinit var watchPassInput: TextInputEditText
    private lateinit var watchStatus: TextView
    private lateinit var watchOutView: TextView
    private var mode = "encrypt"

    private val pickFiles = registerForActivityResult(androidx.activity.result.contract.ActivityResultContracts.OpenMultipleDocuments()) { uris ->
        if (uris.isEmpty()) toast("No images picked") else { queue.addAll(uris); refreshQueue() }
    }
    private val pickFolder = registerForActivityResult(androidx.activity.result.contract.ActivityResultContracts.OpenDocumentTree()) { uri ->
        if (uri == null) { toast("No folder picked"); return@registerForActivityResult }
        takePersistable(uri)
        val tree = DocumentFile.fromTreeUri(this, uri)
        val images = tree?.listFiles()?.filter { it.isFile && isImageName(it.name) } ?: emptyList()
        if (images.isEmpty()) toast("No image files in that folder (top level)")
        else { queue.addAll(images.map { it.uri }); refreshQueue(); toast("Added ${images.size} image(s) from folder") }
    }
    private val pickManualOutput = registerForActivityResult(androidx.activity.result.contract.ActivityResultContracts.OpenDocumentTree()) { uri ->
        if (uri != null) {
            manualOutputUri = uri; takePersistable(uri)
            getSharedPreferences("manual", Context.MODE_PRIVATE).edit().putString("output_uri", uri.toString()).apply()
            refreshOutputs(); toast("Batch output folder set")
        }
    }
    private val pickWatchOutput = registerForActivityResult(androidx.activity.result.contract.ActivityResultContracts.OpenDocumentTree()) { uri ->
        if (uri != null) { takePersistable(uri); FolderWatcher.setOutputTree(this, uri); refreshOutputs(); toast("Watch output folder set") }
    }
    private val pickWatchInbox = registerForActivityResult(androidx.activity.result.contract.ActivityResultContracts.OpenDocumentTree()) { uri ->
        if (uri != null) {
            takePersistable(uri)
            FolderWatcher.setInbox(this, uri)
            saveWatchSettings()
            FolderWatcher.startWatching(this)
            refreshWatchStatus()
            toast("Watching folder set — new images will be queued")
        } else toast("No folder picked")
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        setContentView(R.layout.activity_main)
        val root = findViewById<View>(R.id.root)
        ViewCompat.setOnApplyWindowInsetsListener(root) { v, insets ->
            val sys = insets.getInsets(WindowInsetsCompat.Type.systemBars())
            v.setPadding(0, sys.top, 0, sys.bottom)
            insets
        }
        passInput = findViewById(R.id.pass)
        iterSlider = findViewById(R.id.iter); iterLabel = findViewById(R.id.iterLabel)
        queueView = findViewById(R.id.queueView); startBtn = findViewById(R.id.startBtn)
        results = findViewById(R.id.results); preview = findViewById(R.id.preview)
        manualOutView = findViewById(R.id.manualOutView)
        watchPassInput = findViewById(R.id.watchPass)
        watchStatus = findViewById(R.id.watchStatus); watchOutView = findViewById(R.id.watchOutView)

        manualOutputUri = getSharedPreferences("manual", Context.MODE_PRIVATE).getString("output_uri", null)?.let { Uri.parse(it) }

        iterSlider.value = 200000f
        updateIterLabel()
        iterSlider.addOnChangeListener { _, v, _ -> iterSlider.value = v; updateIterLabel() }

        // ---- Manual job wiring ----
        val chipGroup = findViewById<ChipGroup>(R.id.modeGroup)
        chipGroup.setOnCheckedStateChangeListener { _, checkedIds ->
            mode = when (checkedIds.firstOrNull()) {
                R.id.modeDecrypt -> "decrypt"; R.id.modeVerify -> "verify"; else -> "encrypt"
            }
        }
        findViewById<MaterialButton>(R.id.pickBtn).setOnClickListener { pickFiles.launch(arrayOf("image/*")) }
        findViewById<MaterialButton>(R.id.pickFolderBtn).setOnClickListener { pickFolder.launch(null) }
        findViewById<MaterialButton>(R.id.clearQueueBtn).setOnClickListener { queue.clear(); refreshQueue() }
        findViewById<MaterialButton>(R.id.outputBtn).setOnClickListener { pickManualOutput.launch(null) }
        startBtn.setOnClickListener { startBatch() }

        // ---- Folder watch wiring (own passphrase / output / interval / mode) ----
        val watchModeGroup = findViewById<ChipGroup>(R.id.watchModeGroup)
        watchModeGroup.setOnCheckedStateChangeListener { _, checkedIds ->
            FolderWatcher.setMode(this, if (checkedIds.firstOrNull() == R.id.watchModeDecrypt) "decrypt" else "encrypt")
            refreshWatchStatus()
        }
        val intervalGroup = findViewById<ChipGroup>(R.id.intervalGroup)
        intervalGroup.setOnCheckedStateChangeListener { _, checkedIds ->
            val minutes = when (checkedIds.firstOrNull()) {
                R.id.intervalImmediate -> 0; R.id.interval60 -> 60; R.id.interval360 -> 360; else -> 15
            }
            FolderWatcher.setIntervalMinutes(this, minutes)
            if (FolderWatcher.isWatching(this)) FolderWatcher.startWatching(this) // reschedule with new interval
            toast("Watch interval: ${intervalLabel(minutes)}")
        }
        findViewById<MaterialButton>(R.id.watchOutBtn).setOnClickListener { pickWatchOutput.launch(null) }
        findViewById<MaterialButton>(R.id.watchBtn).setOnClickListener { pickWatchInbox.launch(null) }
        findViewById<MaterialButton>(R.id.watchStartBtn).setOnClickListener {
            if (FolderWatcher.getInbox(this) == null) { toast("Pick a watched folder first"); pickWatchInbox.launch(null) }
            else { saveWatchSettings(); FolderWatcher.startWatching(this); refreshWatchStatus(); toast("Folder watching started") }
        }
        findViewById<MaterialButton>(R.id.watchOffBtn).setOnClickListener {
            saveWatchSettings(); FolderWatcher.stopWatching(this); refreshWatchStatus(); toast("Folder watching stopped")
        }
        findViewById<com.google.android.material.checkbox.MaterialCheckBox>(R.id.watchRememberChk)
            .setOnCheckedChangeListener { _, c ->
                FolderWatcher.setRememberPassphrase(this, c)
                if (c) FolderWatcher.storePassphraseIfEnabled(this, watchPassInput.text.toString())
                toast(if (c) "Watch passphrase will be remembered (encrypted)" else "Watch passphrase will not be stored")
            }
        findViewById<com.google.android.material.checkbox.MaterialCheckBox>(R.id.moveChk)
            .setOnCheckedChangeListener { _, c -> FolderWatcher.setMoveOriginal(this, c) }
        findViewById<MaterialButton>(R.id.permBtn).setOnClickListener { showPermissionsDialog() }

        // Restore watch settings into the UI
        watchPassInput.setText(FolderWatcher.restorePassphraseIfEnabled(this) ?: "")
        findViewById<com.google.android.material.checkbox.MaterialCheckBox>(R.id.watchRememberChk).isChecked = FolderWatcher.isRemembering(this)
        findViewById<com.google.android.material.checkbox.MaterialCheckBox>(R.id.moveChk).isChecked = FolderWatcher.isMoveOriginal(this)
        val watchMode = FolderWatcher.getMode(this)
        watchModeGroup.check(if (watchMode == "decrypt") R.id.watchModeDecrypt else R.id.watchModeEncrypt)
        val interval = FolderWatcher.getIntervalMinutes(this)
        intervalGroup.check(when (interval) { 0 -> R.id.intervalImmediate; 60 -> R.id.interval60; 360 -> R.id.interval360; else -> R.id.interval15 })

        refreshQueue(); refreshOutputs(); refreshWatchStatus()
        handleShareIntent(intent)
    }

    override fun onNewIntent(intent: Intent) { super.onNewIntent(intent); handleShareIntent(intent) }
    private fun handleShareIntent(intent: Intent?) {
        val uris = mutableListOf<Uri>()
        if (intent?.action == Intent.ACTION_SEND) intent.getParcelableExtra<Uri>(Intent.EXTRA_STREAM)?.let { uris.add(it) }
        if (intent?.action == Intent.ACTION_VIEW && intent.data != null) uris.add(intent.data!!)
        if (uris.isNotEmpty()) { queue.addAll(uris); refreshQueue(); toast("Added ${uris.size} shared image(s) to the queue — press Start") }
    }

    private fun intervalLabel(minutes: Int) = when (minutes) { 0 -> "immediately (observer only)"; 60 -> "every hour"; 360 -> "every 6 hours"; else -> "every 15 minutes" }
    private fun isImageName(name: String?) = name?.lowercase()?.endsWith(".png") == true || name?.lowercase()?.endsWith(".jpg") == true ||
        name?.lowercase()?.endsWith(".jpeg") == true || name?.lowercase()?.endsWith(".webp") == true || name?.lowercase()?.endsWith(".bmp") == true

    private fun updateIterLabel() { iterLabel.text = "KDF cost: ${iterSlider.value.toInt()} iterations" }
    private fun takePersistable(uri: Uri) {
        try { contentResolver.takePersistableUriPermission(uri, Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_GRANT_WRITE_URI_PERMISSION) } catch (_: Exception) {}
    }
    private fun refreshQueue() {
        queueView.text = if (queue.isEmpty()) "Queue is empty. Pick images or a folder to add them."
        else "Queue (${queue.size}):\n" + queue.take(8).joinToString("\n") { "• ${it.lastPathSegment}" } + if (queue.size > 8) "\n• …and ${queue.size - 8} more" else ""
        startBtn.isEnabled = queue.isNotEmpty()
    }
    private fun refreshOutputs() {
        manualOutView.text = "Batch output: ${manualOutputUri ?: "app storage (OptiCipher folder)"}"
        watchOutView.text = "Watch output: ${FolderWatcher.getOutputTree(this) ?: "app storage (OptiCipher folder)"}"
    }
    private fun refreshWatchStatus() {
        val inbox = FolderWatcher.getInbox(this)
        val interval = FolderWatcher.getIntervalMinutes(this)
        watchStatus.text = if (FolderWatcher.isWatching(this) && inbox != null)
            "● Watching: $inbox\nMode: ${FolderWatcher.getMode(this)}, checking ${intervalLabel(interval)}.\nOutput: ${FolderWatcher.getOutputTree(this) ?: "app storage"}"
        else "○ Folder watch: off.${if (inbox != null) " Last folder: $inbox — tap Start to resume." else " Pick a watched folder to begin."}"
    }
    private fun saveWatchSettings() {
        // Persist the watch passphrase only if its own remember toggle is on.
        if (FolderWatcher.isRemembering(this)) FolderWatcher.storePassphraseIfEnabled(this, watchPassInput.text.toString())
    }

    // --- Permissions & battery settings -----------------------------------
    private fun permStatus(name: String): String =
        if (ContextCompat.checkSelfPermission(this, name) == PackageManager.PERMISSION_GRANTED) "granted ✓" else "not granted ✗"

    private fun showPermissionsDialog() {
        val pm = getSystemService(android.os.PowerManager::class.java)
        val batteryOk = pm == null || pm.isIgnoringBatteryOptimizations(packageName)
        val lines = StringBuilder()
        if (Build.VERSION.SDK_INT >= 33) {
            lines.append("• Photos (READ_MEDIA_IMAGES): ${permStatus(Manifest.permission.READ_MEDIA_IMAGES)}\n")
            lines.append("• Notifications: ${permStatus(Manifest.permission.POST_NOTIFICATIONS)}\n")
        } else {
            lines.append("• Storage: ${permStatus(Manifest.permission.READ_EXTERNAL_STORAGE)}\n")
        }
        lines.append("• Battery optimisation exemption: ${if (batteryOk) "granted ✓" else "not granted ✗"}\n")
        lines.append("\nFolder watching uses the system folder picker (no permission needed).")

        AlertDialog.Builder(this)
            .setTitle("Permissions & battery")
            .setMessage(lines.toString())
            .setPositiveButton("Request permissions") { _, _ ->
                val perms = mutableListOf<String>()
                if (Build.VERSION.SDK_INT >= 33) {
                    if (ContextCompat.checkSelfPermission(this, Manifest.permission.READ_MEDIA_IMAGES) != PackageManager.PERMISSION_GRANTED) perms.add(Manifest.permission.READ_MEDIA_IMAGES)
                    if (ContextCompat.checkSelfPermission(this, Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) perms.add(Manifest.permission.POST_NOTIFICATIONS)
                } else if (ContextCompat.checkSelfPermission(this, Manifest.permission.READ_EXTERNAL_STORAGE) != PackageManager.PERMISSION_GRANTED) {
                    perms.add(Manifest.permission.READ_EXTERNAL_STORAGE)
                }
                if (perms.isNotEmpty()) ActivityCompat.requestPermissions(this, perms.toTypedArray(), 1)
                else toast("All permissions already granted")
                if (!batteryOk) openBatterySettings()
            }
            .setNegativeButton("Battery settings") { _, _ -> openBatterySettings() }
            .setNeutralButton("App settings") { _, _ -> openAppSettings() }
            .setOnDismissListener { refreshWatchStatus() }
            .show()
    }

    private fun openAppSettings() {
        try { startActivity(Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS, Uri.parse("package:$packageName"))) }
        catch (e: Exception) { toast("Could not open settings: ${e.message}"); startActivity(Intent(Settings.ACTION_SETTINGS)) }
    }

    private fun openBatterySettings() {
        val intents = listOf(
            Intent(Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS, Uri.parse("package:$packageName")),
            Intent(Settings.ACTION_IGNORE_BATTERY_OPTIMIZATION_SETTINGS),
            Intent(Settings.ACTION_BATTERY_SAVER_SETTINGS),
        )
        for (intent in intents) { try { startActivity(intent); return } catch (_: Exception) {} }
        toast("Could not open battery settings — use App settings instead")
        openAppSettings()
    }

    // --- Batch execution (only on Start) ----------------------------------
    private fun startBatch() {
        if (queue.isEmpty()) { toast("Queue is empty — pick images or a folder first"); return }
        val pass = passInput.text.toString()
        if (mode != "verify" && pass.isEmpty()) { toast("Enter a passphrase first"); return }
        val batch = queue.toList()
        queue.clear(); refreshQueue()
        startBtn.isEnabled = false; startBtn.text = "Working…"
        Thread {
            for (uri in batch) {
                try {
                    val img = loadImage(uri)
                    val result = when (mode) {
                        "encrypt" -> encryptImage(img, pass, iterSlider.value.toInt())
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
            runOnUiThread { startBtn.text = "▶  Start"; startBtn.isEnabled = queue.isNotEmpty() }
        }.start()
    }

    private fun loadImage(uri: Uri): ImageData {
        val bytes = contentResolver.openInputStream(uri)?.use { it.readBytes() } ?: throw IllegalArgumentException("cannot read file")
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
        return ImageData(px, w, h, 4)
    }

    private fun writeOutput(img: ImageData, name: String): File {
        val png = encodePNG(img.pixels, img.width, img.height, img.channels)
        if (manualOutputUri != null) {
            val tree = DocumentFile.fromTreeUri(this, manualOutputUri!!)!!
            var candidate = tree.createFile("image/png", name) ?: throw IllegalStateException("cannot create output file")
            var finalName = name; var n = 2
            while (tree.findFile(finalName) != null) { finalName = name.substringBeforeLast('.') + "_${n++}.png"; candidate = tree.createFile("image/png", finalName)!! }
            contentResolver.openOutputStream(candidate.uri)?.use { it.write(png) }
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

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
import android.os.Environment
import android.provider.Settings
import android.view.View
import android.widget.ImageView
import android.widget.LinearLayout
import android.widget.TextView
import android.widget.Toast
import androidx.activity.enableEdgeToEdge
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AlertDialog
import androidx.appcompat.app.AppCompatActivity
import androidx.core.app.ActivityCompat
import androidx.core.content.ContextCompat
import androidx.core.content.FileProvider
import androidx.core.view.ViewCompat
import androidx.core.view.WindowInsetsCompat
import androidx.documentfile.provider.DocumentFile
import com.google.android.material.button.MaterialButton
import com.google.android.material.checkbox.MaterialCheckBox
import com.google.android.material.chip.ChipGroup
import com.google.android.material.slider.Slider
import com.google.android.material.tabs.TabLayout
import com.google.android.material.textfield.TextInputEditText
import java.io.File

class MainActivity : AppCompatActivity() {
    private val queue = mutableListOf<Uri>()
    private var manualOutputUri: Uri? = null
    private var mode = "encrypt"
    private var pendingFolderMode: String? = null
    private var pendingOutputMode: String? = null
    // First-run setup requests a scoped SAF folder grant. Android deliberately
    // does not provide a broad runtime "all folders" permission; the picker is
    // the operating system's folder-permission prompt.
    private var onboardingStep: OnboardingStep? = null
    private lateinit var passInput: TextInputEditText
    private lateinit var iterSlider: Slider
    private lateinit var iterLabel: TextView
    private lateinit var queueView: TextView
    private lateinit var startBtn: MaterialButton
    private lateinit var results: LinearLayout
    private lateinit var preview: ImageView
    private lateinit var manualOutView: TextView
    private lateinit var batchStatus: TextView
    private lateinit var batchDetail: TextView
    private lateinit var batchProgress: com.google.android.material.progressindicator.LinearProgressIndicator

    private val pickFiles = registerForActivityResult(ActivityResultContracts.OpenMultipleDocuments()) { uris ->
        if (uris.isEmpty()) toast("No images selected") else { queue.addAll(uris); refreshQueue() }
    }
    private val pickBatchFolder = registerForActivityResult(ActivityResultContracts.OpenDocumentTree()) { uri ->
        uri?.let { addFolderToQueue(it) } ?: toast("No folder selected")
    }
    private val pickBatchOutput = registerForActivityResult(ActivityResultContracts.OpenDocumentTree()) { uri ->
        if (uri != null) {
            takePersistable(uri); manualOutputUri = uri
            getSharedPreferences("manual", Context.MODE_PRIVATE).edit().putString("output_uri", uri.toString()).apply()
            refreshOutputs()
        }
    }
    private val pickWatchFolder = registerForActivityResult(ActivityResultContracts.OpenDocumentTree()) { uri ->
        val watchMode = pendingFolderMode ?: return@registerForActivityResult
        if (uri != null) {
            takePersistable(uri); FolderWatcher.setInbox(this, watchMode, uri)
            refreshWatch(watchMode); toast("Folder access granted for auto-$watchMode")
            if (onboardingStep == OnboardingStep.ENCRYPT_INPUT) {
                onboardingStep = OnboardingStep.ENCRYPT_OUTPUT
                pendingOutputMode = FolderWatcher.ENCRYPT
                toast("Choose where encrypted images should be saved")
                pickWatchOutput.launch(null)
            }
        }
        pendingFolderMode = null
    }
    private val pickWatchOutput = registerForActivityResult(ActivityResultContracts.OpenDocumentTree()) { uri ->
        val watchMode = pendingOutputMode ?: return@registerForActivityResult
        if (uri != null) {
            takePersistable(uri); FolderWatcher.setOutputTree(this, watchMode, uri)
            refreshWatch(watchMode); toast("Auto-$watchMode output folder chosen")
            if (onboardingStep == OnboardingStep.ENCRYPT_OUTPUT) completeFolderSetup()
        }
        pendingOutputMode = null
    }
    private val requestNotifications = registerForActivityResult(ActivityResultContracts.RequestPermission()) {
        requestImagePermissionOrStorageAccess()
    }
    private val requestImages = registerForActivityResult(ActivityResultContracts.RequestPermission()) {
        requestAllFilesAccessOrFolderSetup()
    }
    private val requestAllFilesAccess = registerForActivityResult(ActivityResultContracts.StartActivityForResult()) {
        beginFolderSetup()
    }

    private enum class OnboardingStep { ENCRYPT_INPUT, ENCRYPT_OUTPUT }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge(); setContentView(R.layout.activity_main)
        ViewCompat.setOnApplyWindowInsetsListener(findViewById(R.id.root)) { view, insets ->
            val bars = insets.getInsets(WindowInsetsCompat.Type.systemBars())
            view.setPadding(0, bars.top, 0, bars.bottom); insets
        }
        passInput = findViewById(R.id.pass); iterSlider = findViewById(R.id.iter); iterLabel = findViewById(R.id.iterLabel)
        queueView = findViewById(R.id.queueView); startBtn = findViewById(R.id.startBtn)
        results = findViewById(R.id.results); preview = findViewById(R.id.preview); manualOutView = findViewById(R.id.manualOutView)
        batchStatus = findViewById(R.id.batchStatus); batchDetail = findViewById(R.id.batchDetail); batchProgress = findViewById(R.id.batchProgress)
        manualOutputUri = getSharedPreferences("manual", Context.MODE_PRIVATE).getString("output_uri", null)?.let(Uri::parse)
        iterSlider.value = 200000f; updateIterLabel(); iterSlider.addOnChangeListener { _, _, _ -> updateIterLabel() }

        findViewById<ChipGroup>(R.id.modeGroup).setOnCheckedStateChangeListener { _, ids ->
            mode = when (ids.firstOrNull()) { R.id.modeDecrypt -> "decrypt"; R.id.modeVerify -> "verify"; else -> "encrypt" }; refreshQueue()
        }
        findViewById<MaterialButton>(R.id.pickBtn).setOnClickListener { pickFiles.launch(arrayOf("image/*", "application/octet-stream")) }
        findViewById<MaterialButton>(R.id.pickFolderBtn).setOnClickListener { pickBatchFolder.launch(null) }
        findViewById<MaterialButton>(R.id.outputBtn).setOnClickListener { pickBatchOutput.launch(null) }
        findViewById<MaterialButton>(R.id.clearQueueBtn).setOnClickListener { queue.clear(); refreshQueue() }
        startBtn.setOnClickListener { startBatch() }
        findViewById<MaterialButton>(R.id.batchCheckBtn).setOnClickListener { runBatchCheck() }
        setupWatch(FolderWatcher.ENCRYPT)
        setupWatch(FolderWatcher.DECRYPT)
        setupTabs()
        findViewById<MaterialButton>(R.id.permissionsBtn).setOnClickListener { showPermissionsDialog() }
        findViewById<MaterialButton>(R.id.refreshLogBtn).setOnClickListener { refreshActivity() }
        findViewById<MaterialButton>(R.id.clearLogBtn).setOnClickListener { FolderWatcher.clearActivityLog(this); refreshActivity() }
        refreshQueue(); refreshOutputs(); refreshWatch(FolderWatcher.ENCRYPT); refreshWatch(FolderWatcher.DECRYPT)
        refreshActivity()
        handleShareIntent(intent)
        showFirstRunSetupIfNeeded()
    }

    private fun setupTabs() {
        val pages = listOf(findViewById<View>(R.id.batchPage), findViewById(R.id.encryptPage), findViewById(R.id.decryptPage), findViewById(R.id.activityPage))
        findViewById<TabLayout>(R.id.mainTabs).addOnTabSelectedListener(object : TabLayout.OnTabSelectedListener {
            override fun onTabSelected(tab: TabLayout.Tab) { pages.forEachIndexed { index, page -> page.visibility = if (index == tab.position) View.VISIBLE else View.GONE }; if (tab.position == 3) refreshActivity() }
            override fun onTabUnselected(tab: TabLayout.Tab) = Unit
            override fun onTabReselected(tab: TabLayout.Tab) { if (tab.position == 3) refreshActivity() }
        })
    }

    private fun refreshActivity() {
        val encrypt = if (FolderWatcher.isWatching(this, FolderWatcher.ENCRYPT)) "● Auto-encrypt: ON" else "○ Auto-encrypt: OFF"
        val decrypt = if (FolderWatcher.isWatching(this, FolderWatcher.DECRYPT)) "● Auto-decrypt: ON" else "○ Auto-decrypt: OFF"
        findViewById<TextView>(R.id.backgroundStatus).text = "$encrypt\n$decrypt\n\nBackground scans run through Android WorkManager. Recent events:"
        val lines = FolderWatcher.activityLog(this)
        findViewById<TextView>(R.id.activityLog).text = if (lines.isEmpty()) "No activity recorded yet." else lines.joinToString("\n")
    }

    private data class WatchIds(val pass: Int, val remember: Int, val folderText: Int, val folderButton: Int, val outputButton: Int,
        val existing: Int, val conflict: Int, val skip: Int, val overwrite: Int, val interval: Int, val immediate: Int, val fifteen: Int,
        val hour: Int, val status: Int, val start: Int, val stop: Int, val check: Int, val checkStatus: Int)
    private fun ids(watchMode: String) = if (watchMode == FolderWatcher.ENCRYPT) WatchIds(
        R.id.encryptWatchPass, R.id.encryptWatchRemember, R.id.encryptWatchFolders, R.id.encryptWatchFolderBtn, R.id.encryptWatchOutputBtn,
        R.id.encryptExisting, R.id.encryptConflictGroup, R.id.encryptSkip, R.id.encryptOverwrite, R.id.encryptIntervalGroup, R.id.encryptImmediate,
        R.id.encrypt15, R.id.encrypt60, R.id.encryptWatchStatus, R.id.encryptWatchStart, R.id.encryptWatchStop, R.id.encryptCheckBtn, R.id.encryptCheckStatus
    ) else WatchIds(
        R.id.decryptWatchPass, R.id.decryptWatchRemember, R.id.decryptWatchFolders, R.id.decryptWatchFolderBtn, R.id.decryptWatchOutputBtn,
        R.id.decryptExisting, R.id.decryptConflictGroup, R.id.decryptSkip, R.id.decryptOverwrite, R.id.decryptIntervalGroup, R.id.decryptImmediate,
        R.id.decrypt15, R.id.decrypt60, R.id.decryptWatchStatus, R.id.decryptWatchStart, R.id.decryptWatchStop, R.id.decryptCheckBtn, R.id.decryptCheckStatus
    )

    private fun setupWatch(watchMode: String) {
        val i = ids(watchMode)
        val pass = findViewById<TextInputEditText>(i.pass)
        val remember = findViewById<MaterialCheckBox>(i.remember)
        val existing = findViewById<MaterialCheckBox>(i.existing)
        pass.setText(FolderWatcher.restorePassphraseIfEnabled(this, watchMode) ?: "")
        remember.isChecked = FolderWatcher.isRemembering(this, watchMode)
        existing.isChecked = FolderWatcher.processExisting(this, watchMode)
        remember.setOnCheckedChangeListener { _, checked ->
            FolderWatcher.setRememberPassphrase(this, watchMode, checked)
            if (checked) FolderWatcher.storePassphraseIfEnabled(this, watchMode, pass.text.toString())
        }
        existing.setOnCheckedChangeListener { _, checked -> FolderWatcher.setProcessExisting(this, watchMode, checked) }
        findViewById<MaterialButton>(i.folderButton).setOnClickListener { pendingFolderMode = watchMode; pickWatchFolder.launch(null) }
        findViewById<MaterialButton>(i.outputButton).setOnClickListener { pendingOutputMode = watchMode; pickWatchOutput.launch(null) }
        val conflict = findViewById<ChipGroup>(i.conflict)
        conflict.check(if (FolderWatcher.getConflictPolicy(this, watchMode) == "overwrite") i.overwrite else i.skip)
        conflict.setOnCheckedStateChangeListener { _, chosen ->
            FolderWatcher.setConflictPolicy(this, watchMode, if (chosen.firstOrNull() == i.overwrite) "overwrite" else "skip")
        }
        val interval = findViewById<ChipGroup>(i.interval)
        interval.check(when (FolderWatcher.getIntervalMinutes(this, watchMode)) { 0 -> i.immediate; 60 -> i.hour; else -> i.fifteen })
        interval.setOnCheckedStateChangeListener { _, chosen ->
            val minutes = when (chosen.firstOrNull()) { i.immediate -> 0; i.hour -> 60; else -> 15 }
            FolderWatcher.setIntervalMinutes(this, watchMode, minutes)
            if (FolderWatcher.isWatching(this, watchMode)) FolderWatcher.startWatching(this, watchMode)
        }
        findViewById<MaterialButton>(i.start).setOnClickListener {
            if (FolderWatcher.getInbox(this, watchMode) == null) {
                toast("Grant access to a folder first"); pendingFolderMode = watchMode; pickWatchFolder.launch(null); return@setOnClickListener
            }
            if (pass.text.isNullOrEmpty()) { toast("Enter an auto-$watchMode passphrase first"); return@setOnClickListener }
            if (!remember.isChecked) { toast("Turn on ‘Remember passphrase’ for background auto-$watchMode"); return@setOnClickListener }
            FolderWatcher.storePassphraseIfEnabled(this, watchMode, pass.text.toString())
            if (!existing.isChecked) FolderWatcher.markExistingProcessed(this, watchMode)
            FolderWatcher.startWatching(this, watchMode); refreshWatch(watchMode)
            toast("Auto-$watchMode is on")
        }
        findViewById<MaterialButton>(i.stop).setOnClickListener { FolderWatcher.stopWatching(this, watchMode); refreshWatch(watchMode); toast("Auto-$watchMode is off") }
        findViewById<MaterialButton>(i.check).setOnClickListener { runWatchCheck(watchMode) }
    }

    /** First-launch flow: runtime media, special all-files and scoped folder grants. */
    private fun showFirstRunSetupIfNeeded() {
        val settings = getSharedPreferences("onboarding", Context.MODE_PRIVATE)
        if (settings.getBoolean("initial_folder_setup_done", false)) return
        AlertDialog.Builder(this)
            .setTitle("Set up OptiCipher folder access")
            .setMessage(
                "OptiCipher will request the permissions needed for local image and folder processing:\n\n" +
                    "• Photos and videos — lets you add images directly.\n" +
                    "• All files access — lets OptiCipher access device folders when you allow it in Android Settings.\n" +
                    "• Selected-folder access — Android will then ask you to choose the auto-encrypt input and output folders.\n" +
                    "• Notifications — lets folder-watch report results.\n\n" +
                    "Nothing is uploaded or sent from this device."
            )
            .setPositiveButton("Grant folder access") { _, _ ->
                if (Build.VERSION.SDK_INT >= 33 && ContextCompat.checkSelfPermission(this, Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) {
                    requestNotifications.launch(Manifest.permission.POST_NOTIFICATIONS)
                } else requestImagePermissionOrStorageAccess()
            }
            .setNegativeButton("Not now", null)
            .setCancelable(false)
            .show()
    }

    private fun requestImagePermissionOrStorageAccess() {
        when {
            Build.VERSION.SDK_INT >= 33 && ContextCompat.checkSelfPermission(this, Manifest.permission.READ_MEDIA_IMAGES) != PackageManager.PERMISSION_GRANTED ->
                requestImages.launch(Manifest.permission.READ_MEDIA_IMAGES)
            Build.VERSION.SDK_INT < 33 && ContextCompat.checkSelfPermission(this, Manifest.permission.READ_EXTERNAL_STORAGE) != PackageManager.PERMISSION_GRANTED ->
                requestImages.launch(Manifest.permission.READ_EXTERNAL_STORAGE)
            else -> requestAllFilesAccessOrFolderSetup()
        }
    }

    private fun requestAllFilesAccessOrFolderSetup() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R && !Environment.isExternalStorageManager()) {
            AlertDialog.Builder(this)
                .setTitle("Allow all files access")
                .setMessage("Android will open the OptiCipher storage-access setting. Turn on ‘Allow access to manage all files’, then return here. This complements the specific folder access you choose next.")
                .setPositiveButton("Open storage settings") { _, _ ->
                    try {
                        requestAllFilesAccess.launch(Intent(Settings.ACTION_MANAGE_APP_ALL_FILES_ACCESS_PERMISSION, Uri.parse("package:$packageName")))
                    } catch (_: Exception) { requestAllFilesAccess.launch(Intent(Settings.ACTION_MANAGE_ALL_FILES_ACCESS_PERMISSION)) }
                }
                .setNegativeButton("Use selected folders only") { _, _ -> beginFolderSetup() }
                .setCancelable(false)
                .show()
        } else beginFolderSetup()
    }

    private fun beginFolderSetup() {
        onboardingStep = OnboardingStep.ENCRYPT_INPUT
        pendingFolderMode = FolderWatcher.ENCRYPT
        toast("Choose the folder whose images you want to auto-encrypt")
        pickWatchFolder.launch(null)
    }

    private fun completeFolderSetup() {
        onboardingStep = null
        getSharedPreferences("onboarding", Context.MODE_PRIVATE).edit().putBoolean("initial_folder_setup_done", true).apply()
        AlertDialog.Builder(this)
            .setTitle("Folder access granted")
            .setMessage("OptiCipher can now access the two folders you selected. Enter a passphrase and tap ‘Turn on auto-encrypt’ when ready.\n\nTo use auto-decrypt, select its input and output folders in the Auto-decrypt section. You can change any folder later.")
            .setPositiveButton("Battery settings") { _, _ -> openBatterySettings() }
            .setNegativeButton("Done", null)
            .show()
    }

    private fun refreshWatch(watchMode: String) {
        val i = ids(watchMode); val inbox = FolderWatcher.getInbox(this, watchMode); val out = FolderWatcher.getOutputTree(this, watchMode)
        findViewById<TextView>(i.folderText).text = "Input: ${inbox ?: "not selected"}\nOutput: ${out ?: "app storage"}"
        val every = when (FolderWatcher.getIntervalMinutes(this, watchMode)) { 0 -> "immediately"; 60 -> "every hour"; else -> "every 15 minutes" }
        findViewById<TextView>(i.status).text = if (FolderWatcher.isWatching(this, watchMode)) "● Auto-$watchMode is on — checks $every" else "○ Auto-$watchMode is off"
    }

    private fun readyStatus(viewId: Int, passed: Boolean, details: String) {
        val status = findViewById<TextView>(viewId)
        status.text = if (passed) "🟢 READY — all tests passed\n$details" else "🔴 NOT READY — fix the items below\n$details"
        val heading = if (passed) "READY" else "NOT READY"
        FolderWatcher.log(this, "$heading: ${details.replace("\n", " · ")}")
    }

    /** Fast no-file test for the manual flow: crypto roundtrip plus output-folder access. */
    private fun runBatchCheck() {
        val status = findViewById<TextView>(R.id.batchCheckStatus); status.text = "Testing batch setup…"
        Thread {
            val findings = mutableListOf<String>()
            var ok = true
            try {
                val tiny = ImageData(byteArrayOf(10, 20, 30), 1, 1, 3)
                val roundtrip = decryptImage(encryptImage(tiny, "OptiCipher-self-test", 10_000), "OptiCipher-self-test")
                if (!roundtrip.pixels.contentEquals(tiny.pixels)) error("crypto round-trip did not match")
                findings += "✓ encryption test passed"
            } catch (e: Exception) { ok = false; findings += "✗ encryption test: ${e.message}" }
            if (manualOutputUri != null) {
                val tree = DocumentFile.fromTreeUri(this, manualOutputUri!!)
                if (tree?.canWrite() == true) findings += "✓ batch output folder writable" else { ok = false; findings += "✗ batch output folder is not writable" }
            } else findings += "✓ app storage output available"
            runOnUiThread { readyStatus(R.id.batchCheckStatus, ok, findings.joinToString("\n")) }
        }.start()
    }

    /** Verifies every prerequisite for background work without modifying user images. */
    private fun runWatchCheck(watchMode: String) {
        val i = ids(watchMode); findViewById<TextView>(i.checkStatus).text = "Testing auto-$watchMode setup…"
        Thread {
            val findings = mutableListOf<String>(); var ok = true
            fun requireCheck(condition: Boolean, pass: String, fail: String) { if (condition) findings += "✓ $pass" else { ok = false; findings += "✗ $fail" } }
            val imagesGranted = if (Build.VERSION.SDK_INT >= 33) ContextCompat.checkSelfPermission(this, Manifest.permission.READ_MEDIA_IMAGES) == PackageManager.PERMISSION_GRANTED else ContextCompat.checkSelfPermission(this, Manifest.permission.READ_EXTERNAL_STORAGE) == PackageManager.PERMISSION_GRANTED
            requireCheck(imagesGranted, "photo/media permission granted", "photo/media permission missing")
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) requireCheck(Environment.isExternalStorageManager(), "all-files access granted", "all-files access missing")
            val input = FolderWatcher.getInbox(this, watchMode)?.let { DocumentFile.fromTreeUri(this, it) }
            requireCheck(input != null && input.canRead(), "input folder readable", "select an accessible input folder")
            val output = FolderWatcher.getOutputTree(this, watchMode)?.let { DocumentFile.fromTreeUri(this, it) }
            requireCheck(output != null && output.canWrite(), "output folder writable", "select a writable output folder")
            requireCheck(FolderWatcher.restorePassphraseIfEnabled(this, watchMode)?.isNotEmpty() == true, "background passphrase stored securely", "enter passphrase and enable Remember")
            try {
                val tiny = ImageData(byteArrayOf(10, 20, 30), 1, 1, 3)
                val restored = decryptImage(encryptImage(tiny, "OptiCipher-self-test", 10_000), "OptiCipher-self-test")
                requireCheck(restored.pixels.contentEquals(tiny.pixels), "crypto round-trip passed", "crypto result mismatch")
            } catch (e: Exception) { ok = false; findings += "✗ crypto self-test: ${e.message}" }
            val heapMb = Runtime.getRuntime().maxMemory() / (1024 * 1024)
            findings += "✓ device processing heap: ${heapMb} MB"
            findings += "Large photos may exceed this device’s memory limit; the app will identify them in Activity."
            runOnUiThread { readyStatus(i.checkStatus, ok, findings.joinToString("\n")) }
        }.start()
    }

    override fun onNewIntent(intent: Intent) { super.onNewIntent(intent); handleShareIntent(intent) }
    @Suppress("DEPRECATION") private fun handleShareIntent(intent: Intent?) {
        val uris = mutableListOf<Uri>()
        if (intent?.action == Intent.ACTION_SEND) intent.getParcelableExtra<Uri>(Intent.EXTRA_STREAM)?.let(uris::add)
        if (intent?.action == Intent.ACTION_VIEW) intent.data?.let(uris::add)
        if (uris.isNotEmpty()) { queue.addAll(uris); refreshQueue(); toast("Added ${uris.size} shared item(s) to the queue") }
    }
    private fun addFolderToQueue(uri: Uri) {
        takePersistable(uri)
        val files = DocumentFile.fromTreeUri(this, uri)?.listFiles()?.filter { it.isFile && isImageName(it.name) } ?: emptyList()
        if (files.isEmpty()) toast("No supported images in the selected folder") else { queue.addAll(files.map { it.uri }); refreshQueue(); toast("Added ${files.size} images") }
    }
    private fun isImageName(name: String?) = ImageFormats.isSupported(name)
    private fun takePersistable(uri: Uri) { try { contentResolver.takePersistableUriPermission(uri, Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_GRANT_WRITE_URI_PERMISSION) } catch (_: Exception) { } }
    private fun updateIterLabel() { iterLabel.text = "KDF cost: ${iterSlider.value.toInt()} iterations" }
    private fun actionLabel() = when (mode) { "encrypt" -> "Encrypt queued files"; "decrypt" -> "Decrypt queued files"; else -> "Verify queued files" }
    private fun refreshQueue() {
        queueView.text = if (queue.isEmpty()) "Queue is empty. Add images or grant access to a batch folder." else "Queue (${queue.size}):\n" + queue.take(8).joinToString("\n") { "• ${it.lastPathSegment}" } + if (queue.size > 8) "\n• …and ${queue.size - 8} more" else ""
        startBtn.text = actionLabel(); startBtn.isEnabled = queue.isNotEmpty()
    }
    private fun refreshOutputs() { manualOutView.text = "Batch output: ${manualOutputUri ?: "app storage (OptiCipher folder)"}" }

    private fun showPermissionsDialog() {
        val batteryOk = getSystemService(android.os.PowerManager::class.java)?.isIgnoringBatteryOptimizations(packageName) != false
        val notification = if (Build.VERSION.SDK_INT >= 33) if (ContextCompat.checkSelfPermission(this, Manifest.permission.POST_NOTIFICATIONS) == PackageManager.PERMISSION_GRANTED) "granted ✓" else "not granted ✗" else "not required"
        val media = if (Build.VERSION.SDK_INT >= 33) if (ContextCompat.checkSelfPermission(this, Manifest.permission.READ_MEDIA_IMAGES) == PackageManager.PERMISSION_GRANTED) "granted ✓" else "not granted ✗" else if (ContextCompat.checkSelfPermission(this, Manifest.permission.READ_EXTERNAL_STORAGE) == PackageManager.PERMISSION_GRANTED) "granted ✓" else "not granted ✗"
        val allFiles = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) if (Environment.isExternalStorageManager()) "granted ✓" else "not granted ✗" else "not required"
        AlertDialog.Builder(this).setTitle("Folder access, notifications & battery")
            .setMessage("Photos/media: $media\nAll files access: $allFiles\nNotifications: $notification\nBattery optimisation exemption: ${if (batteryOk) "granted ✓" else "not granted ✗"}\n\nFolder access can also be granted per folder through Android’s system picker. Choose each watch card’s input and output folders to preserve focused, persistent access.")
            .setPositiveButton("Request all access") { _, _ -> requestImagePermissionOrStorageAccess() }
            .setNeutralButton("Notifications") { _, _ -> if (Build.VERSION.SDK_INT >= 33) ActivityCompat.requestPermissions(this, arrayOf(Manifest.permission.POST_NOTIFICATIONS), 1) }
            .setNegativeButton("Battery settings") { _, _ -> openBatterySettings() }.show()
    }
    private fun openBatterySettings() {
        val candidates = listOf(Intent(Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS, Uri.parse("package:$packageName")), Intent(Settings.ACTION_IGNORE_BATTERY_OPTIMIZATION_SETTINGS), Intent(Settings.ACTION_BATTERY_SAVER_SETTINGS))
        for (intent in candidates) try { startActivity(intent); return } catch (_: Exception) { }
        startActivity(Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS, Uri.parse("package:$packageName")))
    }

    private fun startBatch() {
        if (queue.isEmpty()) return
        val pass = passInput.text.toString(); if (mode != "verify" && pass.isEmpty()) { toast("Enter a passphrase first"); return }
        val batch = queue.toList(); queue.clear(); refreshQueue(); startBtn.isEnabled = false; startBtn.text = "Working…"
        batchProgress.visibility = View.VISIBLE; batchProgress.max = batch.size; batchProgress.progress = 0
        batchDetail.visibility = View.VISIBLE; batchStatus.text = "${actionLabel().removeSuffix(" queued files")} started — 0 of ${batch.size}"; FolderWatcher.log(this, "Batch ${mode} started: ${batch.size} file(s)")
        Thread {
            var completed = 0; var succeeded = 0
            for (uri in batch) {
                var ok = false
                try {
                    val index = completed + 1
                    runOnUiThread { batchStatus.text = "${actionLabel().removeSuffix(" queued files")} — $index of ${batch.size}"; batchDetail.text = "Current: ${uri.lastPathSegment}" }
                    val image = loadImage(uri)
                    if (mode == "verify") {
                        showResult(uri.lastPathSegment ?: "file", verifyImage(image, pass.ifEmpty { null }).let { "[${it.status}] ${it.message}" }, null)
                    } else {
                        val result = if (mode == "encrypt") encryptImage(image, pass, iterSlider.value.toInt()) else decryptImage(image, pass)
                        val inputStem = (uri.lastPathSegment ?: "image").substringBeforeLast('.')
                        val stem = if (mode == "decrypt" && inputStem.endsWith("_encrypted")) inputStem.removeSuffix("_encrypted") else inputStem
                        val name = if (mode == "encrypt") "${stem}_encrypted.png" else "$stem.png"
                        val output = writeOutput(result, name); showBitmap(result); showResult(uri.lastPathSegment ?: "file", "→ ${output.name}", output)
                    }
                    succeeded++; ok = true
                } catch (error: Exception) {
                    showResult(uri.lastPathSegment ?: "file", "ERROR: ${error.message}", null)
                } finally {
                    completed++; runOnUiThread { batchProgress.progress = completed }
                }
                FolderWatcher.log(this, "Batch ${mode}: ${uri.lastPathSegment} ${if (ok) "completed" else "failed"}")
            }
            runOnUiThread { refreshQueue(); batchStatus.text = "Batch complete — $succeeded of ${batch.size} succeeded"; batchDetail.text = "Last processed: ${batch.lastOrNull()?.lastPathSegment}"; startBtn.text = actionLabel(); startBtn.isEnabled = queue.isNotEmpty() }
            FolderWatcher.log(this, "Batch $mode finished: $succeeded/${batch.size} succeeded")
        }.start()
    }
    private fun loadImage(uri: Uri): ImageData = ImageInput.decode(this, uri)
    private fun writeOutput(image: ImageData, name: String): File {
        val png = encodePNG(image.pixels, image.width, image.height, image.channels)
        if (manualOutputUri != null) {
            val tree = DocumentFile.fromTreeUri(this, manualOutputUri!!) ?: error("output folder unavailable")
            var finalName = name; var n = 2
            while (tree.findFile(finalName) != null) finalName = name.substringBeforeLast('.') + "_${n++}.png"
            val doc = tree.createFile("image/png", finalName) ?: error("cannot create output")
            contentResolver.openOutputStream(doc.uri)?.use { it.write(png) } ?: error("cannot write output")
            return File(cacheDir, finalName).also { it.writeBytes(png) }
        }
        val dir = File(getExternalFilesDir(null), "OptiCipher").apply { mkdirs() }; var out = File(dir, name); var n = 2
        while (out.exists()) out = File(dir, name.substringBeforeLast('.') + "_${n++}.png"); out.writeBytes(png); return out
    }
    private fun showBitmap(image: ImageData) = runOnUiThread {
        val bitmap = Bitmap.createBitmap(image.width, image.height, Bitmap.Config.ARGB_8888); val argb = IntArray(image.width * image.height)
        for (n in argb.indices) { val p = n * image.channels; argb[n] = ((if (image.channels == 4) image.pixels[p + 3].toInt() and 255 else 255) shl 24) or ((image.pixels[p].toInt() and 255) shl 16) or ((image.pixels[p + 1].toInt() and 255) shl 8) or (image.pixels[p + 2].toInt() and 255) }
        bitmap.setPixels(argb, 0, image.width, 0, 0, image.width, image.height); preview.setImageBitmap(bitmap); preview.visibility = View.VISIBLE
    }
    private fun showResult(name: String, message: String, file: File?) = runOnUiThread {
        val view = TextView(this).apply { text = "$name: $message"; setPadding(0, 8, 0, 8) }
        if (file != null) view.setOnClickListener { val uri = FileProvider.getUriForFile(this, "$packageName.provider", file); startActivity(Intent.createChooser(Intent(Intent.ACTION_SEND).apply { type = "image/png"; putExtra(Intent.EXTRA_STREAM, uri); addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION) }, "Share output")) }
        results.addView(view)
    }
    private fun toast(message: String) = Toast.makeText(this, message, Toast.LENGTH_LONG).show()
}

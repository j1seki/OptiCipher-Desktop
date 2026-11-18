package com.opticipher

import android.Manifest
import android.app.TimePickerDialog
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.Bitmap
import android.graphics.drawable.BitmapDrawable
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.provider.Settings
import android.text.method.ScrollingMovementMethod
import android.view.View
import android.view.ViewGroup
import android.view.WindowManager
import android.widget.CompoundButton
import android.widget.ImageView
import android.widget.LinearLayout
import android.widget.ProgressBar
import android.widget.ScrollView
import android.widget.TextView
import android.widget.Toast
import androidx.activity.enableEdgeToEdge
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AlertDialog
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat
import androidx.core.content.FileProvider
import androidx.core.view.ViewCompat
import androidx.core.view.WindowInsetsCompat
import androidx.coordinatorlayout.widget.CoordinatorLayout
import androidx.documentfile.provider.DocumentFile
import com.google.android.material.appbar.MaterialToolbar
import com.google.android.material.bottomnavigation.BottomNavigationView
import com.google.android.material.button.MaterialButton
import com.google.android.material.checkbox.MaterialCheckBox
import com.google.android.material.chip.ChipGroup
import com.google.android.material.materialswitch.MaterialSwitch
import com.google.android.material.slider.Slider
import com.google.android.material.textfield.TextInputEditText
import java.io.File

class MainActivity : AppCompatActivity() {
    private val queue = mutableListOf<Uri>()
    private var manualOutputUri: Uri? = null
    private var mode = "encrypt"
    private var batchRunning = false
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
    private lateinit var updateStatus: TextView
    private lateinit var updateBtn: MaterialButton
    private val progressListener = android.content.SharedPreferences.OnSharedPreferenceChangeListener { _, key ->
        if (key?.startsWith("live_") == true) runOnUiThread { refreshLiveProgress() }
    }
    private val watchProgressListener = android.content.SharedPreferences.OnSharedPreferenceChangeListener { _, key ->
        if (key?.endsWith("_live") == true) runOnUiThread { refreshWatchProgress() }
    }

    private val pickFiles = registerForActivityResult(ActivityResultContracts.OpenMultipleDocuments()) { uris ->
        if (uris.isEmpty()) toast("No images selected") else { uris.forEach(::takePersistable); queue.addAll(uris); refreshQueue() }
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
        val watchMode = pendingFolderMode
        if (watchMode != null) {
            if (uri != null) {
                takePersistable(uri); FolderWatcher.setInbox(this, watchMode, uri)
                refreshWatch(watchMode); toast("Folder access granted for auto-$watchMode")
                if (onboardingStep == OnboardingStep.ENCRYPT_INPUT && watchMode == FolderWatcher.ENCRYPT) {
                    onboardingStep = OnboardingStep.ENCRYPT_OUTPUT
                    pendingOutputMode = FolderWatcher.ENCRYPT
                    toast("Choose where encrypted images should be saved")
                    pickWatchOutput.launch(null)
                } else if (FolderWatcher.isWatching(this, watchMode)) {
                    // Changing a watched tree must not retain processed URIs
                    // from the previous tree. Re-scan the newly selected inbox.
                    FolderWatcher.resetProcessed(this, watchMode)
                    FolderWatcher.startWatching(this, watchMode)
                }
            } else {
                if (onboardingStep == OnboardingStep.ENCRYPT_INPUT) {
                    onboardingStep = null
                    toast("Folder setup cancelled — you can choose folders in the Auto-encrypt tab")
                } else toast("No folder selected")
            }
        }
        pendingFolderMode = null
    }
    private val pickWatchOutput = registerForActivityResult(ActivityResultContracts.OpenDocumentTree()) { uri ->
        val watchMode = pendingOutputMode
        if (watchMode != null) {
            if (uri != null) {
                takePersistable(uri); FolderWatcher.setOutputTree(this, watchMode, uri)
                refreshWatch(watchMode); toast("Auto-$watchMode output folder chosen")
                if (FolderWatcher.isWatching(this, watchMode)) FolderWatcher.enqueue(this, watchMode)
                if (onboardingStep == OnboardingStep.ENCRYPT_OUTPUT && watchMode == FolderWatcher.ENCRYPT) completeFolderSetup()
            } else {
                if (onboardingStep == OnboardingStep.ENCRYPT_OUTPUT) {
                    onboardingStep = null
                    toast("Output folder not selected — using app storage")
                    completeFolderSetup()
                } else toast("No folder selected")
            }
        }
        pendingOutputMode = null
    }
    private var permissionsDialog: AlertDialog? = null
    private var reopenPermissions = false

    private val requestNotifications = registerForActivityResult(ActivityResultContracts.RequestPermission()) { granted ->
        toast(if (granted) "Notifications enabled" else "Notifications off — background results still appear in Activity")
        if (reopenPermissions) { reopenPermissions = false; showPermissionsDialog() }
    }
    private val requestImages = registerForActivityResult(ActivityResultContracts.RequestPermission()) { granted ->
        val partial = Build.VERSION.SDK_INT >= 34 &&
            ContextCompat.checkSelfPermission(this, Manifest.permission.READ_MEDIA_VISUAL_USER_SELECTED) == PackageManager.PERMISSION_GRANTED
        toast(when {
            granted -> "Photo library access granted"
            partial -> "Photo library access granted for selected photos"
            else -> "Photo library access not granted — the system picker still works"
        })
        if (reopenPermissions) { reopenPermissions = false; showPermissionsDialog() }
    }

    private enum class OnboardingStep { ENCRYPT_INPUT, ENCRYPT_OUTPUT }

    private companion object {
        const val STATE_ONBOARDING = "onboarding_step"
        const val STATE_PENDING_FOLDER = "pending_folder_mode"
        const val STATE_PENDING_OUTPUT = "pending_output_mode"
        const val STATE_MODE = "batch_mode"
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge(); setContentView(R.layout.activity_main)
        applyInsets()
        // Remove the previous misplaced batch schedule, including its stored secret.
        androidx.work.WorkManager.getInstance(this).cancelUniqueWork("weekly-batch")
        FolderWatcher.setRememberPassphrase(this, "scheduled_batch", false)
        FolderWatcher.clearStoredPassphrase(this, "scheduled_batch")
        migrateExistingWatchDefaults()
        passInput = findViewById(R.id.pass); iterSlider = findViewById(R.id.iter); iterLabel = findViewById(R.id.iterLabel)
        findViewById<MaterialButton>(R.id.batchGenerate).setOnClickListener { generatePassphrase(passInput) }
        queueView = findViewById(R.id.queueView); startBtn = findViewById(R.id.startBtn)
        results = findViewById(R.id.results); preview = findViewById(R.id.preview); manualOutView = findViewById(R.id.manualOutView)
        batchStatus = findViewById(R.id.batchStatus); batchDetail = findViewById(R.id.batchDetail); batchProgress = findViewById(R.id.batchProgress)
        manualOutputUri = getSharedPreferences("manual", Context.MODE_PRIVATE).getString("output_uri", null)?.let(Uri::parse)
        onboardingStep = savedInstanceState?.getString(STATE_ONBOARDING)?.let { runCatching { OnboardingStep.valueOf(it) }.getOrNull() }
        pendingFolderMode = savedInstanceState?.getString(STATE_PENDING_FOLDER)
        pendingOutputMode = savedInstanceState?.getString(STATE_PENDING_OUTPUT)
        mode = savedInstanceState?.getString(STATE_MODE) ?: "encrypt"
        iterSlider.value = 200000f; updateIterLabel(); iterSlider.addOnChangeListener { _, _, _ -> updateIterLabel() }

        val modeGroup = findViewById<ChipGroup>(R.id.modeGroup)
        modeGroup.check(when (mode) { "decrypt" -> R.id.modeDecrypt; "verify" -> R.id.modeVerify; else -> R.id.modeEncrypt })
        modeGroup.setOnCheckedStateChangeListener { _, ids ->
            mode = when (ids.firstOrNull()) { R.id.modeDecrypt -> "decrypt"; R.id.modeVerify -> "verify"; else -> "encrypt" }; refreshQueue()
        }
        findViewById<MaterialButton>(R.id.pickBtn).setOnClickListener { pickFiles.launch(arrayOf("image/*")) }
        findViewById<MaterialButton>(R.id.pickFolderBtn).setOnClickListener { pickBatchFolder.launch(null) }
        findViewById<MaterialButton>(R.id.outputBtn).setOnClickListener { pickBatchOutput.launch(null) }
        val privateOutput = findViewById<MaterialSwitch>(R.id.privateOutput)
        privateOutput.isChecked = getSharedPreferences("manual", Context.MODE_PRIVATE).getBoolean("private_output", false)
        privateOutput.setOnCheckedChangeListener { _, checked ->
            getSharedPreferences("manual", Context.MODE_PRIVATE).edit().putBoolean("private_output", checked).apply()
            refreshOutputs()
        }
        findViewById<MaterialButton>(R.id.privateFilesBtn).setOnClickListener { showPrivateFiles() }
        BatchSchedule.prefs(this).registerOnSharedPreferenceChangeListener(progressListener)
        getSharedPreferences("folder_watch", Context.MODE_PRIVATE).registerOnSharedPreferenceChangeListener(watchProgressListener)
        refreshLiveProgress()
        refreshWatchProgress()
        findViewById<MaterialButton>(R.id.clearQueueBtn).setOnClickListener { queue.clear(); refreshQueue() }
        startBtn.setOnClickListener { startBatch() }
        findViewById<MaterialButton>(R.id.batchCheckBtn).setOnClickListener { runBatchCheck() }
        setupWatch(FolderWatcher.ENCRYPT)
        setupWatch(FolderWatcher.DECRYPT)
        // Re-register the live observers after the process was recreated.
        if (FolderWatcher.isWatching(this, FolderWatcher.ENCRYPT) && !FolderWatcher.isWeekly(this, FolderWatcher.ENCRYPT)) FolderWatcher.startWatching(this, FolderWatcher.ENCRYPT)
        if (FolderWatcher.isWatching(this, FolderWatcher.DECRYPT) && !FolderWatcher.isWeekly(this, FolderWatcher.DECRYPT)) FolderWatcher.startWatching(this, FolderWatcher.DECRYPT)
        if (FolderWatcher.isWatching(this, FolderWatcher.ENCRYPT) || FolderWatcher.isWatching(this, FolderWatcher.DECRYPT)) WatchService.start(this)
        setupNav()
        findViewById<MaterialToolbar>(R.id.toolbar).setOnMenuItemClickListener { item ->
            if (item.itemId == R.id.action_settings) { showSettings(); true } else false
        }
        findViewById<MaterialToolbar>(R.id.toolbar).menu.findItem(R.id.action_settings)?.icon?.setTint(ContextCompat.getColor(this, R.color.brand_on_surface))
        findViewById<MaterialButton>(R.id.permissionsBtn).setOnClickListener { showPermissionsDialog() }
        updateStatus = findViewById(R.id.updateStatus)
        updateBtn = findViewById(R.id.updateBtn)
        updateStatus.text = "Installed version: ${Updater.currentVersion(this)}"
        updateBtn.setOnClickListener { checkForUpdates() }
        findViewById<MaterialButton>(R.id.refreshLogBtn).setOnClickListener { refreshActivity() }
        findViewById<MaterialButton>(R.id.clearLogBtn).setOnClickListener { FolderWatcher.clearActivityLog(this); refreshActivity() }
        refreshQueue(); refreshOutputs(); refreshWatch(FolderWatcher.ENCRYPT); refreshWatch(FolderWatcher.DECRYPT)
        refreshActivity()
        handleShareIntent(intent)
        showFirstRunSetupIfNeeded()
    }

    private fun setupNav() {
        val nav = findViewById<BottomNavigationView>(R.id.bottomNav)
        val batch = findViewById<View>(R.id.batchPage)
        val watch = findViewById<View>(R.id.watchPage)
        val activity = findViewById<View>(R.id.activityPage)
        val fab = findViewById<View>(R.id.startBtn)
        fun show(id: Int) {
            batch.visibility = if (id == R.id.nav_batch) View.VISIBLE else View.GONE
            watch.visibility = if (id == R.id.nav_watch) View.VISIBLE else View.GONE
            activity.visibility = if (id == R.id.nav_activity) View.VISIBLE else View.GONE
            fab.visibility = if (id == R.id.nav_batch) View.VISIBLE else View.GONE
            if (id == R.id.nav_activity) refreshActivity()
        }
        nav.setOnItemSelectedListener { show(it.itemId); true }
        nav.setOnItemReselectedListener { if (it.itemId == R.id.nav_activity) refreshActivity() }
        nav.selectedItemId = R.id.nav_batch
    }

    /** Keep the bottom navigation and FAB above Android's gesture/navigation bar. */
    private fun applyInsets() {
        val root = findViewById<View>(R.id.root)
        val nav = findViewById<BottomNavigationView>(R.id.bottomNav)
        val content = findViewById<View>(R.id.contentFrame)
        val fab = findViewById<View>(R.id.startBtn)
        val density = resources.displayMetrics.density
        val navBase = (80 * density).toInt()
        val fabBase = (96 * density).toInt()
        ViewCompat.setOnApplyWindowInsetsListener(root) { view, insets ->
            val bars = insets.getInsets(WindowInsetsCompat.Type.systemBars())
            view.setPadding(0, 0, 0, 0)
            (findViewById<View>(R.id.appBar).layoutParams as? CoordinatorLayout.LayoutParams)?.let { params ->
                params.topMargin = bars.top
                findViewById<View>(R.id.appBar).layoutParams = params
            }
            nav.setPadding(nav.paddingLeft, nav.paddingTop, nav.paddingRight, bars.bottom)
            nav.layoutParams = nav.layoutParams.apply { height = navBase + bars.bottom }
            content.layoutParams = (content.layoutParams as CoordinatorLayout.LayoutParams).apply {
                bottomMargin = navBase + bars.bottom
            }
            fab.layoutParams = (fab.layoutParams as CoordinatorLayout.LayoutParams).apply {
                bottomMargin = fabBase + bars.bottom
            }
            insets
        }
    }

    /** v1.4.3: process existing inbox items by default, including upgraded installs. */
    private fun migrateExistingWatchDefaults() {
        val prefs = getSharedPreferences("folder_watch", Context.MODE_PRIVATE)
        if (prefs.getInt("watch_schema", 0) < 3) {
            prefs.edit()
                .putBoolean("encrypt_process_existing", true)
                .putBoolean("decrypt_process_existing", true)
                .putInt("watch_schema", 3)
                .apply()
            FolderWatcher.resetProcessed(this, FolderWatcher.ENCRYPT)
            FolderWatcher.resetProcessed(this, FolderWatcher.DECRYPT)
        }
    }

    private fun refreshActivity() {
        val encrypt = if (FolderWatcher.isWatching(this, FolderWatcher.ENCRYPT)) "●  Auto-encrypt  ·  On" else "○  Auto-encrypt  ·  Off"
        val decrypt = if (FolderWatcher.isWatching(this, FolderWatcher.DECRYPT)) "●  Auto-decrypt  ·  On" else "○  Auto-decrypt  ·  Off"
        findViewById<TextView>(R.id.backgroundStatus).text = "$encrypt\n$decrypt"
        val lines = FolderWatcher.activityLog(this)
        findViewById<TextView>(R.id.activityLog).text = if (lines.isEmpty()) "No activity yet" else lines.joinToString("\n")
    }

    private fun showSettings() {
        val options = arrayOf("Permissions & battery", "Check for updates", "Source code", "About OptiCipher")
        AlertDialog.Builder(this)
            .setTitle("Settings")
            .setItems(options) { _, which ->
                when (which) {
                    0 -> showPermissionsDialog()
                    1 -> {
                        checkForUpdates()
                        findViewById<BottomNavigationView>(R.id.bottomNav).selectedItemId = R.id.nav_activity
                    }
                    2 -> startActivity(Intent(Intent.ACTION_VIEW, Uri.parse("https://github.com/j1seki/OptiCipher-Desktop")))
                    3 -> AlertDialog.Builder(this).setTitle("OptiCipher")
                        .setMessage("Version ${Updater.currentVersion(this)}\nPrivate, on-device image encryption.")
                        .setPositiveButton("Close", null).show()
                }
            }.show()
    }

    private data class WatchIds(val pass: Int, val remember: Int, val folderText: Int, val folderButton: Int, val outputButton: Int,
        val existing: Int, val conflict: Int, val skip: Int, val overwrite: Int, val interval: Int, val fifteen: Int,
        val hour: Int, val sixHours: Int, val twelveHours: Int, val day: Int, val status: Int, val switch: Int, val scanNow: Int, val check: Int, val checkStatus: Int)
    private fun ids(watchMode: String) = if (watchMode == FolderWatcher.ENCRYPT) WatchIds(
        R.id.encryptWatchPass, R.id.encryptWatchRemember, R.id.encryptWatchFolders, R.id.encryptWatchFolderBtn, R.id.encryptWatchOutputBtn,
        R.id.encryptExisting, R.id.encryptConflictGroup, R.id.encryptSkip, R.id.encryptOverwrite, R.id.encryptIntervalGroup,
        R.id.encrypt15, R.id.encrypt60, R.id.encrypt360, R.id.encrypt720, R.id.encrypt1440, R.id.encryptWatchStatus, R.id.encryptWatchSwitch, R.id.encryptScanNow, R.id.encryptCheckBtn, R.id.encryptCheckStatus
    ) else WatchIds(
        R.id.decryptWatchPass, R.id.decryptWatchRemember, R.id.decryptWatchFolders, R.id.decryptWatchFolderBtn, R.id.decryptWatchOutputBtn,
        R.id.decryptExisting, R.id.decryptConflictGroup, R.id.decryptSkip, R.id.decryptOverwrite, R.id.decryptIntervalGroup,
        R.id.decrypt15, R.id.decrypt60, R.id.decrypt360, R.id.decrypt720, R.id.decrypt1440, R.id.decryptWatchStatus, R.id.decryptWatchSwitch, R.id.decryptScanNow, R.id.decryptCheckBtn, R.id.decryptCheckStatus
    )

    private fun setupWatch(watchMode: String) {
        val i = ids(watchMode)
        val pass = findViewById<TextInputEditText>(i.pass)
        findViewById<MaterialButton>(if (watchMode == FolderWatcher.ENCRYPT) R.id.encryptGenerate else R.id.decryptGenerate)
            .setOnClickListener { generatePassphrase(pass) }
        findViewById<MaterialButton>(if (watchMode == FolderWatcher.ENCRYPT) R.id.encryptWeekly else R.id.decryptWeekly)
            .setOnClickListener { configureWeeklyWatch(watchMode) }
        val remember = findViewById<CompoundButton>(i.remember)
        val existing = findViewById<CompoundButton>(i.existing)
        val watchSwitch = findViewById<MaterialSwitch>(i.switch)
        pass.setText(FolderWatcher.restorePassphraseIfEnabled(this, watchMode) ?: "")
        remember.isChecked = FolderWatcher.isRemembering(this, watchMode)
        existing.isChecked = FolderWatcher.processExisting(this, watchMode)
        watchSwitch.isChecked = FolderWatcher.isWatching(this, watchMode)
        remember.setOnCheckedChangeListener { _, checked ->
            FolderWatcher.setRememberPassphrase(this, watchMode, checked)
            if (checked) {
                if (pass.text.isNullOrEmpty()) toast("Enter a passphrase to remember it")
                else if (!FolderWatcher.storePassphraseIfEnabled(this, watchMode, pass.text.toString()))
                    toast("Could not store the passphrase securely on this device")
            } else FolderWatcher.clearStoredPassphrase(this, watchMode)
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
        interval.isSelectionRequired = false
        if (!FolderWatcher.isWeekly(this, watchMode)) interval.check(when (FolderWatcher.getIntervalMinutes(this, watchMode)) { 60 -> i.hour; 360 -> i.sixHours; 720 -> i.twelveHours; 1440 -> i.day; else -> i.fifteen }) else interval.clearCheck()
        interval.setOnCheckedStateChangeListener { _, chosen ->
            if (chosen.isEmpty()) return@setOnCheckedStateChangeListener
            val minutes = when (chosen.firstOrNull()) { i.hour -> 60; i.sixHours -> 360; i.twelveHours -> 720; i.day -> 1440; else -> 15 }
            FolderWatcher.setIntervalSchedule(this, watchMode)
            FolderWatcher.setIntervalMinutes(this, watchMode, minutes)
            if (FolderWatcher.isWatching(this, watchMode)) FolderWatcher.startWatching(this, watchMode)
            refreshWatch(watchMode)
        }
        watchSwitch.setOnCheckedChangeListener { _, checked ->
            if (checked) startWatch(watchMode, pass, remember, existing, watchSwitch)
            else {
                FolderWatcher.stopWatching(this, watchMode)
                WatchService.stopIfIdle(this)
                refreshWatch(watchMode)
            }
        }
        findViewById<MaterialButton>(i.scanNow).setOnClickListener {
            if (!FolderWatcher.isWatching(this, watchMode)) { toast("Turn on the watch first"); return@setOnClickListener }
            FolderWatcher.enqueue(this, watchMode)
            toast("Scan queued")
        }
        findViewById<MaterialButton>(i.check).setOnClickListener { runWatchCheck(watchMode) }
        refreshWatch(watchMode)
    }

    private fun startWatch(watchMode: String, pass: TextInputEditText, remember: CompoundButton, existing: CompoundButton, watchSwitch: MaterialSwitch) {
        if (FolderWatcher.getInbox(this, watchMode) == null) {
            toast("Choose a folder first")
            watchSwitch.isChecked = false
            pendingFolderMode = watchMode
            pickWatchFolder.launch(null)
            return
        }
        if (pass.text.isNullOrEmpty()) {
            toast("Enter a passphrase")
            watchSwitch.isChecked = false
            return
        }
        if (!remember.isChecked) {
            toast("Enable ‘Remember passphrase’ for background watching")
            watchSwitch.isChecked = false
            return
        }
        if (!FolderWatcher.storePassphraseIfEnabled(this, watchMode, pass.text.toString())) {
            toast("Could not store the passphrase securely on this device")
            watchSwitch.isChecked = false
            return
        }
        ensureNotificationPermission()
        val begin = {
            FolderWatcher.startWatching(this, watchMode)
            WatchService.start(this)
            refreshWatch(watchMode)
            toast("Auto-$watchMode is on")
        }
        // Re-scan the selected inbox when enabling. The output conflict policy
        // independently decides whether existing outputs are skipped or overwritten.
        if (existing.isChecked) FolderWatcher.resetProcessed(this, watchMode)
        else FolderWatcher.markExistingProcessed(this, watchMode)
        begin()
    }

    /**
     * First-launch flow: only a scoped SAF folder grant is required. Broad
     * storage permissions are neither needed nor requested; photo-library and
     * notification access are optional and can be enabled later.
     */
    private fun showFirstRunSetupIfNeeded() {
        val settings = getSharedPreferences("onboarding", Context.MODE_PRIVATE)
        if (settings.getBoolean("initial_folder_setup_done", false)) return
        AlertDialog.Builder(this)
            .setTitle("Set up folder access")
            .setMessage(
                "OptiCipher works entirely on-device.\n\n" +
                    "Choose a folder to watch for new images. Android grants access only to that folder, and the grant survives reboots."
            )
            .setPositiveButton("Choose folders") { _, _ -> beginFolderSetup() }
            .setNegativeButton("Skip for now") { _, _ -> markOnboardingDone() }
            .setCancelable(true)
            .show()
    }

    private fun markOnboardingDone() {
        getSharedPreferences("onboarding", Context.MODE_PRIVATE).edit().putBoolean("initial_folder_setup_done", true).apply()
    }

    private fun beginFolderSetup() {
        onboardingStep = OnboardingStep.ENCRYPT_INPUT
        pendingFolderMode = FolderWatcher.ENCRYPT
        toast("Choose the folder whose images you want to auto-encrypt")
        pickWatchFolder.launch(null)
    }

    private fun completeFolderSetup() {
        onboardingStep = null
        markOnboardingDone()
        AlertDialog.Builder(this)
            .setTitle("Folder access ready")
            .setMessage("OptiCipher will watch the folders you selected. Enter a passphrase and tap ‘Turn on auto-encrypt’ when ready.\n\nAuto-decrypt has its own folders and passphrase in the Auto-decrypt tab. You can change any folder later; notifications and battery settings are optional.")
            .setPositiveButton("Battery settings") { _, _ -> openBatterySettings() }
            .setNegativeButton("Done", null)
            .show()
    }

    private fun mediaStatus(): String = when {
        Build.VERSION.SDK_INT >= 33 && ContextCompat.checkSelfPermission(this, Manifest.permission.READ_MEDIA_IMAGES) == PackageManager.PERMISSION_GRANTED -> "granted ✓"
        Build.VERSION.SDK_INT >= 34 && ContextCompat.checkSelfPermission(this, Manifest.permission.READ_MEDIA_VISUAL_USER_SELECTED) == PackageManager.PERMISSION_GRANTED -> "selected photos ✓"
        Build.VERSION.SDK_INT < 33 && ContextCompat.checkSelfPermission(this, Manifest.permission.READ_EXTERNAL_STORAGE) == PackageManager.PERMISSION_GRANTED -> "granted ✓"
        else -> "not granted (optional)"
    }

    private fun requestMediaPermission() {
        val permission = if (Build.VERSION.SDK_INT >= 33) Manifest.permission.READ_MEDIA_IMAGES else Manifest.permission.READ_EXTERNAL_STORAGE
        if (ContextCompat.checkSelfPermission(this, permission) == PackageManager.PERMISSION_GRANTED) {
            reopenPermissions = false; toast("Photo library access already granted")
        } else requestImages.launch(permission)
    }

    private fun requestNotificationPermission() {
        if (Build.VERSION.SDK_INT < 33) { reopenPermissions = false; toast("Notifications are allowed automatically on this Android version"); return }
        if (ContextCompat.checkSelfPermission(this, Manifest.permission.POST_NOTIFICATIONS) == PackageManager.PERMISSION_GRANTED) {
            reopenPermissions = false; toast("Notifications already allowed")
        } else requestNotifications.launch(Manifest.permission.POST_NOTIFICATIONS)
    }

    private fun ensureNotificationPermission() {
        if (Build.VERSION.SDK_INT >= 33 && ContextCompat.checkSelfPermission(this, Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED)
            requestNotifications.launch(Manifest.permission.POST_NOTIFICATIONS)
    }

    private fun folderLabel(uri: Uri?): String = uri?.lastPathSegment?.substringAfterLast(':')?.takeIf { it.isNotBlank() } ?: uri?.lastPathSegment ?: ""

    private fun refreshWatch(watchMode: String) {
        val i = ids(watchMode); val inbox = FolderWatcher.getInbox(this, watchMode); val out = FolderWatcher.getOutputTree(this, watchMode)
        findViewById<TextView>(i.folderText).text = "In: ${inbox?.let(::folderLabel) ?: "not selected"}\nOut: ${out?.let(::folderLabel) ?: "app storage"}"
        val every = if (FolderWatcher.isWeekly(this, watchMode)) FolderWatcher.weeklyLabel(this, watchMode) else when (FolderWatcher.getIntervalMinutes(this, watchMode)) { 60 -> "every hour"; 360 -> "every 6 hours"; 720 -> "every 12 hours"; 1440 -> "daily"; else -> "every 15 min" }
        findViewById<TextView>(i.status).text = if (FolderWatcher.isWatching(this, watchMode)) "On · $every" else "Off"
        findViewById<MaterialButton>(if (watchMode == FolderWatcher.ENCRYPT) R.id.encryptWeekly else R.id.decryptWeekly).text = if (FolderWatcher.isWeekly(this, watchMode)) "$every · change" else "Schedule weekday and time"
    }

    private fun configureWeeklyWatch(watchMode: String) {
        val days = arrayOf("Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday")
        AlertDialog.Builder(this).setTitle("Choose a weekday").setItems(days) { _, day ->
            TimePickerDialog(this, { _, hour, minute ->
                FolderWatcher.setWeekly(this, watchMode, day + 1, hour, minute)
                findViewById<ChipGroup>(ids(watchMode).interval).clearCheck()
                if (FolderWatcher.isWatching(this, watchMode)) FolderWatcher.startWatching(this, watchMode)
                refreshWatch(watchMode)
                toast("Weekly schedule set; Android may delay the scan")
            }, 9, 0, true).show()
        }.setNegativeButton("Cancel", null).show()
    }

    private fun generatePassphrase(field: TextInputEditText) {
        val alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789!@#%+-_"
        val random = java.security.SecureRandom()
        val value = buildString { repeat(28) { append(alphabet[random.nextInt(alphabet.length)]) } }
        AlertDialog.Builder(this).setTitle("Generated passphrase")
            .setMessage("$value\n\nSave this somewhere safe. You need the same passphrase to decrypt; it cannot be recovered if lost.")
            .setPositiveButton("Use passphrase") { _, _ ->
                field.setText(value)
                if (field.id == R.id.encryptWatchPass && FolderWatcher.isRemembering(this, FolderWatcher.ENCRYPT)) FolderWatcher.storePassphraseIfEnabled(this, FolderWatcher.ENCRYPT, value)
                if (field.id == R.id.decryptWatchPass && FolderWatcher.isRemembering(this, FolderWatcher.DECRYPT)) FolderWatcher.storePassphraseIfEnabled(this, FolderWatcher.DECRYPT, value)
            }.setNegativeButton("Cancel", null).show()
    }

    private fun readyStatus(viewId: Int, passed: Boolean, details: String) {
        val status = findViewById<TextView>(viewId)
        status.text = if (passed) "✓ Ready\n$details" else "✗ Needs attention\n$details"
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
            fun note(condition: Boolean, pass: String, warn: String) { findings += if (condition) "✓ $pass" else "⚠ $warn" }
            // Folder access comes from the SAF tree grant, not a broad storage
            // permission, so only the selected folders need to be readable.
            val input = FolderWatcher.getInbox(this, watchMode)?.let { DocumentFile.fromTreeUri(this, it) }
            requireCheck(input != null && input.canRead(), "input folder readable", "select an accessible input folder")
            val output = FolderWatcher.getOutputTree(this, watchMode)?.let { DocumentFile.fromTreeUri(this, it) }
            if (output != null) requireCheck(output.canWrite(), "output folder writable", "output folder is not writable")
            else findings += "✓ app storage output available (no output folder selected)"
            requireCheck(FolderWatcher.restorePassphraseIfEnabled(this, watchMode)?.isNotEmpty() == true, "background passphrase stored securely", "enter a passphrase and enable Remember passphrase")
            try {
                val tiny = ImageData(byteArrayOf(10, 20, 30), 1, 1, 3)
                val restored = decryptImage(encryptImage(tiny, "OptiCipher-self-test", 10_000), "OptiCipher-self-test")
                requireCheck(restored.pixels.contentEquals(tiny.pixels), "crypto round-trip passed", "crypto result mismatch")
            } catch (e: Exception) { ok = false; findings += "✗ crypto self-test: ${e.message}" }
            val notificationsOn = Build.VERSION.SDK_INT < 33 ||
                ContextCompat.checkSelfPermission(this, Manifest.permission.POST_NOTIFICATIONS) == PackageManager.PERMISSION_GRANTED
            note(notificationsOn, "notifications enabled", "notifications are off — background results will only appear in Activity")
            val batteryOk = getSystemService(android.os.PowerManager::class.java)?.isIgnoringBatteryOptimizations(packageName) != false
            note(batteryOk, "battery optimisation exemption granted", "battery optimisation may delay background checks")
            val heapMb = Runtime.getRuntime().maxMemory() / (1024 * 1024)
            findings += "✓ device processing heap: ${heapMb} MB"
            findings += "Large photos may exceed this device’s memory limit; the app will identify them in Activity."
            runOnUiThread { readyStatus(i.checkStatus, ok, findings.joinToString("\n")) }
        }.start()
    }

    override fun onSaveInstanceState(outState: Bundle) {
        super.onSaveInstanceState(outState)
        outState.putString(STATE_ONBOARDING, onboardingStep?.name)
        outState.putString(STATE_PENDING_FOLDER, pendingFolderMode)
        outState.putString(STATE_PENDING_OUTPUT, pendingOutputMode)
        outState.putString(STATE_MODE, mode)
    }

    override fun onNewIntent(intent: Intent) { super.onNewIntent(intent); handleShareIntent(intent) }
    @Suppress("DEPRECATION") private fun handleShareIntent(intent: Intent?) {
        val uris = mutableListOf<Uri>()
        when (intent?.action) {
            Intent.ACTION_SEND -> intent.getParcelableExtra<Uri>(Intent.EXTRA_STREAM)?.let(uris::add)
            Intent.ACTION_SEND_MULTIPLE -> intent.getParcelableArrayListExtra<Uri>(Intent.EXTRA_STREAM)?.let(uris::addAll)
            Intent.ACTION_VIEW -> intent.data?.let(uris::add)
        }
        if (uris.isNotEmpty()) { queue.addAll(uris); refreshQueue(); toast("Added ${uris.size} shared item(s) to the queue") }
    }
    private fun addFolderToQueue(uri: Uri) {
        takePersistable(uri)
        toast("Scanning folder…")
        Thread {
            val files = DocumentFile.fromTreeUri(this, uri)?.listFiles()?.filter { it.isFile && isImageName(it.name) } ?: emptyList()
            runOnUiThread {
                if (isFinishing || isDestroyed) return@runOnUiThread
                if (files.isEmpty()) toast("No supported images in the selected folder")
                else { queue.addAll(files.map { it.uri }); refreshQueue(); toast("Added ${files.size} images") }
            }
        }.start()
    }
    private fun isImageName(name: String?) = ImageFormats.isSupported(name)
    private fun takePersistable(uri: Uri) {
        val readWrite = Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_GRANT_WRITE_URI_PERMISSION
        try {
            contentResolver.takePersistableUriPermission(uri, readWrite)
        } catch (_: Exception) {
            // Some providers grant read-only trees; keep at least that grant.
            try { contentResolver.takePersistableUriPermission(uri, Intent.FLAG_GRANT_READ_URI_PERMISSION) } catch (_: Exception) { }
        }
    }
    private fun updateIterLabel() { iterLabel.text = "${iterSlider.value.toInt()} iterations" }
    private fun actionLabel() = when (mode) { "encrypt" -> "Encrypt files"; "decrypt" -> "Decrypt files"; else -> "Verify files" }
    private fun refreshQueue() {
        queueView.text = if (queue.isEmpty()) "No files yet" else "${queue.size} file(s) · " + queue.take(3).joinToString(", ") { it.lastPathSegment ?: "" } + if (queue.size > 3) " +${queue.size - 3}" else ""
        startBtn.text = if (batchRunning) "Working…" else actionLabel(); startBtn.isEnabled = queue.isNotEmpty() && !batchRunning
        startBtn.visibility = if (queue.isEmpty()) View.GONE else View.VISIBLE
    }
    private fun refreshOutputs() {
        val isPrivate = getSharedPreferences("manual", Context.MODE_PRIVATE).getBoolean("private_output", false)
        manualOutView.text = if (isPrivate) "Private folder" else manualOutputUri?.let(::folderLabel) ?: "App storage"
    }

    private fun showPrivateFiles() {
        val files = File(filesDir, "private_outputs").listFiles()?.filter { it.isFile && it.extension == "png" }?.sortedBy { it.name } ?: emptyList()
        if (files.isEmpty()) { toast("No private files yet"); return }
        AlertDialog.Builder(this).setTitle("Private folder · choose a file")
            .setItems(files.map { it.name }.toTypedArray()) { _, index ->
                val file = files[index]
                AlertDialog.Builder(this).setTitle(file.name)
                    .setItems(arrayOf("Add to batch queue", "Share a copy", "Delete")) { _, action ->
                        when (action) {
                            0 -> { queue.add(FileProvider.getUriForFile(this, "$packageName.provider", file)); refreshQueue(); toast("Added to batch") }
                            1 -> shareFile(file)
                            2 -> AlertDialog.Builder(this).setMessage("Permanently delete ${file.name}?")
                                .setPositiveButton("Delete") { _, _ -> if (!file.delete()) toast("Could not delete file") }.setNegativeButton("Cancel", null).show()
                        }
                    }.show()
            }
            .setNegativeButton("Close", null).show()
    }

    private fun refreshLiveProgress() {
        if (batchRunning) return
        val p = BatchSchedule.prefs(this)
        val title = p.getString("live_title", null) ?: return
        batchStatus.text = title
        batchDetail.text = p.getString("live_detail", "")
        batchDetail.visibility = View.VISIBLE
        batchProgress.visibility = View.VISIBLE
        batchProgress.max = p.getInt("live_total", 0).coerceAtLeast(1)
        batchProgress.progress = p.getInt("live_current", 0)
    }

    private fun refreshWatchProgress() {
        val p = getSharedPreferences("folder_watch", Context.MODE_PRIVATE)
        findViewById<TextView>(R.id.encryptLiveStatus).text = p.getString("encrypt_live", "")
        findViewById<TextView>(R.id.decryptLiveStatus).text = p.getString("decrypt_live", "")
    }

    override fun onDestroy() {
        BatchSchedule.prefs(this).unregisterOnSharedPreferenceChangeListener(progressListener)
        getSharedPreferences("folder_watch", Context.MODE_PRIVATE).unregisterOnSharedPreferenceChangeListener(watchProgressListener)
        super.onDestroy()
    }

    private fun shareFile(file: File) {
        val uri = FileProvider.getUriForFile(this, "$packageName.provider", file)
        startActivity(Intent.createChooser(Intent(Intent.ACTION_SEND).apply {
            type = "image/png"; putExtra(Intent.EXTRA_STREAM, uri); addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
        }, "Export a copy"))
    }

    private fun showPermissionsDialog() {
        val batteryOk = getSystemService(android.os.PowerManager::class.java)?.isIgnoringBatteryOptimizations(packageName) != false
        val notifications = if (Build.VERSION.SDK_INT >= 33) if (ContextCompat.checkSelfPermission(this, Manifest.permission.POST_NOTIFICATIONS) == PackageManager.PERMISSION_GRANTED) "granted ✓" else "not granted ✗" else "allowed ✓"
        val encryptIn = FolderWatcher.getInbox(this, FolderWatcher.ENCRYPT)?.let(::folderLabel) ?: "not selected"
        val encryptOut = FolderWatcher.getOutputTree(this, FolderWatcher.ENCRYPT)?.let(::folderLabel) ?: "app storage"
        val decryptIn = FolderWatcher.getInbox(this, FolderWatcher.DECRYPT)?.let(::folderLabel) ?: "not selected"
        val decryptOut = FolderWatcher.getOutputTree(this, FolderWatcher.DECRYPT)?.let(::folderLabel) ?: "app storage"
        val message =
            "Folder access is granted only for the folders you pick — OptiCipher never asks for all-files access.\n\n" +
                "Auto-encrypt input: $encryptIn\nAuto-encrypt output: $encryptOut\n" +
                "Auto-decrypt input: $decryptIn\nAuto-decrypt output: $decryptOut\n\n" +
                "Notifications: $notifications\n" +
                "Photo library (optional): ${mediaStatus()}\n" +
                "Battery optimisation exemption: ${if (batteryOk) "granted ✓" else "not granted ✗"}"

        val density = resources.displayMetrics.density
        var dialog: AlertDialog? = null
        val content = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding((20 * density).toInt(), (8 * density).toInt(), (20 * density).toInt(), 0)
            addView(TextView(this@MainActivity).apply {
                text = message
                setPadding(0, 0, 0, (8 * density).toInt())
            })
            fun action(label: String, onClick: () -> Unit) {
                addView(MaterialButton(this@MainActivity).apply {
                    text = label
                    isAllCaps = false
                    setOnClickListener { dialog?.dismiss(); onClick() }
                })
            }
            action("Choose auto-encrypt folder") { pendingFolderMode = FolderWatcher.ENCRYPT; pickWatchFolder.launch(null) }
            action("Photo library access (optional)") { reopenPermissions = true; requestMediaPermission() }
            action("Allow notifications") { reopenPermissions = true; requestNotificationPermission() }
            action("Battery optimisation settings") { openBatterySettings() }
        }
        val built = AlertDialog.Builder(this)
            .setTitle("Permissions & background access")
            .setView(ScrollView(this).apply { addView(content) })
            .setNegativeButton("Close", null)
            .create()
        built.setOnDismissListener { if (permissionsDialog === built) permissionsDialog = null }
        permissionsDialog = built
        dialog = built
        built.show()
    }

    private fun openBatterySettings() {
        val candidates = listOf(
            Intent(Settings.ACTION_IGNORE_BATTERY_OPTIMIZATION_SETTINGS),
            Intent(Settings.ACTION_BATTERY_SAVER_SETTINGS),
            Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS, Uri.parse("package:$packageName"))
        )
        for (intent in candidates) try { startActivity(intent); return } catch (_: Exception) { }
        toast("Could not open battery settings")
    }

    private fun checkForUpdates() {
        updateBtn.isEnabled = false
        updateStatus.text = "Checking GitHub for updates…"
        Thread {
            try {
                val result = Updater.check(this)
                runOnUiThread {
                    if (isFinishing || isDestroyed) return@runOnUiThread
                    updateBtn.isEnabled = true
                    val release = result.release
                    when {
                        release == null -> updateStatus.text = "No Android APK found in the latest release (installed v${result.currentVersion})."
                        !result.newer -> updateStatus.text = "Up to date — installed v${result.currentVersion}; latest release v${release.version}."
                        else -> showUpdateDialog(release)
                    }
                }
            } catch (error: Exception) {
                runOnUiThread {
                    if (isFinishing || isDestroyed) return@runOnUiThread
                    updateBtn.isEnabled = true
                    updateStatus.text = "Update check failed: ${error.message}"
                }
            }
        }.start()
    }

    private fun showUpdateDialog(release: Updater.Release) {
        val notes = release.notes.trim().take(2000).ifBlank { "No release notes provided." }
        val size = if (release.size > 0) " (${"%.1f".format(release.size / 1024.0 / 1024.0)} MB)" else ""
        val body = TextView(this).apply {
            text = "A newer version is available: v${release.version}$size\n\n$notes"
            setPadding(48, 24, 48, 0)
            movementMethod = ScrollingMovementMethod()
        }
        AlertDialog.Builder(this)
            .setTitle("Update available")
            .setView(ScrollView(this).apply { addView(body) })
            .setPositiveButton("Download & install") { _, _ -> downloadAndInstall(release) }
            .setNegativeButton("Later", null)
            .show()
    }

    private fun downloadAndInstall(release: Updater.Release) {
        val cached = Updater.reusableApk(this, release)
        if (cached != null) {
            try {
                updateStatus.text = "Using downloaded v${release.version} — opening installer…"
                if (!Updater.install(this, cached)) {
                    updateStatus.text = "Allow installs from OptiCipher, then tap Check for updates again."
                }
            } catch (error: Exception) {
                updateStatus.text = "Update failed: ${error.message}"
            }
            return
        }
        val progressBar = ProgressBar(this, null, android.R.attr.progressBarStyleHorizontal).apply { max = 100 }
        val label = TextView(this).apply {
            text = "Starting download…"
            setPadding(48, 24, 48, 8)
        }
        val content = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            addView(label)
            addView(progressBar)
        }
        val dialog = AlertDialog.Builder(this)
            .setTitle("Downloading v${release.version}")
            .setView(content)
            .setCancelable(false)
            .create()
        dialog.show()
        updateBtn.isEnabled = false
        updateStatus.text = "Downloading v${release.version}…"
        Thread {
            try {
                val file = Updater.download(this, release) { percent ->
                    runOnUiThread {
                        if (dialog.isShowing) {
                            progressBar.progress = percent
                            label.text = "Downloading… $percent%"
                        }
                    }
                }
                val version = Updater.validateApk(this, file)
                runOnUiThread {
                    if (dialog.isShowing) dialog.dismiss()
                    updateBtn.isEnabled = true
                    if (isFinishing || isDestroyed) return@runOnUiThread
                    updateStatus.text = "Downloaded v$version — opening installer…"
                    if (!Updater.install(this, file)) {
                        updateStatus.text = "Allow installs from OptiCipher, then tap Check for updates again."
                    }
                }
            } catch (error: Exception) {
                runOnUiThread {
                    if (dialog.isShowing) dialog.dismiss()
                    updateBtn.isEnabled = true
                    updateStatus.text = "Update failed: ${error.message}"
                    toast("Update failed: ${error.message}")
                }
            }
        }.start()
    }

    private fun startBatch() {
        if (queue.isEmpty() || batchRunning) return
        val pass = passInput.text.toString(); if (mode != "verify" && pass.isEmpty()) { toast("Enter a passphrase first"); return }
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        val batchMode = mode
        val iterations = iterSlider.value.toInt()
        val privateOutput = getSharedPreferences("manual", Context.MODE_PRIVATE).getBoolean("private_output", false)
        val outputUri = manualOutputUri
        batchRunning = true
        val batch = queue.toList(); queue.clear(); refreshQueue(); startBtn.isEnabled = false; startBtn.text = "Working…"
        batchProgress.visibility = View.VISIBLE; batchProgress.max = batch.size; batchProgress.progress = 0
        batchDetail.visibility = View.VISIBLE; batchStatus.text = "${actionLabel()} started — 0 of ${batch.size}"; FolderWatcher.log(this, "Batch ${mode} started: ${batch.size} file(s)")
        ensureNotificationPermission()
        BatchSchedule.progress(this, "Batch $batchMode", "Starting ${batch.size} files", 0, batch.size)
        Thread {
            var completed = 0; var succeeded = 0
            for (uri in batch) {
                var ok = false
                val inputName = displayName(uri)
                try {
                    val index = completed + 1
                    BatchSchedule.progress(this, "Batch $batchMode · $index/${batch.size}", "Processing $inputName", completed, batch.size)
                    runOnUiThread { batchStatus.text = "${batchMode.replaceFirstChar { it.uppercase() }} — $index of ${batch.size}"; batchDetail.text = "Current: $inputName" }
                    val image = loadImage(uri)
                    if (batchMode == "verify") {
                        showResult(inputName, verifyImage(image, pass.ifEmpty { null }).let { "[${it.status}] ${it.message}" }, null)
                    } else {
                        val result = if (batchMode == "encrypt") encryptImage(image, pass, iterations) else decryptImage(image, pass)
                        val inputStem = inputName.substringBeforeLast('.')
                        val stem = if (batchMode == "decrypt" && inputStem.endsWith("_encrypted")) inputStem.removeSuffix("_encrypted") else inputStem
                        val name = if (batchMode == "encrypt") "${stem}_encrypted.png" else "$stem.png"
                        val output = writeOutput(result, name, compress = batchMode == "decrypt", privateOutput = privateOutput, outputUri = outputUri); showBitmap(result); showResult(inputName, "→ ${output.name}", output)
                    }
                    succeeded++; ok = true
                } catch (error: Exception) {
                    showResult(inputName, "ERROR: ${error.message}", null)
                } finally {
                    completed++; runOnUiThread { batchProgress.progress = completed }
                    BatchSchedule.progress(this, "Batch $batchMode", "$completed of ${batch.size} processed", completed, batch.size)
                }
                FolderWatcher.log(this, "Batch $batchMode: $inputName ${if (ok) "completed" else "failed"}")
            }
            runOnUiThread {
                if (!isFinishing && !isDestroyed) window.clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
                batchRunning = false
                refreshQueue(); batchStatus.text = "Batch complete — $succeeded of ${batch.size} succeeded"; batchDetail.text = "Last processed: ${batch.lastOrNull()?.lastPathSegment}"
            }
            FolderWatcher.log(this, "Batch $batchMode finished: $succeeded/${batch.size} succeeded")
            BatchSchedule.progress(this, "Batch complete", "$succeeded of ${batch.size} succeeded", batch.size, batch.size, true)
        }.start()
    }
    private fun loadImage(uri: Uri): ImageData = ImageInput.decode(this, uri)
    private fun displayName(uri: Uri): String {
        val fallback = uri.lastPathSegment?.substringAfterLast('/')?.takeIf { it.isNotBlank() } ?: "image"
        if (uri.scheme == "raw" || uri.scheme == "file") {
            return (uri.path ?: uri.schemeSpecificPart)?.substringAfterLast('/')?.takeIf { it.isNotBlank() } ?: fallback
        }
        return try {
            DocumentFile.fromSingleUri(this, uri)?.name ?: fallback
        } catch (_: Exception) {
            fallback
        }
    }
    private fun writeOutput(image: ImageData, name: String, compress: Boolean = true, privateOutput: Boolean = false, outputUri: Uri? = null): File {
        require(name == File(name).name && name != "." && name != "..") { "Invalid output filename" }
        val png = encodePNG(image.pixels, image.width, image.height, image.channels, compress = compress)
        if (!privateOutput && outputUri != null) {
            val tree = DocumentFile.fromTreeUri(this, outputUri) ?: error("output folder unavailable")
            var finalName = name; var n = 2
            while (tree.findFile(finalName) != null) finalName = name.substringBeforeLast('.') + "_${n++}.png"
            val doc = tree.createFile("image/png", finalName) ?: error("cannot create output")
            contentResolver.openOutputStream(doc.uri)?.use { it.write(png) } ?: error("cannot write output")
            val cacheName = (doc.name ?: finalName).replace(Regex("[^A-Za-z0-9._-]"), "_")
            return File(cacheDir, cacheName).also { it.writeBytes(png) }
        }
        val dir = if (privateOutput) File(filesDir, "private_outputs") else File(getExternalFilesDir(null), "OptiCipher")
        check(dir.exists() || dir.mkdirs()) { "Cannot create output folder" }
        var out = File(dir, name); var n = 2
        while (out.exists()) out = File(dir, name.substringBeforeLast('.') + "_${n++}.png"); out.writeBytes(png); return out
    }
    private fun showBitmap(image: ImageData) = runOnUiThread {
        if (isFinishing || isDestroyed) return@runOnUiThread
        val old = preview.drawable
        preview.setImageDrawable(null)
        (old as? BitmapDrawable)?.bitmap?.takeIf { !it.isRecycled }?.recycle()
        val bitmap = Bitmap.createBitmap(image.width, image.height, Bitmap.Config.ARGB_8888); val argb = IntArray(image.width * image.height)
        for (n in argb.indices) { val p = n * image.channels; argb[n] = ((if (image.channels == 4) image.pixels[p + 3].toInt() and 255 else 255) shl 24) or ((image.pixels[p].toInt() and 255) shl 16) or ((image.pixels[p + 1].toInt() and 255) shl 8) or (image.pixels[p + 2].toInt() and 255) }
        bitmap.setPixels(argb, 0, image.width, 0, 0, image.width, image.height); preview.setImageBitmap(bitmap); preview.visibility = View.VISIBLE
    }
    private fun showResult(name: String, message: String, file: File?) = runOnUiThread {
        if (isFinishing || isDestroyed) return@runOnUiThread
        val view = TextView(this).apply { text = "$name: $message"; setPadding(0, 8, 0, 8) }
        if (file != null) view.setOnClickListener { shareFile(file) }
        results.addView(view)
    }
    private fun toast(message: String) = Toast.makeText(this, message, Toast.LENGTH_LONG).show()
}

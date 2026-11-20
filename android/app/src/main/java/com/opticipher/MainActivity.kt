package com.opticipher

import android.Manifest
import android.app.TimePickerDialog
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.provider.Settings
import android.text.method.ScrollingMovementMethod
import android.text.InputType
import android.view.View
import android.view.ViewGroup
import android.view.WindowManager
import android.widget.CompoundButton
import android.widget.EditText
import android.widget.AdapterView
import android.widget.ArrayAdapter
import android.widget.ImageView
import android.widget.LinearLayout
import android.widget.ProgressBar
import android.widget.ScrollView
import android.widget.Spinner
import android.widget.TextView
import android.widget.Toast
import androidx.activity.enableEdgeToEdge
import androidx.activity.OnBackPressedCallback
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AlertDialog
import androidx.appcompat.app.AppCompatActivity
import androidx.appcompat.app.AppCompatDelegate
import androidx.core.content.ContextCompat
import androidx.core.content.FileProvider
import androidx.core.widget.doAfterTextChanged
import androidx.core.view.ViewCompat
import androidx.core.view.WindowCompat
import androidx.core.view.WindowInsetsCompat
import androidx.coordinatorlayout.widget.CoordinatorLayout
import androidx.documentfile.provider.DocumentFile
import androidx.lifecycle.ViewModelProvider
import com.google.android.material.appbar.MaterialToolbar
import com.google.android.material.bottomnavigation.BottomNavigationView
import com.google.android.material.button.MaterialButton
import com.google.android.material.checkbox.MaterialCheckBox
import com.google.android.material.chip.ChipGroup
import com.google.android.material.dialog.MaterialAlertDialogBuilder
import com.google.android.material.materialswitch.MaterialSwitch
import com.google.android.material.slider.Slider
import com.google.android.material.textfield.TextInputEditText
import com.google.android.material.textfield.TextInputLayout
import java.io.File

class MainActivity : AppCompatActivity() {
    private val queue = mutableListOf<Uri>()
    private var manualOutputUri: Uri? = null
    private var onSftpKeyPicked: ((Uri) -> Unit)? = null
    private var mode = "encrypt"
    private lateinit var batch: BatchSession
    private var batchRunning = false
    private var renderedBatchId: String? = null
    private var pendingFolderMode: String? = null
    private var pendingOutputMode: String? = null
    // First-run setup requests a scoped SAF folder grant. Android deliberately
    // does not provide a broad runtime "all folders" permission; the picker is
    // the operating system's folder-permission prompt.
    private var onboardingStep: OnboardingStep? = null
    private lateinit var passInput: TextInputEditText
    private lateinit var confirmInput: TextInputEditText
    private var shownAnalysis: ImageAnalysis? = null
    private lateinit var iterSlider: Slider
    private lateinit var iterLabel: TextView
    private lateinit var queueView: TextView
    private lateinit var startBtn: MaterialButton
    private lateinit var stopBtn: MaterialButton
    private lateinit var settingsBack: OnBackPressedCallback
    private lateinit var results: LinearLayout
    private lateinit var preview: ImageView
    private lateinit var manualOutView: TextView
    private lateinit var batchStatus: TextView
    private lateinit var batchDetail: TextView
    private lateinit var batchProgress: com.google.android.material.progressindicator.LinearProgressIndicator
    private lateinit var updateStatus: TextView
    private lateinit var updateBtn: View
    private lateinit var logsPanel: LogsPanel
    private lateinit var jobsPanel: JobHistoryPanel
    private val watchProgressListener = android.content.SharedPreferences.OnSharedPreferenceChangeListener { _, key ->
        runOnUiThread {
            if (key?.endsWith("_live") == true) refreshWatchProgress()
        }
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
    private val pickSftpKey = registerForActivityResult(ActivityResultContracts.OpenDocument()) { uri ->
        if (uri != null) onSftpKeyPicked?.invoke(uri)
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
                    if (!FolderWatcher.processExisting(this, watchMode)) FolderWatcher.markExistingProcessed(this, watchMode)
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
                if (FolderWatcher.isWatching(this, watchMode) && !FolderWatcher.isWeekly(this, watchMode)) {
                    FolderWatcher.enqueue(this, watchMode, replace = true)
                }
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
        toast(if (granted) "Notifications enabled" else "Notifications off · Results are available in Logs")
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
        const val STATE_QUEUE = "batch_queue"
        const val STATE_WORKSPACE = "workspace"
        const val STATE_SETTINGS = "settings_open"
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        val theme = getSharedPreferences("appearance", Context.MODE_PRIVATE).getInt("theme", AppCompatDelegate.MODE_NIGHT_YES)
        delegate.localNightMode = theme
        super.onCreate(savedInstanceState)
        enableEdgeToEdge(); setContentView(R.layout.activity_main)
        applyInsets()
        // Remove the previous misplaced batch schedule, including its stored secret.
        androidx.work.WorkManager.getInstance(this).cancelUniqueWork("weekly-batch")
        FolderWatcher.setRememberPassphrase(this, "scheduled_batch", false)
        FolderWatcher.clearStoredPassphrase(this, "scheduled_batch")
        batch = ViewModelProvider(this)[BatchSession::class.java]
        passInput = findViewById(R.id.pass); iterSlider = findViewById(R.id.iter); iterLabel = findViewById(R.id.iterLabel)
        confirmInput = findViewById(R.id.batchConfirm)
        passInput.doAfterTextChanged { findViewById<TextInputLayout>(R.id.batchPassLayout).error = null }
        confirmInput.doAfterTextChanged { findViewById<TextInputLayout>(R.id.batchConfirmLayout).error = null }
        findViewById<MaterialButton>(R.id.batchGenerate).setOnClickListener { generatePassphrase(passInput) }
        queueView = findViewById(R.id.queueView); startBtn = findViewById(R.id.startBtn)
        stopBtn = findViewById(R.id.batchCancel)
        results = findViewById(R.id.results); preview = findViewById(R.id.preview); manualOutView = findViewById(R.id.manualOutView)
        batchStatus = findViewById(R.id.batchStatus); batchDetail = findViewById(R.id.batchDetail); batchProgress = findViewById(R.id.batchProgress)
        manualOutputUri = getSharedPreferences("manual", Context.MODE_PRIVATE).getString("output_uri", null)?.let(Uri::parse)
        onboardingStep = savedInstanceState?.getString(STATE_ONBOARDING)?.let { runCatching { OnboardingStep.valueOf(it) }.getOrNull() }
        pendingFolderMode = savedInstanceState?.getString(STATE_PENDING_FOLDER)
        pendingOutputMode = savedInstanceState?.getString(STATE_PENDING_OUTPUT)
        mode = savedInstanceState?.getString(STATE_MODE) ?: "encrypt"
        queue.addAll(savedInstanceState?.getStringArrayList(STATE_QUEUE).orEmpty().map(Uri::parse))
        iterSlider.value = 200000f; updateIterLabel(); iterSlider.addOnChangeListener { _, _, _ -> updateIterLabel() }

        val modeGroup = findViewById<ChipGroup>(R.id.modeGroup)
        modeGroup.check(when (mode) {
            "decrypt" -> R.id.modeDecrypt
            "verify" -> R.id.modeVerify
            "analyze" -> R.id.modeAnalyze
            else -> R.id.modeEncrypt
        })
        modeGroup.setOnCheckedStateChangeListener { _, ids ->
            mode = when (ids.firstOrNull()) {
                R.id.modeDecrypt -> "decrypt"
                R.id.modeVerify -> "verify"
                R.id.modeAnalyze -> "analyze"
                else -> "encrypt"
            }
            refreshBatchMode()
            refreshQueue()
        }
        refreshBatchMode()
        refreshSftpButton()
        findViewById<MaterialButton>(R.id.pickBtn).setOnClickListener { pickFiles.launch(arrayOf("image/*")) }
        findViewById<MaterialButton>(R.id.pickFolderBtn).setOnClickListener { pickBatchFolder.launch(null) }
        findViewById<MaterialButton>(R.id.outputBtn).setOnClickListener { pickBatchOutput.launch(null) }
        findViewById<MaterialButton>(R.id.batchSftp).setOnClickListener { showSftp() }
        val privateOutput = findViewById<MaterialSwitch>(R.id.privateOutput)
        privateOutput.isChecked = getSharedPreferences("manual", Context.MODE_PRIVATE).getBoolean("private_output", false)
        privateOutput.setOnCheckedChangeListener { _, checked ->
            getSharedPreferences("manual", Context.MODE_PRIVATE).edit().putBoolean("private_output", checked).apply()
            refreshOutputs()
        }
        findViewById<MaterialButton>(R.id.privateFilesBtn).setOnClickListener { showPrivateFiles() }
        batch.state.observe(this, ::renderBatch)
        getSharedPreferences("folder_watch", Context.MODE_PRIVATE).registerOnSharedPreferenceChangeListener(watchProgressListener)
        batch.lastStatus(this)?.let(::renderBatch)
        refreshWatchProgress()
        findViewById<MaterialButton>(R.id.clearQueueBtn).setOnClickListener { queue.clear(); refreshQueue() }
        startBtn.setOnClickListener { startBatch() }
        stopBtn.setOnClickListener {
            batch.stopAfterCurrentFile()
            refreshQueue()
        }
        findViewById<MaterialButton>(R.id.batchCheckBtn).setOnClickListener { runBatchCheck() }
        setupWatch(FolderWatcher.ENCRYPT)
        setupWatch(FolderWatcher.DECRYPT)
        FolderWatcher.MODES.forEach { WeeklyWatch.migrate(this, it) }
        WatchService.update(this)
        setupSettings()
        val logsPage = findViewById<View>(R.id.activityPage)
        val jobsPage = findViewById<View>(R.id.jobsPage)
        logsPanel = LogsPanel(logsPage)
        jobsPanel = JobHistoryPanel(jobsPage)
        JobJournal.get(this).changes.observe(this) {
            if (logsPage.visibility == View.VISIBLE) refreshLogs()
            if (jobsPage.visibility == View.VISIBLE) jobsPanel.refresh()
        }
        setupNav(savedInstanceState)
        refreshQueue(); refreshOutputs(); refreshWatch(FolderWatcher.ENCRYPT); refreshWatch(FolderWatcher.DECRYPT)
        if (savedInstanceState == null) handleShareIntent(intent)
        showFirstRunSetupIfNeeded()
    }

    private fun setupNav(savedState: Bundle?) {
        val nav = findViewById<BottomNavigationView>(R.id.bottomNav)
        val toolbar = findViewById<MaterialToolbar>(R.id.toolbar)
        settingsBack = object : OnBackPressedCallback(false) {
            override fun handleOnBackPressed() = showWorkspace(nav.selectedItemId)
        }
        onBackPressedDispatcher.addCallback(this, settingsBack)
        toolbar.setNavigationOnClickListener { showWorkspace(nav.selectedItemId) }
        toolbar.setOnMenuItemClickListener { item ->
            if (item.itemId == R.id.action_settings) {
                showPage(R.id.settingsPage)
                true
            } else false
        }
        toolbar.menu.findItem(R.id.action_settings)?.icon?.setTint(ContextCompat.getColor(this, R.color.brand_on_surface))
        nav.setOnItemSelectedListener { showWorkspace(it.itemId); true }
        nav.setOnItemReselectedListener {
            if (it.itemId == R.id.nav_activity) refreshLogs()
            if (it.itemId == R.id.nav_jobs) jobsPanel.refresh()
        }
        nav.selectedItemId = savedState?.getInt(STATE_WORKSPACE, R.id.nav_batch) ?: R.id.nav_batch
        showWorkspace(nav.selectedItemId)
        if (savedState?.getBoolean(STATE_SETTINGS) == true) showPage(R.id.settingsPage)
    }

    private fun showWorkspace(destination: Int) {
        showPage(when (destination) {
            R.id.nav_watch -> R.id.watchPage
            R.id.nav_activity -> R.id.activityPage
            R.id.nav_jobs -> R.id.jobsPage
            else -> R.id.batchPage
        })
    }

    private fun showPage(page: Int) {
        val settings = page == R.id.settingsPage
        val toolbar = findViewById<MaterialToolbar>(R.id.toolbar)
        for (id in intArrayOf(R.id.batchPage, R.id.watchPage, R.id.activityPage, R.id.jobsPage, R.id.settingsPage)) {
            findViewById<View>(id).visibility = if (page == id) View.VISIBLE else View.GONE
        }
        findViewById<BottomNavigationView>(R.id.bottomNav).visibility = if (settings) View.GONE else View.VISIBLE
        settingsBack.isEnabled = settings
        toolbar.setTitle(if (settings) R.string.settings_title else R.string.app_title)
        toolbar.menu.findItem(R.id.action_settings).isVisible = !settings
        if (settings) {
            toolbar.setNavigationIcon(R.drawable.ic_arrow_back)
            toolbar.setNavigationContentDescription(R.string.settings_back_description)
        } else {
            toolbar.navigationIcon = null
        }
        if (page == R.id.activityPage) refreshLogs()
        if (page == R.id.jobsPage) jobsPanel.refresh()
        ViewCompat.requestApplyInsets(findViewById(R.id.root))
    }

    /** Leave space for the system bars and the workspace navigation. */
    private fun applyInsets() {
        val root = findViewById<View>(R.id.root)
        val nav = findViewById<BottomNavigationView>(R.id.bottomNav)
        val content = findViewById<View>(R.id.contentFrame)
        val density = resources.displayMetrics.density
        val navBase = (80 * density).toInt()
        ViewCompat.setOnApplyWindowInsetsListener(root) { _, insets ->
            val bars = insets.getInsets(WindowInsetsCompat.Type.systemBars())
            (findViewById<View>(R.id.appBar).layoutParams as? CoordinatorLayout.LayoutParams)?.let { params ->
                params.topMargin = bars.top
                findViewById<View>(R.id.appBar).layoutParams = params
            }
            nav.setPadding(nav.paddingLeft, nav.paddingTop, nav.paddingRight, bars.bottom)
            nav.layoutParams = nav.layoutParams.apply { height = navBase + bars.bottom }
            content.layoutParams = (content.layoutParams as CoordinatorLayout.LayoutParams).apply {
                bottomMargin = bars.bottom + if (nav.visibility == View.VISIBLE) navBase else 0
            }
            insets
        }
    }

    private fun refreshLogs() {
        val encrypt = if (FolderWatcher.isWatching(this, FolderWatcher.ENCRYPT)) "●  Auto-encrypt  ·  On" else "○  Auto-encrypt  ·  Off"
        val decrypt = if (FolderWatcher.isWatching(this, FolderWatcher.DECRYPT)) "●  Auto-decrypt  ·  On" else "○  Auto-decrypt  ·  Off"
        findViewById<TextView>(R.id.backgroundStatus).text = "$encrypt\n$decrypt"
        logsPanel.refresh()
    }

    private fun setupSettings() {
        fun bind(id: Int, title: Int, icon: Int, summary: String? = null, action: () -> Unit): View {
            val row = findViewById<View>(id)
            row.findViewById<TextView>(R.id.settingTitle).setText(title)
            row.findViewById<ImageView>(R.id.settingIcon).setImageResource(icon)
            row.findViewById<TextView>(R.id.settingSummary).apply {
                text = summary
                visibility = if (summary.isNullOrEmpty()) View.GONE else View.VISIBLE
            }
            row.setOnClickListener { action() }
            return row
        }

        bind(R.id.settingTheme, R.string.settings_theme, R.drawable.ic_tune, themeNames()[themeIndex()]) {
            showAppearance()
        }
        bind(R.id.permissionsBtn, R.string.settings_permissions, R.drawable.ic_shield, getString(R.string.settings_permissions_detail)) {
            showPermissionsDialog()
        }
        updateBtn = bind(R.id.updateBtn, R.string.settings_updates, R.drawable.ic_update) { checkForUpdates() }
        updateStatus = updateBtn.findViewById<TextView>(R.id.settingSummary).apply {
            accessibilityLiveRegion = View.ACCESSIBILITY_LIVE_REGION_POLITE
        }
        val version = getString(R.string.settings_version, Updater.currentVersion(this))
        bind(R.id.settingAbout, R.string.settings_about, R.drawable.ic_info, version) {
            MaterialAlertDialogBuilder(this).setTitle(R.string.app_title)
                .setMessage("$version\nPrivate, on-device image encryption.")
                .setPositiveButton(android.R.string.ok, null).show()
        }
        val source = bind(R.id.settingSource, R.string.settings_source, R.drawable.ic_code) {
            try {
                startActivity(Intent(Intent.ACTION_VIEW, Uri.parse("https://github.com/j1seki/OptiCipher-Desktop")))
            } catch (_: android.content.ActivityNotFoundException) {
                toast(getString(R.string.settings_source_unavailable))
            }
        }
        source.findViewById<ImageView>(R.id.settingIndicator).setImageResource(R.drawable.ic_open_in_new)
    }

    private val themeModes = intArrayOf(AppCompatDelegate.MODE_NIGHT_YES, AppCompatDelegate.MODE_NIGHT_NO, AppCompatDelegate.MODE_NIGHT_FOLLOW_SYSTEM)
    private fun themeNames() = arrayOf(getString(R.string.theme_dark), getString(R.string.theme_light), getString(R.string.theme_system))
    private fun themeIndex() = themeModes.indexOf(delegate.localNightMode).coerceAtLeast(0)

    private fun showAppearance() {
        val preferences = getSharedPreferences("appearance", Context.MODE_PRIVATE)
        val names = themeNames()
        MaterialAlertDialogBuilder(this).setTitle(R.string.settings_theme)
            .setSingleChoiceItems(names, themeIndex()) { dialog, index ->
                preferences.edit().putInt("theme", themeModes[index]).apply()
                findViewById<View>(R.id.settingTheme).findViewById<TextView>(R.id.settingSummary).text = names[index]
                dialog.dismiss()
                delegate.localNightMode = themeModes[index]
            }.setNegativeButton(android.R.string.cancel, null).show()
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
            } else {
                watchSwitch.isChecked = false
                FolderWatcher.clearStoredPassphrase(this, watchMode)
            }
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
            if (FolderWatcher.isWatching(this, watchMode)) {
                FolderWatcher.startWatching(this, watchMode)
                WatchService.update(this)
            }
            refreshWatch(watchMode)
        }
        watchSwitch.setOnCheckedChangeListener { _, checked ->
            if (checked) startWatch(watchMode, pass, remember, existing, watchSwitch)
            else {
                FolderWatcher.stopWatching(this, watchMode)
                WatchService.update(this)
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
            WatchService.update(this)
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
        val watching = FolderWatcher.isWatching(this, watchMode)
        findViewById<TextView>(i.status).text = if (watching) "On · $every" else "Off"
        findViewById<TextInputEditText>(i.pass).isEnabled = !watching
        findViewById<MaterialButton>(if (watchMode == FolderWatcher.ENCRYPT) R.id.encryptGenerate else R.id.decryptGenerate).isEnabled = !watching
        findViewById<MaterialButton>(if (watchMode == FolderWatcher.ENCRYPT) R.id.encryptWeekly else R.id.decryptWeekly).text = if (FolderWatcher.isWeekly(this, watchMode)) "$every · change" else "Schedule weekday and time"
    }

    private fun configureWeeklyWatch(watchMode: String) {
        val days = arrayOf("Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday")
        AlertDialog.Builder(this).setTitle("Choose a weekday").setItems(days) { _, day ->
            TimePickerDialog(this, { _, hour, minute ->
                FolderWatcher.setWeekly(this, watchMode, day + 1, hour, minute)
                findViewById<ChipGroup>(ids(watchMode).interval).clearCheck()
                if (FolderWatcher.isWatching(this, watchMode)) {
                    FolderWatcher.startWatching(this, watchMode)
                    WatchService.update(this)
                }
                refreshWatch(watchMode)
                toast("Weekly schedule set; Android may delay the scan")
            }, FolderWatcher.weeklyTime(this, watchMode).hour, FolderWatcher.weeklyTime(this, watchMode).minute,
                android.text.format.DateFormat.is24HourFormat(this)).show()
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
                if (field.id == R.id.pass) confirmInput.setText(value)
                if (field.id == R.id.encryptWatchPass && FolderWatcher.isRemembering(this, FolderWatcher.ENCRYPT)) FolderWatcher.storePassphraseIfEnabled(this, FolderWatcher.ENCRYPT, value)
                if (field.id == R.id.decryptWatchPass && FolderWatcher.isRemembering(this, FolderWatcher.DECRYPT)) FolderWatcher.storePassphraseIfEnabled(this, FolderWatcher.DECRYPT, value)
            }.setNegativeButton("Cancel", null).show()
    }

    private fun readyStatus(viewId: Int, passed: Boolean, details: String) {
        if (isFinishing || isDestroyed) return
        val status = findViewById<TextView>(viewId)
        status.text = if (passed) "✓ Ready\n$details" else "✗ Needs attention\n$details"
        val heading = if (passed) "READY" else "NOT READY"
        FolderWatcher.log(this, "$heading: ${details.replace("\n", " · ")}")
    }

    /** Fast no-file test for the manual flow: crypto roundtrip plus output-folder access. */
    private fun runBatchCheck() {
        val status = findViewById<TextView>(R.id.batchCheckStatus); status.text = "Testing batch setup…"
        val privateOutput = getSharedPreferences("manual", Context.MODE_PRIVATE).getBoolean("private_output", false)
        val pickedOutput = manualOutputUri.takeUnless { privateOutput }
        Thread {
            val findings = mutableListOf<String>()
            var ok = true
            try {
                val tiny = ImageData(byteArrayOf(10, 20, 30), 1, 1, 3)
                val roundtrip = decryptImage(encryptImage(tiny, "OptiCipher-self-test", 10_000), "OptiCipher-self-test")
                if (!roundtrip.pixels.contentEquals(tiny.pixels)) error("crypto round-trip did not match")
                findings += "✓ encryption test passed"
            } catch (e: Exception) { ok = false; findings += "✗ encryption test: ${e.message}" }
            if (pickedOutput != null) {
                val tree = DocumentFile.fromTreeUri(this, pickedOutput)
                if (tree?.canWrite() == true) findings += "✓ batch output folder writable" else { ok = false; findings += "✗ batch output folder is not writable" }
            } else if (privateOutput || getExternalFilesDir(null)?.canWrite() == true) {
                findings += if (privateOutput) "✓ private folder storage available" else "✓ app storage output available"
            } else {
                ok = false
                findings += "✗ app storage output is unavailable"
            }
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
            note(notificationsOn, "notifications enabled", "notifications are off · Background results are available in Logs")
            val batteryOk = getSystemService(android.os.PowerManager::class.java)?.isIgnoringBatteryOptimizations(packageName) != false
            note(batteryOk, "battery optimisation exemption granted", "battery optimisation may delay background checks")
            val heapMb = Runtime.getRuntime().maxMemory() / (1024 * 1024)
            findings += "✓ device processing heap: ${heapMb} MB"
            findings += "Logs reports images that exceed this device’s processing limit."
            runOnUiThread { readyStatus(i.checkStatus, ok, findings.joinToString("\n")) }
        }.start()
    }

    override fun onSaveInstanceState(outState: Bundle) {
        super.onSaveInstanceState(outState)
        outState.putString(STATE_ONBOARDING, onboardingStep?.name)
        outState.putString(STATE_PENDING_FOLDER, pendingFolderMode)
        outState.putString(STATE_PENDING_OUTPUT, pendingOutputMode)
        outState.putString(STATE_MODE, mode)
        outState.putStringArrayList(STATE_QUEUE, ArrayList(queue.map(Uri::toString)))
        outState.putInt(STATE_WORKSPACE, findViewById<BottomNavigationView>(R.id.bottomNav).selectedItemId)
        outState.putBoolean(STATE_SETTINGS, settingsBack.isEnabled)
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
    private fun actionLabel() = when (mode) {
        "encrypt" -> R.string.batch_encrypt
        "decrypt" -> R.string.batch_decrypt
        "analyze" -> R.string.batch_analyze
        else -> R.string.batch_verify
    }
    private fun refreshBatchMode() {
        val encrypt = mode == "encrypt"
        val writes = encrypt || mode == "decrypt"
        val visibility = if (encrypt) View.VISIBLE else View.GONE
        for (id in listOf(R.id.batchConfirmLayout, R.id.batchGenerate, R.id.batchKdfLabelRow, R.id.iter)) {
            findViewById<View>(id).visibility = visibility
        }
        findViewById<View>(R.id.batchSecretCard).visibility = if (mode == "analyze") View.GONE else View.VISIBLE
        findViewById<View>(R.id.batchDestinationCard).visibility = if (writes) View.VISIBLE else View.GONE
        findViewById<View>(R.id.batchSftp).visibility = if (writes) View.VISIBLE else View.GONE
        findViewById<View>(R.id.privateOutput).visibility = if (writes) View.VISIBLE else View.GONE
        findViewById<View>(R.id.privateOutputHint).visibility = if (writes) View.VISIBLE else View.GONE
        findViewById<TextInputLayout>(R.id.batchPassLayout).apply {
            hint = if (mode == "verify") "Passphrase (optional for format check)" else "Passphrase"
            error = null
        }
        findViewById<TextInputLayout>(R.id.batchConfirmLayout).error = null
    }

    private fun showSftp() {
        val old = batch.sftp
        var identity = old?.identity
        val form = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            val margin = (20 * resources.displayMetrics.density).toInt()
            setPadding(margin, 0, margin, 0)
        }
        fun field(label: String, value: String, type: Int): EditText = EditText(this).apply {
            hint = label
            contentDescription = label
            inputType = type
            setText(value)
            form.addView(this)
        }
        val address = field("sftp://user@host/folder", old?.address.orEmpty(), InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_VARIATION_URI)
        val hostKey = field("Trusted server public key", old?.hostKey.orEmpty(), InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_FLAG_NO_SUGGESTIONS)
        val password = field("SSH password or key passphrase", old?.password.orEmpty(), InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_VARIATION_PASSWORD)
        val identityButton = MaterialButton(this).apply { text = if (identity == null) "Choose SSH private key" else "Change SSH private key" }
        val usePassword = MaterialButton(this).apply { text = "Use password instead"; visibility = if (identity == null) View.GONE else View.VISIBLE }
        form.addView(identityButton)
        form.addView(usePassword)
        identityButton.setOnClickListener {
            onSftpKeyPicked = { uri ->
                identity = uri
                identityButton.text = "Change SSH private key"
                usePassword.visibility = View.VISIBLE
            }
            pickSftpKey.launch(arrayOf("*/*"))
        }
        usePassword.setOnClickListener {
            identity = null
            identityButton.text = "Choose SSH private key"
            usePassword.visibility = View.GONE
        }
        val scroll = ScrollView(this).apply { addView(form) }
        val dialog = AlertDialog.Builder(this)
            .setTitle("SFTP copy")
            .setMessage("Each result is saved locally first. Paste the server public key from a trusted source.")
            .setView(scroll)
            .setPositiveButton("Use SFTP", null)
            .setNegativeButton("Cancel", null)
            .setNeutralButton("Turn off") { _, _ -> batch.sftp = null; refreshSftpButton() }
            .create()
        dialog.setOnDismissListener { onSftpKeyPicked = null }
        dialog.show()
        dialog.getButton(AlertDialog.BUTTON_POSITIVE).setOnClickListener {
            try {
                val server = address.text.toString().trim()
                val target = SftpTarget.parse(server)
                val key = SftpProfile.parseHostKey(hostKey.text.toString())
                val secret = password.text.toString()
                require(identity != null || secret.isNotEmpty()) { "Enter a password or choose an SSH key." }
                batch.sftp = SftpProfile(target, server, key, secret, identity)
                refreshSftpButton()
                dialog.dismiss()
            } catch (error: IllegalArgumentException) {
                toast(error.message ?: "Invalid SFTP settings")
            } catch (_: java.net.URISyntaxException) {
                toast("Use sftp://user@host/folder")
            }
        }
    }

    private fun refreshSftpButton() {
        findViewById<MaterialButton>(R.id.batchSftp).text = batch.sftp?.let {
            "SFTP copy · ${it.target.host}"
        } ?: "Configure SFTP copy"
    }
    private fun refreshQueue() {
        queueView.text = if (queue.isEmpty()) "No files yet" else "${queue.size} file(s) · " + queue.take(3).joinToString(", ") { it.lastPathSegment ?: "" } + if (queue.size > 3) " +${queue.size - 3}" else ""
        val canStop = batchRunning && batch.state.value?.canStop == true
        startBtn.setText(if (batchRunning) R.string.batch_working else actionLabel())
        startBtn.isEnabled = queue.isNotEmpty() && !batchRunning
        startBtn.visibility = if (canStop) View.GONE else View.VISIBLE
        stopBtn.visibility = if (canStop) View.VISIBLE else View.GONE
        stopBtn.setText(if (batch.isStopping) R.string.batch_stopping else R.string.batch_stop_after_file)
        stopBtn.isEnabled = !batch.isStopping
        findViewById<View>(R.id.clearQueueBtn).isEnabled = queue.isNotEmpty()
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

    private fun refreshWatchProgress() {
        val p = getSharedPreferences("folder_watch", Context.MODE_PRIVATE)
        findViewById<TextView>(R.id.encryptLiveStatus).text = p.getString("encrypt_live", "")
        findViewById<TextView>(R.id.decryptLiveStatus).text = p.getString("decrypt_live", "")
    }

    override fun onDestroy() {
        getSharedPreferences("folder_watch", Context.MODE_PRIVATE).unregisterOnSharedPreferenceChangeListener(watchProgressListener)
        super.onDestroy()
    }

    private fun shareFile(file: File) {
        val uri = FileProvider.getUriForFile(this, "$packageName.provider", file)
        shareImage(uri)
    }
    private fun shareImage(uri: Uri) {
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
        updateStatus.visibility = View.VISIBLE
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
                        else -> {
                            updateStatus.text = getString(R.string.settings_update_available, release.version)
                            if (settingsBack.isEnabled) showUpdateDialog(release)
                        }
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
        val passphrase = passInput.text.toString()
        if ((mode == "encrypt" || mode == "decrypt") && passphrase.isEmpty()) {
            promptBatchField(passInput, R.id.batchPassLayout, R.string.batch_pass_required)
            return
        }
        if (mode == "encrypt" && passphrase != confirmInput.text.toString()) {
            promptBatchField(confirmInput, R.id.batchConfirmLayout, R.string.batch_pass_mismatch)
            return
        }
        if (mode == "analyze" && queue.size > 2) {
            toast("Add one or two images to analyze")
            return
        }
        ensureNotificationPermission()
        val privateOutput = getSharedPreferences("manual", Context.MODE_PRIVATE).getBoolean("private_output", false)
        val files = queue.toList()
        queue.clear()
        batch.start(applicationContext, files, mode, passphrase, iterSlider.value.toInt(), privateOutput, manualOutputUri, batch.sftp)
    }

    private fun promptBatchField(field: TextInputEditText, container: Int, message: Int) {
        findViewById<TextInputLayout>(container).error = getString(message)
        field.requestFocus()
        WindowCompat.getInsetsController(window, field).show(WindowInsetsCompat.Type.ime())
    }

    private fun renderBatch(state: BatchState) {
        batchRunning = !state.done
        refreshQueue()
        if (batchRunning) window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        else window.clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        if (renderedBatchId != state.id) {
            renderedBatchId = state.id
            results.removeAllViews()
            preview.setImageDrawable(null)
            preview.visibility = View.GONE
            renderAnalysis(null)
        }
        batchStatus.text = state.title
        batchDetail.text = state.detail
        findViewById<View>(R.id.batchFeedback).visibility = View.VISIBLE
        batchProgress.visibility = if (batchRunning) View.VISIBLE else View.GONE
        batchProgress.max = state.total.coerceAtLeast(1)
        batchProgress.progress = state.completed
        state.preview?.let {
            preview.setImageBitmap(it)
            preview.visibility = View.VISIBLE
        }
        if (state.analysis != shownAnalysis) renderAnalysis(state.analysis)
        for (item in state.results.drop(results.childCount)) {
            val row = TextView(this).apply {
                text = "${item.input}: ${item.message}"
                setPadding(0, 8, 0, 8)
            }
            if (item.output != null) row.setOnClickListener { shareImage(item.output.uri) }
            results.addView(row)
        }
    }

    private fun renderAnalysis(report: ImageAnalysis?) {
        shownAnalysis = report
        val container = findViewById<LinearLayout>(R.id.batchAnalysis)
        container.removeAllViews()
        container.visibility = if (report == null) View.GONE else View.VISIBLE
        if (report == null) return
        val labels = listOf("Red", "Green", "Blue", "Alpha").take(report.channels.size)
        val summary = TextView(this)
        val label = TextView(this).apply { text = "Histogram channel" }
        val selector = Spinner(this).apply {
            adapter = ArrayAdapter(context, android.R.layout.simple_spinner_dropdown_item, labels)
            contentDescription = "Histogram channel"
        }
        val histogram = ImageHistogram(this)
        val height = (140 * resources.displayMetrics.density).toInt()
        container.addView(label)
        container.addView(selector)
        container.addView(histogram, LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, height))
        container.addView(summary)
        selector.onItemSelectedListener = object : AdapterView.OnItemSelectedListener {
            override fun onNothingSelected(parent: AdapterView<*>?) = Unit
            override fun onItemSelected(parent: AdapterView<*>?, view: View?, position: Int, id: Long) {
                val channel = report.channels[position]
                histogram.setChannel(labels[position], position, channel.histogram)
                val mean = report.channels.map { it.entropy }.average()
                summary.text = buildString {
                    append("Mean entropy %.4f bits/byte\n".format(mean))
                    append("${labels[position]} entropy %.4f bits/byte\n".format(channel.entropy))
                    append("Correlation H %.3f  V %.3f  D %.3f".format(*channel.correlation.toTypedArray()))
                    if (report.npcr != null) append("\nNPCR %.2f%% · UACI %.2f%%".format(report.npcr, report.uaci))
                }
            }
        }
    }
    private fun toast(message: String) = Toast.makeText(this, message, Toast.LENGTH_LONG).show()
}

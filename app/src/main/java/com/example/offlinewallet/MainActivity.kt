package com.example.offlinewallet

import android.os.Bundle
import android.view.WindowManager
import androidx.activity.OnBackPressedCallback
import androidx.activity.enableEdgeToEdge
import androidx.appcompat.app.AppCompatActivity
import androidx.biometric.BiometricManager
import androidx.biometric.BiometricPrompt
import androidx.core.content.ContextCompat
import androidx.core.view.ViewCompat
import androidx.core.view.WindowInsetsCompat
import androidx.core.view.isVisible
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.lifecycleScope
import androidx.lifecycle.repeatOnLifecycle
import com.example.offlinewallet.databinding.ActivityMainBinding
import com.example.offlinewallet.ui.*
import com.google.android.material.dialog.MaterialAlertDialogBuilder
import kotlinx.coroutines.launch

class MainActivity : AppCompatActivity() {
    private lateinit var binding: ActivityMainBinding
    lateinit var viewModel: MainViewModel
        private set
    private lateinit var prompt: BiometricPrompt
    private var promptAction: String? = null
    private var setupDialog: androidx.appcompat.app.AlertDialog? = null
    private var renderingNavigation = false
    private val authenticators=BiometricManager.Authenticators.BIOMETRIC_WEAK or BiometricManager.Authenticators.DEVICE_CREDENTIAL
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        androidx.appcompat.app.AppCompatDelegate.setDefaultNightMode(androidx.appcompat.app.AppCompatDelegate.MODE_NIGHT_NO)
        enableEdgeToEdge()
        window.addFlags(WindowManager.LayoutParams.FLAG_SECURE)
        binding=ActivityMainBinding.inflate(layoutInflater)
        setContentView(binding.root)
        viewModel=ViewModelProvider(this,MainViewModel.factory(application as WalletApplication))[MainViewModel::class.java]
        promptAction=savedInstanceState?.getString("prompt-action")
        prompt=BiometricPrompt(this,ContextCompat.getMainExecutor(this),object : BiometricPrompt.AuthenticationCallback() {
            override fun onAuthenticationSucceeded(result: BiometricPrompt.AuthenticationResult) {
                val action=promptAction ?: return
                promptAction=null
                viewModel.controller.authenticatedLocally(enable=action=="enable",disable=action=="disable")
            }
            override fun onAuthenticationError(errorCode: Int, errString: CharSequence) {
                promptAction=null
                viewModel.controller.promptFailed()
            }
            override fun onAuthenticationFailed() { viewModel.controller.promptFailed() }
        })
        ViewCompat.setOnApplyWindowInsetsListener(binding.root) { view,insets ->
            val padding=insets.getInsets(WindowInsetsCompat.Type.systemBars() or WindowInsetsCompat.Type.ime())
            view.setPadding(padding.left,padding.top,padding.right,padding.bottom)
            insets
        }
        binding.navigation.setOnItemSelectedListener { item ->
            if (renderingNavigation) return@setOnItemSelectedListener true
            val screen=when(item.itemId) { R.id.nav_add_money -> Screen.ADD_MONEY; R.id.nav_profile -> Screen.PROFILE; else -> Screen.HOME }
            if (viewModel.controller.state.value.screen!=screen) viewModel.controller.navigate(screen)
            true
        }
        onBackPressedDispatcher.addCallback(this,object : OnBackPressedCallback(true) {
            override fun handleOnBackPressed() {
                val state=viewModel.controller.state.value
                if (state.locked || state.busy) return
                when(state.screen) {
                    Screen.ACTIVATION,Screen.SESSION_EXPIRED -> viewModel.controller.navigate(Screen.LOGIN)
                    Screen.HISTORY,Screen.ADD_MONEY,Screen.PROFILE -> viewModel.controller.navigate(Screen.HOME)
                    else -> moveTaskToBack(true)
                }
            }
        })
        lifecycleScope.launch { repeatOnLifecycle(Lifecycle.State.STARTED) { viewModel.controller.state.collect(::render) } }
        viewModel.controller.start()
    }
    private fun render(state: AppState) {
        binding.banner.text=state.message
        binding.banner.isVisible=state.message!=null
        binding.loading.isVisible=state.busy
        val shell= !state.locked && state.screen in listOf(Screen.HOME,Screen.ADD_MONEY,Screen.PROFILE,Screen.HISTORY)
        binding.navigation.isVisible=shell
        for (i in 0 until binding.navigation.menu.size()) binding.navigation.menu.getItem(i).isEnabled=!state.busy
        if (shell) {
            val selected=when(state.screen) { Screen.ADD_MONEY -> R.id.nav_add_money; Screen.PROFILE -> R.id.nav_profile; else -> R.id.nav_home }
            renderingNavigation=true
            try { if (binding.navigation.selectedItemId!=selected) binding.navigation.selectedItemId=selected }
            finally { renderingNavigation=false }
        }
        val tag=if(state.locked) "LOCKED" else state.screen.name
        if (supportFragmentManager.findFragmentById(R.id.destination)?.tag!=tag && !supportFragmentManager.isStateSaved) {
            val fragment=if(state.locked) StatusFragment() else when(state.screen) {
                Screen.LOGIN,Screen.ACTIVATION -> AuthFragment()
                Screen.DEVICE -> DeviceFragment()
                Screen.HOME -> HomeFragment()
                Screen.ADD_MONEY -> AddMoneyFragment()
                Screen.PROFILE -> ProfileFragment()
                Screen.HISTORY -> HistoryFragment()
                else -> StatusFragment()
            }
            supportFragmentManager.beginTransaction().replace(R.id.destination,fragment,tag).commit()
        }
        if(state.offerLock && !state.locked && !state.busy && setupDialog==null) showLockSetup()
    }
    override fun onStart() { super.onStart(); if(::viewModel.isInitialized) viewModel.controller.foreground() }
    override fun onPause() { viewModel.controller.hideBalance(); super.onPause() }
    override fun onStop() { if(!isChangingConfigurations) viewModel.controller.background(); super.onStop() }
    override fun onSaveInstanceState(outState: Bundle) { outState.putString("prompt-action",promptAction); super.onSaveInstanceState(outState) }
    fun authenticateLocally(action: String="unlock") {
        if(promptAction!=null) return
        if(BiometricManager.from(this).canAuthenticate(authenticators)!=BiometricManager.BIOMETRIC_SUCCESS) {
            MaterialAlertDialogBuilder(this).setMessage(R.string.lock_unavailable).setPositiveButton(android.R.string.ok,null).show()
            viewModel.controller.promptFailed()
            return
        }
        promptAction=action
        prompt.authenticate(BiometricPrompt.PromptInfo.Builder().setTitle(getString(R.string.unlock))
            .setSubtitle(getString(R.string.lock_setup_description)).setAllowedAuthenticators(authenticators).build())
    }
    fun showLockSetup() {
        if(setupDialog!=null) return
        setupDialog=MaterialAlertDialogBuilder(this).setTitle(R.string.set_up_lock).setMessage(R.string.lock_setup_description)
            .setPositiveButton(R.string.set_up_lock) { _,_ -> viewModel.controller.declineLock(); authenticateLocally("enable") }
            .setNegativeButton(R.string.not_now) { _,_ -> viewModel.controller.declineLock() }
            .setOnCancelListener { viewModel.controller.declineLock() }.create()
        setupDialog?.setOnDismissListener { setupDialog=null }
        setupDialog?.show()
    }
    fun manageLock() {
        if(!viewModel.controller.state.value.lockEnabled) viewModel.controller.offerLock()
        else MaterialAlertDialogBuilder(this).setTitle(R.string.manage_app_lock).setMessage(R.string.app_lock_on)
            .setPositiveButton(R.string.disable_lock) { _,_ -> authenticateLocally("disable") }.setNegativeButton(R.string.cancel,null).show()
    }
    fun confirm(message: Int, action: () -> Unit) {
        MaterialAlertDialogBuilder(this).setMessage(message).setPositiveButton(R.string.confirm) { _,_ -> action() }.setNegativeButton(R.string.cancel,null).show()
    }
}

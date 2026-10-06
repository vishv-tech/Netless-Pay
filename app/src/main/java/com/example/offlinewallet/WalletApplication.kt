package com.example.offlinewallet

import android.app.Application
import com.example.offlinewallet.data.*
import com.example.offlinewallet.data.auth.androidCredentialStore
import com.example.offlinewallet.ui.LockPreferences

open class WalletApplication : Application() {
    val repository: ParticipantRepository by lazy { createRepository() }
    val lockPreferences: LockPreferences by lazy { createLockPreferences() }
    open fun createRepository(): ParticipantRepository = ApiParticipantRepository(HttpWalletApi(BuildConfig.BACKEND_BASE_URL),
        androidCredentialStore(this), RoomWalletCache(WalletDatabase.getInstance(this).participantCacheDao()))
    open fun createLockPreferences(): LockPreferences {
        val prefs=getSharedPreferences("privacy-settings", MODE_PRIVATE)
        return object : LockPreferences {
            override var enabled: Boolean
                get()=prefs.getBoolean("app-lock-enabled",false)
                set(value) { check(prefs.edit().putBoolean("app-lock-enabled",value).commit()) }
            override var offered: Boolean
                get()=prefs.getBoolean("app-lock-offered",false)
                set(value) { check(prefs.edit().putBoolean("app-lock-offered",value).commit()) }
        }
    }
}

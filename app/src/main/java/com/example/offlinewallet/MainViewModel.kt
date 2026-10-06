package com.example.offlinewallet

import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.viewModelScope
import android.os.SystemClock
import com.example.offlinewallet.ui.AppLock
import com.example.offlinewallet.ui.WalletController

/** Local UI preferences only. Balances and payment outcomes must come from the backend. */
class MainViewModel(application: WalletApplication) : ViewModel() {
    val controller=WalletController(application.repository,AppLock(application.lockPreferences,SystemClock::elapsedRealtime),viewModelScope)
    companion object {
        fun factory(application: WalletApplication)=object : ViewModelProvider.Factory {
            @Suppress("UNCHECKED_CAST") override fun <T: ViewModel> create(modelClass: Class<T>): T = MainViewModel(application) as T
        }
    }
}

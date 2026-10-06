package com.example.offlinewallet

import android.app.Application
import android.content.Context
import androidx.test.runner.AndroidJUnitRunner
import com.example.offlinewallet.data.*
import com.example.offlinewallet.ui.LockPreferences

class WalletTestRunner : AndroidJUnitRunner() {
    override fun newApplication(cl: ClassLoader?,className: String?,context: Context?): Application =
        super.newApplication(cl,TestWalletApplication::class.java.name,context)
}
class TestWalletApplication : WalletApplication() {
    val fake=UiFakeRepository()
    val privacy=object : LockPreferences { override var enabled=false;override var offered=true }
    override fun createRepository(): ParticipantRepository=fake
    override fun createLockPreferences(): LockPreferences=privacy
}
class UiFakeRepository : ParticipantRepository {
    private val profile=ParticipantProfile("synthetic-id","Synthetic Participant","+919876543210","admin-confirmed phone","active")
    private val wallet=ConfirmedWallet(WalletSummary("synthetic-wallet",1234,0,1234,true),1000)
    var loggedIn=false
    var activations=0
    private fun result()=ParticipantSnapshot(profile,wallet,listOf(ParticipantDevice("synthetic-device",profile.participantId,"Test phone","active",1)),"synthetic-device",false,false)
    override suspend fun restore()=if(loggedIn) result() else null
    override suspend fun activate(token: String,password: String) { activations++ }
    override suspend fun login(phone: String,password: String,useDevice: Boolean): ParticipantSnapshot { loggedIn=true;return result() }
    override suspend fun register(label: String)=result()
    override suspend fun revoke() { loggedIn=false }
    override suspend fun logout(all: Boolean): Boolean { loggedIn=false;return true }
    override suspend fun clearLocal() { loggedIn=false }
    override suspend fun history(offset: Int)=HistoryPage(emptyList(),0,offset,20)
}

package com.example.offlinewallet

import com.example.offlinewallet.data.*
import com.example.offlinewallet.data.auth.*
import com.example.offlinewallet.ui.LockPreferences
import java.security.SecureRandom
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.spec.GCMParameterSpec

class TestBlob : CredentialBlob {
    var bytes: ByteArray?=null
    override fun read()=bytes?.clone()
    override fun write(bytes: ByteArray) { this.bytes=bytes.clone() }
    override fun clear() { bytes=null }
}
class TestCipher : CredentialCipher {
    private val key=KeyGenerator.getInstance("AES").apply { init(256) }.generateKey()
    override fun encrypt(plaintext: ByteArray): ByteArray {
        val nonce=ByteArray(12).also(SecureRandom()::nextBytes)
        val cipher=Cipher.getInstance("AES/GCM/NoPadding");cipher.init(Cipher.ENCRYPT_MODE,key,GCMParameterSpec(128,nonce))
        return nonce+cipher.doFinal(plaintext)
    }
    override fun decrypt(ciphertext: ByteArray): ByteArray {
        val cipher=Cipher.getInstance("AES/GCM/NoPadding");cipher.init(Cipher.DECRYPT_MODE,key,GCMParameterSpec(128,ciphertext.copyOfRange(0,12)))
        return cipher.doFinal(ciphertext.copyOfRange(12,ciphertext.size))
    }
}
class TestCache : WalletCache {
    val values=mutableMapOf<String,CachedParticipant>()
    override suspend fun load(id: String)=values[id]
    override suspend fun save(value: CachedParticipant) { values[value.profile.participantId]=value }
    override suspend fun clear() { values.clear() }
}
class TestLockPreferences(override var enabled: Boolean=false,override var offered: Boolean=true) : LockPreferences
val testProfile=ParticipantProfile("participant-a","Synthetic Participant","+919876543210","admin-confirmed phone","active")
val testSummary=WalletSummary("wallet-a",1234L,100L,1134L,true)
val testDevice=ParticipantDevice("device-a",testProfile.participantId,"Synthetic phone","active",1)
val testSnapshot=ParticipantSnapshot(testProfile,ConfirmedWallet(testSummary,1000),listOf(testDevice),testDevice.deviceId,false,false)

class FakeWalletApi : WalletApi {
    var error: Failure?=null
    var deviceStatus="active"
    var profileResult=testProfile
    var seenDevice: DeviceCredentials?=null
    var logoutAll=false
    private fun fail() { error?.let { throw WalletFailure(it) } }
    override suspend fun redeem(token: String,password: String) { fail() }
    override suspend fun login(phone: String,password: String,device: DeviceCredentials?): LoginResponse {
        fail();seenDevice=device
        return LoginResponse(profileResult.participantId,"synthetic-new-session","2099-01-01T00:00:00Z","PARTICIPANT")
    }
    override suspend fun profile(token: String): ParticipantProfile { fail();return profileResult }
    override suspend fun wallet(token: String): WalletSummary { fail();return testSummary }
    override suspend fun devices(token: String): List<ParticipantDevice> { fail();return listOf(testDevice.copy(status=deviceStatus,participantId=profileResult.participantId)) }
    override suspend fun register(token: String,label: String): DeviceEnrollmentResponse {
        fail();deviceStatus="pending"
        return DeviceEnrollmentResponse("device-a",profileResult.participantId,"synthetic-one-time-device-secret",2,"pending")
    }
    override suspend fun revoke(token: String,deviceId: String) { fail();deviceStatus="revoked" }
    override suspend fun logout(token: String,all: Boolean) { logoutAll=all;fail() }
    override suspend fun history(token: String,offset: Int): HistoryPage { fail();return HistoryPage(emptyList(),0,offset,20) }
}

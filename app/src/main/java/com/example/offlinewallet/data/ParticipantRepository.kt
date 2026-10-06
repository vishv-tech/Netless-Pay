package com.example.offlinewallet.data

import com.example.offlinewallet.data.auth.AuthRepository
import com.example.offlinewallet.data.auth.CredentialStore
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.time.Instant

data class ParticipantSnapshot(val profile: ParticipantProfile?, val wallet: ConfirmedWallet?, val devices: List<ParticipantDevice>, val deviceId: String?, val needsDevice: Boolean, val offline: Boolean, val bindingRequired: Boolean=false, val offlineCause: Failure?=null)
interface ParticipantRepository {
    suspend fun restore(): ParticipantSnapshot?
    suspend fun activate(token: String, password: String)
    suspend fun login(phone: String, password: String, useDevice: Boolean): ParticipantSnapshot
    suspend fun register(label: String): ParticipantSnapshot
    suspend fun revoke()
    suspend fun logout(all: Boolean): Boolean
    suspend fun clearLocal()
    suspend fun history(offset: Int): HistoryPage
}

/** Credentials stay in the existing encrypted store; Room is a timestamped read cache only. */
class ApiParticipantRepository(private val api: WalletApi, private val store: CredentialStore,
    private val cache: WalletCache, private val wallClock: () -> Long = System::currentTimeMillis) : ParticipantRepository {
    private val secure = AuthRepository(store)
    private suspend fun <T> storage(block: () -> T): T = withContext(Dispatchers.IO) {
        try { block() } catch (_: Exception) { throw WalletFailure(Failure.STORAGE) }
    }
    private suspend fun sessionToken(): String = storage { store.read()?.sessionToken } ?: throw WalletFailure(Failure.SESSION)
    private suspend fun invalidateSession() { storage { store.read()?.let { store.write(it.copy(sessionToken=null, sessionExpiresAt=null)) } } }
    override suspend fun restore(): ParticipantSnapshot? {
        val credentials = storage { store.read() } ?: return null
        if (credentials.sessionToken == null) return null
        val expiry = try { Instant.parse(credentials.sessionExpiresAt).toEpochMilli() } catch (_: Exception) { 0L }
        if (expiry <= wallClock()) { invalidateSession(); throw WalletFailure(Failure.SESSION) }
        val cached = cache.load(credentials.participantId)
        try {
            val profile = api.profile(credentials.sessionToken)
            if (profile.participantId != credentials.participantId || profile.status != "active") {
                invalidateSession(); throw WalletFailure(Failure.SESSION)
            }
            val devices = api.devices(credentials.sessionToken)
            val device = devices.find { it.deviceId == credentials.device?.deviceId }
            if (device?.status == "revoked") {
                storage { secure.clearOnDeviceRevocation() }; invalidateSession()
                cache.save(CachedParticipant(profile, null)); throw WalletFailure(Failure.SESSION)
            }
            var wallet: ConfirmedWallet? = null
            var needsDevice = device?.status != "active"
            var bindingRequired=false
            if (!needsDevice) {
                try { wallet = ConfirmedWallet(api.wallet(credentials.sessionToken), wallClock()) }
                catch (error: WalletFailure) { if (error.reason == Failure.DEVICE_APPROVAL) { needsDevice=true; bindingRequired=true } else throw error }
            }
            cache.save(CachedParticipant(profile, wallet))
            return ParticipantSnapshot(profile, wallet, devices, credentials.device?.deviceId, needsDevice, false,bindingRequired)
        } catch (error: WalletFailure) {
            if (error.reason == Failure.SESSION) invalidateSession()
            if (error.reason == Failure.OFFLINE || error.reason == Failure.SERVER) {
                return ParticipantSnapshot(cached?.profile, cached?.wallet, emptyList(), credentials.device?.deviceId,
                    cached?.wallet == null, true,offlineCause=error.reason)
            }
            throw error
        }
    }
    override suspend fun activate(token: String, password: String) = api.redeem(token,password)
    override suspend fun login(phone: String, password: String, useDevice: Boolean): ParticipantSnapshot {
        val previous = storage { store.read() }
        val cached = previous?.let { cache.load(it.participantId) }
        val device = if (useDevice && cached?.profile?.phone == phone) previous?.device else null
        val response = api.login(phone,password,device)
        if (response.participantId != previous?.participantId) cache.clear()
        storage { secure.acceptLogin(response) }
        return restore() ?: throw WalletFailure(Failure.SESSION)
    }
    override suspend fun register(label: String): ParticipantSnapshot {
        val credentials = storage { store.read() } ?: throw WalletFailure(Failure.SESSION)
        val token = credentials.sessionToken ?: throw WalletFailure(Failure.SESSION)
        // Invalidate old local device and cached balance before the potentially committing request.
        storage { secure.beginDeviceReplacement() }
        cache.load(credentials.participantId)?.let { cache.save(it.copy(wallet=null)) }
        val response = api.register(token,label)
        storage { secure.acceptDeviceEnrollment(response) }
        return restore() ?: throw WalletFailure(Failure.SESSION)
    }
    override suspend fun revoke() {
        val credentials = storage { store.read() } ?: throw WalletFailure(Failure.SESSION)
        val id = credentials.device?.deviceId ?: throw WalletFailure(Failure.VALIDATION)
        api.revoke(credentials.sessionToken ?: throw WalletFailure(Failure.SESSION),id)
        clearLocal()
    }
    override suspend fun logout(all: Boolean): Boolean {
        var confirmed = true
        try { storage { store.read()?.sessionToken }?.let { api.logout(it,all) } }
        catch (_: WalletFailure) { confirmed=false }
        finally { clearLocal() }
        return confirmed
    }
    override suspend fun clearLocal() {
        storage { secure.clearOnLogout() }
        cache.clear()
    }
    override suspend fun history(offset: Int): HistoryPage {
        try { return api.history(sessionToken(),offset) }
        catch (error: WalletFailure) { if (error.reason == Failure.SESSION) invalidateSession(); throw error }
    }
}

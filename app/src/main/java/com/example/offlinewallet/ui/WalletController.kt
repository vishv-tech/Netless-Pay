package com.example.offlinewallet.ui

import com.example.offlinewallet.data.*
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch

enum class Screen { STARTUP, LOGIN, ACTIVATION, DEVICE, HOME, ADD_MONEY, PROFILE, HISTORY, SESSION_EXPIRED }
data class AppState(val screen: Screen=Screen.STARTUP, val busy: Boolean=false, val message: String?=null,
    val profile: ParticipantProfile?=null, val wallet: ConfirmedWallet?=null, val devices: List<ParticipantDevice> = emptyList(),
    val deviceId: String?=null, val offline: Boolean=false, val hidden: Boolean=true, val locked: Boolean=false,
    val lockEnabled: Boolean=false, val offerLock: Boolean=false, val history: List<WalletTransaction> = emptyList(),
    val nextOffset: Int=0, val historyTotal: Int=0, val historyLoaded: Boolean=false, val bindingRequired: Boolean=false)

fun normalizeIndianPhone(input: String): String? {
    var value = input.replace(Regex("[ ()-]"), "")
    if (value.startsWith("+91")) value=value.drop(3) else if (value.length==12 && value.startsWith("91")) value=value.drop(2)
    return if (Regex("[6-9][0-9]{9}").matches(value)) "+91$value" else null
}
fun validPassword(value: String) = value.length in 12..128 && value.any { it.isLetter() } && value.any { !it.isLetter() && !it.isWhitespace() } &&
    listOf("password","qwerty","letmein","123456","offlinewallet").none { value.contains(it,true) }

class WalletController(private val repository: ParticipantRepository, private val lock: AppLock, private val scope: CoroutineScope) {
    private val mutable = MutableStateFlow(AppState(locked=lock.locked, lockEnabled=lock.enabled))
    val state = mutable.asStateFlow()
    private fun set(block: (AppState) -> AppState) { mutable.value=block(mutable.value) }
    private fun submit(operation: suspend () -> Unit) {
        if (state.value.busy || state.value.locked) return
        set { it.copy(busy=true,message=null) }
        scope.launch {
            try { operation() }
            catch (error: CancellationException) { throw error }
            catch (error: WalletFailure) { failed(error.reason) }
            catch (_: Exception) { failed(Failure.STORAGE) }
            finally { set { it.copy(busy=false) } }
        }
    }
    private fun failed(reason: Failure) {
        if (reason == Failure.SESSION) {
            set { AppState(screen=Screen.SESSION_EXPIRED, message="Your session expired, was revoked, or your account/device is unavailable. Sign in again or contact your administrator.", locked=lock.locked,lockEnabled=lock.enabled) }
        } else set { it.copy(message=when(reason) {
            Failure.OFFLINE -> "Cannot connect. Your request is unconfirmed. Retry when connected; do not assume enrollment completed."
            Failure.INVALID_LOGIN -> "Sign-in details or the saved device are unavailable. Check your details, or turn off ‘Use saved device’ to recover device enrollment."
            Failure.ENROLLMENT -> "Activation token is unavailable, expired or already used. Ask your administrator; if you already activated, sign in."
            Failure.VALIDATION -> "Check the entered details and try again."
            Failure.DEVICE_APPROVAL -> "An approved device-bound session is required. Check device enrollment."
            Failure.RATE_LIMIT -> "Too many attempts. Wait before trying again."
            Failure.CONFIGURATION -> "The backend address is not configured for this build."
            Failure.STORAGE -> "Secure local storage is unavailable. Sign in again or clear local data."
            else -> "The backend is unavailable. Your request is unconfirmed; try again later."
        }, hidden=if (it.screen==Screen.DEVICE) true else it.hidden, wallet=if (it.screen==Screen.DEVICE) null else it.wallet) }
    }
    private fun snapshot(value: ParticipantSnapshot, authenticated: Boolean=false) {
        set { it.copy(screen=if(value.needsDevice) Screen.DEVICE else Screen.HOME, profile=value.profile,wallet=value.wallet,
            devices=value.devices,deviceId=value.deviceId,offline=value.offline,hidden=true,
            history=emptyList(),nextOffset=0,historyTotal=0,historyLoaded=false,
            message=if(value.offline) (if(value.offlineCause==Failure.SERVER) "Backend unavailable" else "Offline") + " — session and device status cannot be checked. Showing only last-confirmed data." else null,
            bindingRequired=value.bindingRequired,
            offerLock=authenticated && lock.shouldOffer()) }
    }
    fun start() { if (state.value.screen==Screen.STARTUP && !state.value.locked) refresh() }
    fun refresh() = submit {
        val value = repository.restore()
        if (value==null) set { it.copy(screen=Screen.LOGIN,profile=null,wallet=null,devices=emptyList(),history=emptyList()) }
        else snapshot(value)
    }
    fun activate(token: String,password: String,confirmation: String) {
        if (token.isBlank() || token.length>128 || !validPassword(password) || password!=confirmation) {
            set { it.copy(message="Enter your administrator token and matching passwords: 12–128 characters with a letter and digit or symbol, without common patterns.") }; return
        }
        submit { repository.activate(token.trim(),password); set { it.copy(screen=Screen.LOGIN,message="Account activated. Sign in with your admin-confirmed phone number.",offerLock=lock.shouldOffer()) } }
    }
    fun login(phone: String,password: String,useDevice: Boolean) {
        val normalized=normalizeIndianPhone(phone)
        if (normalized==null || password.isEmpty() || password.length>128) { set { it.copy(message="Enter a valid Indian mobile number and password.") }; return }
        submit { snapshot(repository.login(normalized!!,password,useDevice),authenticated=true) }
    }
    fun register(label: String) {
        if (label.isBlank() || label.length>80) { set { it.copy(message="Enter a device label up to 80 characters.") }; return }
        submit { set { it.copy(wallet=null,hidden=true,deviceId=null,devices=emptyList()) }; snapshot(repository.register(label.trim())) }
    }
    fun revoke() = submit { repository.revoke(); set { AppState(screen=Screen.SESSION_EXPIRED,message="Device revoked by the backend. Local credentials cleared.",locked=lock.locked,lockEnabled=lock.enabled) } }
    fun logout(all: Boolean=false) = submit {
        val confirmed=repository.logout(all)
        set { AppState(screen=Screen.LOGIN,locked=lock.locked,lockEnabled=lock.enabled,message=if(confirmed) "Signed out." else "Local credentials cleared. Server sign-out could not be confirmed; sessions may remain until expiry.") }
    }
    fun navigate(screen: Screen) {
        if (state.value.busy || state.value.locked) return
        val protected = screen in listOf(Screen.HOME,Screen.PROFILE,Screen.ADD_MONEY,Screen.HISTORY,Screen.DEVICE)
        if (protected && state.value.screen in listOf(Screen.LOGIN,Screen.ACTIVATION,Screen.SESSION_EXPIRED,Screen.STARTUP)) return
        set { it.copy(screen=screen,message=if(it.offline) "Offline — showing last-confirmed data only." else null, hidden=if(screen==Screen.HOME) true else it.hidden) }
        if (screen==Screen.HISTORY && !state.value.historyLoaded) loadHistory()
    }
    fun loadHistory() = submit {
        if (state.value.offline) throw WalletFailure(Failure.OFFLINE)
        val page=repository.history(state.value.nextOffset)
        set { it.copy(history=(it.history+page.items).distinctBy { row -> row.id },nextOffset=page.offset+page.items.size,
            historyTotal=page.total,historyLoaded=true) }
    }
    fun toggleBalance() { if (!state.value.locked && state.value.wallet!=null) set { it.copy(hidden=!it.hidden) } }
    fun hideBalance() = set { it.copy(hidden=true) }
    fun background() { hideBalance(); lock.background() }
    fun foreground() { lock.foreground(); set { it.copy(locked=lock.locked,lockEnabled=lock.enabled) }; start() }
    fun lockNow() { hideBalance(); lock.lock(); set { it.copy(locked=lock.locked,offerLock=!lock.enabled,lockEnabled=lock.enabled) } }
    fun offerLock() = set { it.copy(offerLock=true) }
    fun declineLock() { lock.decline(); set { it.copy(offerLock=false) } }
    fun authenticatedLocally(enable: Boolean=false,disable: Boolean=false) {
        if (disable) lock.disableAfterAuthentication() else lock.authenticated(enable)
        set { it.copy(locked=false,lockEnabled=lock.enabled,offerLock=false,hidden=true,message=null) }
        // Local unlock never creates a server session; restore revalidates it online when possible.
        if (!state.value.busy) refresh()
    }
    fun promptFailed() = set { it.copy(message="Unlock cancelled or unavailable. Use Unlock to try again.") }
    fun eraseLockedData() {
        if (state.value.busy) return
        set { it.copy(busy=true) }
        scope.launch {
            try { repository.clearLocal(); lock.clearAfterErasingLocalData(); set { AppState(screen=Screen.LOGIN,message="Local data cleared. Existing server sessions may remain until expiry.") } }
            catch (error: CancellationException) { throw error }
            catch (_: Exception) { set { it.copy(busy=false,message="Could not clear local data. Unlock remains required.") } }
        }
    }
}

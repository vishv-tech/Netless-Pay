package com.example.offlinewallet

import com.example.offlinewallet.data.*
import com.example.offlinewallet.ui.*
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.test.*
import org.junit.Assert.*
import org.junit.Test

@OptIn(kotlinx.coroutines.ExperimentalCoroutinesApi::class)
class ControllerTest {
    private class Repo : ParticipantRepository {
        var snapshot: ParticipantSnapshot?=testSnapshot
        var error: Failure?=null
        var activations=0;var logins=0;var registrations=0;var clears=0;var logoutConfirmed=true
        var gate: CompletableDeferred<Unit>?=null
        val historyOffsets=mutableListOf<Int>()
        private fun fail() { error?.let { throw WalletFailure(it) } }
        override suspend fun restore(): ParticipantSnapshot? { fail();return snapshot }
        override suspend fun activate(token: String,password: String) { activations++;gate?.await();fail() }
        override suspend fun login(phone: String,password: String,useDevice: Boolean): ParticipantSnapshot { logins++;gate?.await();fail();return snapshot!! }
        override suspend fun register(label: String): ParticipantSnapshot { registrations++;fail();return testSnapshot.copy(wallet=null,needsDevice=true,devices=listOf(testDevice.copy(status="pending"))) }
        override suspend fun revoke() { fail();clears++ }
        override suspend fun logout(all: Boolean): Boolean { clears++;return logoutConfirmed }
        override suspend fun clearLocal() { clears++ }
        override suspend fun history(offset: Int): HistoryPage { fail();historyOffsets+=offset
            val items=(offset until minOf(offset+2,3)).map { WalletTransaction("tx-$it","funding",100,100,0,"2026-10-06T12:00:00Z") }
            return HistoryPage(items,3,offset,2)
        }
    }
    private fun controller(repo: Repo,scope: kotlinx.coroutines.CoroutineScope,prefs: TestLockPreferences=TestLockPreferences(),elapsed: () -> Long={0L}) = WalletController(repo,AppLock(prefs,elapsed),scope)
    @Test fun activationValidationPreventsNetworkRequest()=runTest {
        val repo=Repo();val c=controller(repo,this)
        c.activate("","weak","different");advanceUntilIdle()
        assertEquals(0,repo.activations);assertNotNull(c.state.value.message)
    }
    @Test fun activationWaitsForBackendBeforeSuccess()=runTest {
        val repo=Repo();repo.gate=CompletableDeferred();val c=controller(repo,this)
        c.navigate(Screen.ACTIVATION);c.activate("synthetic-token","Synthetic-river-7-stones","Synthetic-river-7-stones");runCurrent()
        assertTrue(c.state.value.busy);assertEquals(Screen.ACTIVATION,c.state.value.screen)
        repo.gate!!.complete(Unit);advanceUntilIdle();assertEquals(Screen.LOGIN,c.state.value.screen)
    }
    @Test fun activationFailureKeepsActivationScreen()=runTest {
        val repo=Repo();repo.error=Failure.ENROLLMENT;val c=controller(repo,this)
        c.navigate(Screen.ACTIVATION);c.activate("token","Synthetic-river-7-stones","Synthetic-river-7-stones");advanceUntilIdle()
        assertEquals(Screen.ACTIVATION,c.state.value.screen);assertFalse(c.state.value.busy)
    }
    @Test fun validLoginOpensHomeWithBalanceHidden()=runTest {
        val repo=Repo();val c=controller(repo,this);c.login("9876543210","valid",true);advanceUntilIdle()
        assertEquals(Screen.HOME,c.state.value.screen);assertTrue(c.state.value.hidden)
    }
    @Test fun failedLoginCannotShowHome()=runTest {
        val repo=Repo();repo.error=Failure.INVALID_LOGIN;val c=controller(repo,this)
        c.navigate(Screen.LOGIN);c.login("9876543210","bad",true);advanceUntilIdle()
        assertEquals(Screen.LOGIN,c.state.value.screen);assertNull(c.state.value.wallet)
    }
    @Test fun invalidPhonePreventsLogin()=runTest { val r=Repo();val c=controller(r,this);c.login("123","valid",true);assertEquals(0,r.logins) }
    @Test fun restoresSessionWithoutCreatingLogin()=runTest {
        val r=Repo();val c=controller(r,this);c.start();advanceUntilIdle();assertEquals(Screen.HOME,c.state.value.screen);assertEquals(0,r.logins)
    }
    @Test fun missingSessionOpensLogin()=runTest { val r=Repo();r.snapshot=null;val c=controller(r,this);c.start();advanceUntilIdle();assertEquals(Screen.LOGIN,c.state.value.screen) }
    @Test fun expiredOrRevokedSessionRemovesWalletFromUi()=runTest {
        val r=Repo();val c=controller(r,this);c.start();advanceUntilIdle();r.error=Failure.SESSION;c.refresh();advanceUntilIdle()
        assertEquals(Screen.SESSION_EXPIRED,c.state.value.screen);assertNull(c.state.value.wallet);assertNull(c.state.value.profile)
    }
    @Test fun offlineRestorationLabelsLastConfirmedData()=runTest {
        val r=Repo();r.snapshot=testSnapshot.copy(offline=true);val c=controller(r,this);c.start();advanceUntilIdle()
        assertTrue(c.state.value.offline);assertTrue(c.state.value.message!!.contains("last-confirmed"));assertEquals(1000L,c.state.value.wallet!!.confirmedAt)
    }
    @Test fun registerShowsPendingUntilAdministratorApproval()=runTest {
        val r=Repo();val c=controller(r,this);c.start();advanceUntilIdle();c.navigate(Screen.DEVICE);c.register("Phone");advanceUntilIdle()
        assertEquals(Screen.DEVICE,c.state.value.screen);assertNull(c.state.value.wallet)
    }
    @Test fun revokeRequiresBackendConfirmation()=runTest {
        val r=Repo();val c=controller(r,this);c.start();advanceUntilIdle();c.revoke();advanceUntilIdle()
        assertEquals(Screen.SESSION_EXPIRED,c.state.value.screen);assertEquals(1,r.clears)
    }
    @Test fun balanceRevealHideAndBackground()=runTest {
        val c=controller(Repo(),this);c.start();advanceUntilIdle();assertTrue(c.state.value.hidden)
        c.toggleBalance();assertFalse(c.state.value.hidden);c.toggleBalance();assertTrue(c.state.value.hidden)
        c.toggleBalance();c.background();assertTrue(c.state.value.hidden)
    }
    @Test fun immediateLockHidesBalanceAndCannotNavigate()=runTest {
        val prefs=TestLockPreferences(true);val c=controller(Repo(),this,prefs)
        c.authenticatedLocally();advanceUntilIdle();c.toggleBalance();c.lockNow();assertTrue(c.state.value.locked);assertTrue(c.state.value.hidden)
        c.navigate(Screen.PROFILE);assertEquals(Screen.HOME,c.state.value.screen)
    }
    @Test fun homeLockWhenDisabledOffersSetup()=runTest { val c=controller(Repo(),this);c.lockNow();assertFalse(c.state.value.locked);assertTrue(c.state.value.offerLock) }
    @Test fun coldLaunchIsLockedAndNoBackendCallsOccurUntilUnlock()=runTest {
        val c=controller(Repo(),this,TestLockPreferences(true));c.start();advanceUntilIdle();assertEquals(Screen.STARTUP,c.state.value.screen);assertTrue(c.state.value.locked)
    }
    @Test fun cancelledPromptCannotBypassLock()=runTest {
        val c=controller(Repo(),this,TestLockPreferences(true));c.promptFailed();assertTrue(c.state.value.locked)
    }
    @Test fun localUnlockDoesNotCreateBackendSession()=runTest {
        val r=Repo();r.snapshot=null;val c=controller(r,this,TestLockPreferences(true));c.authenticatedLocally();advanceUntilIdle()
        assertEquals(Screen.LOGIN,c.state.value.screen);assertEquals(0,r.logins)
    }
    @Test fun backgroundTimeoutLocksAtThirtySeconds()=runTest {
        var time=0L;val c=controller(Repo(),this,TestLockPreferences(true)) { time }
        c.authenticatedLocally();advanceUntilIdle();c.background();time=29999;c.foreground();assertFalse(c.state.value.locked)
        c.background();time+=30000;c.foreground();assertTrue(c.state.value.locked)
    }
    @Test fun logoutClearsUiAndUnconfirmedMessageIsHonest()=runTest {
        val r=Repo();r.logoutConfirmed=false;val c=controller(r,this);c.start();advanceUntilIdle();c.logout();advanceUntilIdle()
        assertEquals(Screen.LOGIN,c.state.value.screen);assertNull(c.state.value.wallet);assertTrue(c.state.value.message!!.contains("could not be confirmed"))
    }
    @Test fun paginationUsesServerOffsetAndAppendsUniqueEntries()=runTest {
        val r=Repo();val c=controller(r,this);c.start();advanceUntilIdle();c.navigate(Screen.HISTORY);advanceUntilIdle();c.loadHistory();advanceUntilIdle()
        assertEquals(listOf(0,2),r.historyOffsets);assertEquals(3,c.state.value.history.size);assertEquals(3,c.state.value.nextOffset)
    }
    @Test fun repeatedSubmitCreatesOnlyOneLoginRequest()=runTest {
        val r=Repo();r.gate=CompletableDeferred();val c=controller(r,this)
        repeat(5) { c.login("9876543210","valid",true) };runCurrent();assertEquals(1,r.logins)
        r.gate!!.complete(Unit);advanceUntilIdle();assertFalse(c.state.value.busy)
    }
    @Test fun passwordPolicyAndPhoneNormalizationMatchBackend() {
        assertEquals("+919876543210",normalizeIndianPhone("+91 (98765) 43210"))
        assertFalse(validPassword("myPassword-long-99"));assertTrue(validPassword("Synthetic-river-7-stones"))
    }
    @Test fun paiseFormattingUsesIntegersIncludingExtremeValues() {
        assertEquals("₹0.00",rupees(0));assertEquals("₹0.01",rupees(1));assertEquals("₹1,234.56",rupees(123456))
        assertEquals("−₹0.01",rupees(-1));assertEquals("−₹92,23,37,20,36,85,47,758.08",rupees(Long.MIN_VALUE))
    }
    @Test fun processRecreationAlwaysRequiresLocalUnlockWhenEnabled() {
        val prefs=TestLockPreferences(true);val original=AppLock(prefs) {0};original.authenticated();assertFalse(original.locked)
        assertTrue(AppLock(prefs) {0}.locked)
    }
    @Test fun immediateLockSurvivesAnInFlightNetworkResponse()=runTest {
        val repo=Repo();val c=controller(repo,this,TestLockPreferences(true))
        c.authenticatedLocally();advanceUntilIdle()
        repo.gate=CompletableDeferred();c.login("9876543210","synthetic",true);runCurrent()
        c.lockNow();assertTrue(c.state.value.locked)
        repo.gate!!.complete(Unit);advanceUntilIdle()
        assertTrue(c.state.value.locked);assertTrue(c.state.value.hidden)
    }
}

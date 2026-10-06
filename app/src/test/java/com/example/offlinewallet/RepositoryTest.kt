package com.example.offlinewallet

import com.example.offlinewallet.data.*
import com.example.offlinewallet.data.auth.*
import kotlinx.coroutines.test.runTest
import org.junit.Assert.*
import org.junit.Test

class RepositoryTest {
    private val blob=TestBlob()
    private val store=CredentialStore(blob,TestCipher())
    private val cache=TestCache()
    private val api=FakeWalletApi()
    private val repo=ApiParticipantRepository(api,store,cache) { 2000L }
    private suspend fun seed(expiry: String="2099-01-01T00:00:00Z") {
        store.write(Credentials(testProfile.participantId,"synthetic-session",expiry,DeviceCredentials("device-a","synthetic-device-secret",1)))
        cache.save(CachedParticipant(testProfile,ConfirmedWallet(testSummary,1000L)))
    }
    @Test fun restoresSessionAndConfirmsWallet()=runTest {
        seed();val result=repo.restore()!!
        assertFalse(result.offline);assertFalse(result.needsDevice);assertEquals(2000L,result.wallet!!.confirmedAt)
        assertEquals(1234L,result.wallet!!.summary.balancePaise)
    }
    @Test fun missingSessionRoutesToLogin()=runTest { assertNull(repo.restore()) }
    @Test fun expiredSessionRemovesTokenButKeepsDeviceForLogin()=runTest {
        seed("1970-01-01T00:00:01Z")
        try { repo.restore();fail() } catch(error: WalletFailure) { assertEquals(Failure.SESSION,error.reason) }
        assertNull(store.read()!!.sessionToken);assertNotNull(store.read()!!.device)
    }
    @Test fun revokedSessionRemovesToken()=runTest {
        seed();api.error=Failure.SESSION
        try { repo.restore();fail() } catch(error: WalletFailure) { assertEquals(Failure.SESSION,error.reason) }
        assertNull(store.read()!!.sessionToken)
    }
    @Test fun offlineRetainsPotentiallyValidSessionAndTimestamp()=runTest {
        seed();api.error=Failure.OFFLINE;val result=repo.restore()!!
        assertTrue(result.offline);assertEquals(1000L,result.wallet!!.confirmedAt)
        assertEquals("synthetic-session",store.read()!!.sessionToken)
    }
    @Test fun serverFailureUsesHonestCachedState()=runTest {
        seed();api.error=Failure.SERVER;val result=repo.restore()!!
        assertTrue(result.offline);assertEquals(Failure.SERVER,result.offlineCause)
        assertEquals(1000L,result.wallet!!.confirmedAt)
    }
    @Test fun pendingDeviceCannotReadWallet()=runTest {
        seed();api.deviceStatus="pending";val result=repo.restore()!!
        assertTrue(result.needsDevice);assertNull(result.wallet)
        assertNull(cache.load(testProfile.participantId)!!.wallet)
    }
    @Test fun revokedDeviceClearsItsSecret()=runTest {
        seed();api.deviceStatus="revoked"
        try { repo.restore();fail() } catch(error: WalletFailure) { assertEquals(Failure.SESSION,error.reason) }
        assertNull(store.read()!!.device);assertNull(store.read()!!.sessionToken)
    }
    @Test fun loginBindsMatchingParticipantDevice()=runTest {
        seed();repo.login(testProfile.phone,"synthetic-password",true)
        assertEquals("device-a",api.seenDevice!!.deviceId)
    }
    @Test fun anotherParticipantNeverReceivesPreviousDeviceOrCache()=runTest {
        seed();api.profileResult=testProfile.copy(participantId="participant-b",phone="+918765432109")
        repo.login(api.profileResult.phone,"synthetic-password",true)
        assertNull(api.seenDevice);assertNull(store.read()!!.device)
        assertNull(cache.load(testProfile.participantId))
    }
    @Test fun enrollmentStoresSecretEncryptedOnceAndPending()=runTest {
        seed();val result=repo.register("New phone")
        assertTrue(result.needsDevice);assertNull(result.wallet)
        assertEquals("synthetic-one-time-device-secret",store.read()!!.device!!.secret)
        assertFalse(String(blob.bytes!!).contains("synthetic-one-time-device-secret"))
        assertFalse(result.toString().contains("synthetic-one-time-device-secret"))
    }
    @Test fun lostReplacementResponseClearsOldCredentialAndBalance()=runTest {
        seed();api.error=Failure.OFFLINE
        try { repo.register("New phone");fail() } catch(error: WalletFailure) { assertEquals(Failure.OFFLINE,error.reason) }
        assertNull(store.read()!!.device);assertNull(cache.load(testProfile.participantId)!!.wallet)
        assertNotNull(store.read()!!.sessionToken)
    }
    @Test fun confirmedRevocationClearsCredentialsAndCache()=runTest {
        seed();repo.revoke();assertNull(store.read());assertTrue(cache.values.isEmpty())
    }
    @Test fun failedRevocationDoesNotClaimSuccessOrEraseSession()=runTest {
        seed();api.error=Failure.OFFLINE
        try { repo.revoke();fail() } catch(error: WalletFailure) { assertEquals(Failure.OFFLINE,error.reason) }
        assertNotNull(store.read()!!.device);assertNotNull(store.read()!!.sessionToken)
    }
    @Test fun offlineLogoutClearsLocalCredentialsAndReportsUnconfirmed()=runTest {
        seed();api.error=Failure.OFFLINE;assertFalse(repo.logout(true))
        assertTrue(api.logoutAll);assertNull(store.read());assertTrue(cache.values.isEmpty())
    }
    @Test fun confirmedLogoutClearsBothCredentials()=runTest { seed();assertTrue(repo.logout(false));assertNull(store.read()) }
    @Test fun cacheRequiresMatchingParticipantIdentity()=runTest {
        seed();store.write(store.read()!!.copy(participantId="missing"));api.error=Failure.OFFLINE
        val result=repo.restore()!!;assertNull(result.wallet);assertNull(result.profile)
    }
}

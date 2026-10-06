package com.example.offlinewallet

import com.example.offlinewallet.data.*
import com.example.offlinewallet.data.auth.DeviceCredentials
import kotlinx.coroutines.test.runTest
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.json.JSONObject
import org.junit.After
import org.junit.Assert.*
import org.junit.Before
import org.junit.Test

class HttpWalletApiTest {
    private lateinit var server: MockWebServer
    private lateinit var api: HttpWalletApi
    @Before fun setUp() { server=MockWebServer();server.start();api=HttpWalletApi(server.url("/").toString()) }
    @After fun tearDown() { server.shutdown() }
    private fun response(body: String,code: Int=200) { server.enqueue(MockResponse().setResponseCode(code).setHeader("Content-Type","application/json").setBody(body)) }
    @Test fun activationUsesSprintTwoSchemaAndWaitsFor204()=runTest {
        response("",204);api.redeem("synthetic-token","Synthetic-river-7-stones")
        val request=server.takeRequest();assertEquals("/api/v1/auth/redeem",request.path)
        val body=JSONObject(request.body.readUtf8());assertEquals(setOf("enrollment_token","password"),body.keys().asSequence().toSet())
        assertNull(request.getHeader("Authorization"))
    }
    @Test fun loginUsesActualNamesAndNeverAttachesSession()=runTest {
        response("""{"participant_id":"participant-a","session_token":"synthetic-session","expires_at":"2099-01-01T00:00:00Z","role":"PARTICIPANT"}""")
        val result=api.login("+919876543210","synthetic-password",DeviceCredentials("device-id","synthetic-secret",1))
        assertEquals("participant-a",result.participantId)
        val request=server.takeRequest();assertEquals("/api/v1/auth/login",request.path);assertNull(request.getHeader("Authorization"))
        val body=JSONObject(request.body.readUtf8());assertEquals("device-id",body.getString("device_id"));assertEquals("synthetic-secret",body.getString("device_secret"))
        assertFalse(result.toString().contains("synthetic-session"))
    }
    @Test fun profileIsSessionValidationWithBearer()=runTest {
        response("""{"participant_id":"participant-a","name":"Synthetic","phone":"+919876543210","phone_confirmation":"admin-confirmed phone","status":"active"}""")
        assertEquals("admin-confirmed phone",api.profile("synthetic-session").phoneConfirmation)
        val request=server.takeRequest();assertEquals("/api/v1/me",request.path);assertEquals("Bearer synthetic-session",request.getHeader("Authorization"))
    }
    @Test fun walletIsLedgerConfirmedWithIntegerPaise()=runTest {
        response("""{"wallet_id":"wallet-a","balance_paise":1234,"held_paise":100,"available_paise":1134,"enabled":true,"source":"confirmed-ledger"}""")
        assertEquals(1234L,api.wallet("synthetic-session").balancePaise)
    }
    @Test fun fractionalMoneyIsRejected()=runTest {
        response("""{"wallet_id":"wallet-a","balance_paise":12.34,"held_paise":0,"available_paise":12.34,"enabled":true,"source":"confirmed-ledger"}""")
        try { api.wallet("synthetic-session");fail() } catch(error: WalletFailure) { assertEquals(Failure.SERVER,error.reason) }
    }
    @Test fun transactionHistoryUsesServerPagination()=runTest {
        response("""{"items":[{"transaction_id":"tx-1","kind":"transfer","amount_paise":100,"balance_delta_paise":-100,"held_delta_paise":0,"created_at":"2026-10-06T12:00:00Z"}],"total":21,"limit":20,"offset":20}""")
        val page=api.history("synthetic-session",20)
        assertEquals(20,page.offset);assertEquals(-100L,page.items.single().balanceDeltaPaise)
        assertEquals("/api/v1/me/transactions?limit=20&offset=20",server.takeRequest().path)
    }
    @Test fun deviceRegistrationMapsOneTimeSecret()=runTest {
        response("""{"device_id":"device-a","participant_id":"participant-a","label":"Phone","status":"pending","secret_version":2,"device_secret":"synthetic-device-secret"}""",201)
        val device=api.register("synthetic-session","Phone");assertEquals("pending",device.status)
        assertFalse(device.toString().contains("synthetic-device-secret"))
        assertEquals("Phone",JSONObject(server.takeRequest().body.readUtf8()).getString("label"))
    }
    @Test fun deviceListCannotReturnSecretInModel()=runTest {
        response("""{"items":[{"device_id":"device-a","participant_id":"participant-a","label":"Phone","status":"revoked","secret_version":1}],"total":1,"limit":100,"offset":0}""")
        assertEquals("revoked",api.devices("synthetic-session").single().status)
        assertEquals("/api/v1/me/devices?limit=100&offset=0",server.takeRequest().path)
    }
    @Test fun revokeAndLogoutUseCorrectMethodsAndPaths()=runTest {
        response("{}");api.revoke("synthetic-session","device-a");assertEquals("DELETE",server.takeRequest().method)
        response("",204);api.logout("synthetic-session",true);val request=server.takeRequest()
        assertEquals("POST",request.method);assertEquals("/api/v1/auth/logout-all",request.path)
    }
    @Test fun repositoryErrorMappingIsContextSpecific() {
        assertEquals(Failure.INVALID_LOGIN,failureFor(401,"auth/login"))
        assertEquals(Failure.SESSION,failureFor(401,"me/wallet"))
        assertEquals(Failure.DEVICE_APPROVAL,failureFor(403,"me/wallet"))
        assertEquals(Failure.ENROLLMENT,failureFor(400,"auth/redeem"))
        assertEquals(Failure.VALIDATION,failureFor(422,"auth/redeem"))
        assertEquals(Failure.RATE_LIMIT,failureFor(429,"auth/login"))
        assertEquals(Failure.SERVER,failureFor(503,"me"))
    }
    @Test fun sensitiveFailureBodyIsDiscarded()=runTest {
        response("""{"detail":"synthetic-sensitive-body"}""",401)
        try { api.profile("synthetic-session");fail() } catch(error: WalletFailure) {
            assertEquals(Failure.SESSION,error.reason);assertFalse(error.toString().contains("synthetic-sensitive-body"))
        }
    }
    @Test fun redirectCannotForwardCredentials()=runTest {
        server.enqueue(MockResponse().setResponseCode(302).setHeader("Location",server.url("/unexpected")))
        try { api.profile("synthetic-session");fail() } catch(error: WalletFailure) { assertEquals(Failure.SERVER,error.reason) }
        assertEquals(1,server.requestCount)
    }
}

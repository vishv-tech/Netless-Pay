package com.example.offlinewallet.data

import com.example.offlinewallet.data.auth.DeviceCredentials
import com.example.offlinewallet.data.auth.DeviceEnrollmentResponse
import com.example.offlinewallet.data.auth.LoginResponse
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.withContext
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import okhttp3.HttpUrl.Companion.toHttpUrlOrNull
import org.json.JSONObject
import java.io.IOException
import java.util.concurrent.TimeUnit

interface WalletApi {
    suspend fun redeem(token: String, password: String)
    suspend fun login(phone: String, password: String, device: DeviceCredentials?): LoginResponse
    suspend fun profile(token: String): ParticipantProfile
    suspend fun wallet(token: String): WalletSummary
    suspend fun devices(token: String): List<ParticipantDevice>
    suspend fun register(token: String, label: String): DeviceEnrollmentResponse
    suspend fun revoke(token: String, deviceId: String)
    suspend fun logout(token: String, all: Boolean)
    suspend fun history(token: String, offset: Int): HistoryPage
}

/** No redirects, body/token logging, automatic mutation retry, or custom TLS trust manager. */
class HttpWalletApi(baseUrl: String, private val client: OkHttpClient = OkHttpClient.Builder()
    .connectTimeout(10, TimeUnit.SECONDS).readTimeout(15, TimeUnit.SECONDS).writeTimeout(15, TimeUnit.SECONDS)
    .callTimeout(25, TimeUnit.SECONDS).retryOnConnectionFailure(false).followRedirects(false).followSslRedirects(false).build()) : WalletApi {
    private val base = baseUrl.toHttpUrlOrNull()?.takeIf { it.username.isEmpty() && it.password.isEmpty() && it.query == null && it.fragment == null }
    private suspend fun call(path: String, token: String? = null, body: JSONObject? = null, method: String = if (body == null) "GET" else "POST"): JSONObject = withContext(Dispatchers.IO) {
        val url = base?.resolve("api/v1/$path") ?: throw WalletFailure(Failure.CONFIGURATION)
        val request = Request.Builder().url(url).header("Accept", "application/json").header("Cache-Control", "no-store")
        token?.let { request.header("Authorization", "Bearer $it") }
        request.method(method, if (method == "POST") (body?.toString() ?: "").toRequestBody("application/json".toMediaType()) else null)
        try {
            client.newCall(request.build()).execute().use { response ->
                if (!response.isSuccessful) throw WalletFailure(failureFor(response.code, path.substringBefore('?')))
                if (response.code == 204) JSONObject() else {
                    val text = response.body?.string() ?: throw WalletFailure(Failure.SERVER)
                    try { JSONObject(text) } catch (_: Exception) { throw WalletFailure(Failure.SERVER) }
                }
            }
        } catch (_: IOException) { throw WalletFailure(Failure.OFFLINE) }
    }
    private suspend fun <T> parse(block: suspend () -> T): T = try { block() } catch (error: CancellationException) { throw error } catch (error: WalletFailure) { throw error } catch (_: Exception) { throw WalletFailure(Failure.SERVER) }
    private fun money(json: JSONObject, field: String): Long {
        val value = json.get(field)
        if (value !is Int && value !is Long) throw WalletFailure(Failure.SERVER)
        return (value as Number).toLong()
    }
    override suspend fun redeem(token: String, password: String) { call("auth/redeem", body=JSONObject().put("enrollment_token", token).put("password", password)) }
    override suspend fun login(phone: String, password: String, device: DeviceCredentials?): LoginResponse = parse {
        val body = JSONObject().put("phone", phone).put("password", password)
        device?.let { body.put("device_id", it.deviceId).put("device_secret", it.secret) }
        val json = call("auth/login", body=body)
        LoginResponse(json.getString("participant_id"), json.getString("session_token"), json.getString("expires_at"), json.getString("role"))
    }
    override suspend fun profile(token: String): ParticipantProfile = parse {
        val j = call("me", token)
        ParticipantProfile(j.getString("participant_id"), j.getString("name"), j.getString("phone"), j.getString("phone_confirmation"), j.getString("status"))
    }
    override suspend fun wallet(token: String): WalletSummary = parse {
        val j = call("me/wallet", token)
        if (j.getString("source") != "confirmed-ledger") throw WalletFailure(Failure.SERVER)
        WalletSummary(j.getString("wallet_id"), money(j,"balance_paise"), money(j,"held_paise"), money(j,"available_paise"), j.getBoolean("enabled"))
    }
    override suspend fun devices(token: String): List<ParticipantDevice> = parse {
        val list = call("me/devices?limit=100&offset=0", token).getJSONArray("items")
        (0 until list.length()).map { index -> val j = list.getJSONObject(index)
            ParticipantDevice(j.getString("device_id"), j.getString("participant_id"), j.getString("label"), j.getString("status"), j.getInt("secret_version")) }
    }
    override suspend fun register(token: String, label: String): DeviceEnrollmentResponse = parse {
        val j = call("me/devices", token, JSONObject().put("label", label))
        DeviceEnrollmentResponse(j.getString("device_id"), j.getString("participant_id"), j.getString("device_secret"), j.getInt("secret_version"), j.getString("status"))
    }
    override suspend fun revoke(token: String, deviceId: String) { call("me/devices/$deviceId", token, method="DELETE") }
    override suspend fun logout(token: String, all: Boolean) { call(if (all) "auth/logout-all" else "auth/logout", token, method="POST") }
    override suspend fun history(token: String, offset: Int): HistoryPage = parse {
        val j = call("me/transactions?limit=20&offset=$offset", token)
        val list = j.getJSONArray("items")
        HistoryPage((0 until list.length()).map { i -> val t = list.getJSONObject(i)
            WalletTransaction(t.getString("transaction_id"), t.getString("kind"), money(t,"amount_paise"), money(t,"balance_delta_paise"), money(t,"held_delta_paise"), t.getString("created_at")) },
            j.getInt("total"), j.getInt("offset"), j.getInt("limit"))
    }
}

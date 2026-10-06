package com.example.offlinewallet.data.auth

/** Network adapters will map the versioned API fields to these models in a later sprint. */
data class LoginResponse(
    val participantId: String,
    val sessionToken: String,
    val expiresAt: String,
    val role: String,
) {
    override fun toString() = "LoginResponse(credentials=redacted)"
}

data class DeviceEnrollmentResponse(
    val deviceId: String,
    val participantId: String,
    val deviceSecret: String,
    val secretVersion: Int,
    val status: String,
) {
    override fun toString() = "DeviceEnrollmentResponse(credentials=redacted)"
}

data class DeviceCredentials(val deviceId: String, val secret: String, val version: Int) {
    override fun toString() = "DeviceCredentials(redacted)"
}

data class Credentials(
    val participantId: String,
    val sessionToken: String?,
    val sessionExpiresAt: String?,
    val device: DeviceCredentials?,
) {
    override fun toString() = "Credentials(redacted)"
}

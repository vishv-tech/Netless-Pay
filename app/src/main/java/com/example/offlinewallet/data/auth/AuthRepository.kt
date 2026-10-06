package com.example.offlinewallet.data.auth

/** No HTTP client or UI integration in Sprint 2. Call these only after a confirmed server response. */
class AuthRepository(private val store: CredentialStore) {
    @Synchronized
    fun acceptLogin(response: LoginResponse) {
        require(response.role == "PARTICIPANT")
        require(response.participantId.isNotBlank() && response.sessionToken.isNotBlank())
        val previous = store.read()
        val device = previous?.takeIf { it.participantId == response.participantId }?.device
        store.write(Credentials(response.participantId, response.sessionToken, response.expiresAt, device))
    }

    /** Call before requesting replacement: a lost response must not leave an old secret in use. */
    @Synchronized
    fun beginDeviceReplacement() {
        val credentials = requireNotNull(store.read())
        store.write(credentials.copy(device = null))
    }

    @Synchronized
    fun acceptDeviceEnrollment(response: DeviceEnrollmentResponse) {
        val credentials = requireNotNull(store.read())
        require(credentials.participantId == response.participantId)
        require(response.status == "pending" || response.status == "active")
        require(response.secretVersion > 0 && response.deviceSecret.isNotBlank())
        store.write(credentials.copy(device = DeviceCredentials(response.deviceId, response.deviceSecret, response.secretVersion)))
    }

    /** Run even if server logout fails. Future networking must report that remote revocation is unconfirmed. */
    @Synchronized
    fun clearOnLogout() = store.clear()

    @Synchronized
    fun clearOnDeviceRevocation() = beginDeviceReplacement()
}

package com.example.offlinewallet.data.auth

import java.io.ByteArrayInputStream
import java.io.ByteArrayOutputStream
import java.io.DataInputStream
import java.io.DataOutputStream

interface CredentialCipher {
    fun encrypt(plaintext: ByteArray): ByteArray
    fun decrypt(ciphertext: ByteArray): ByteArray
}

interface CredentialBlob {
    fun read(): ByteArray?
    fun write(bytes: ByteArray)
    fun clear()
}

class CredentialsUnavailable : IllegalStateException("Stored credentials unavailable; sign in and enroll again")

/** No Room rows or preferences contain credentials. Each replacement is a single encrypted blob. */
class CredentialStore(private val blob: CredentialBlob, private val cipher: CredentialCipher) {
    @Synchronized
    fun read(): Credentials? {
        val encrypted = blob.read() ?: return null
        var plaintext: ByteArray? = null
        try {
            require(encrypted.size <= 16384)
            plaintext = cipher.decrypt(encrypted)
            return DataInputStream(ByteArrayInputStream(plaintext)).use { input ->
                require(input.readInt() == 1)
                val participant = input.readUTF()
                val token = if (input.readBoolean()) input.readUTF() else null
                val expires = if (input.readBoolean()) input.readUTF() else null
                val device = if (input.readBoolean()) DeviceCredentials(input.readUTF(), input.readUTF(), input.readInt()) else null
                require(input.available() == 0)
                Credentials(participant, token, expires, device)
            }
        } catch (_: Exception) {
            blob.clear()
            throw CredentialsUnavailable()
        } finally {
            plaintext?.fill(0)
        }
    }

    @Synchronized
    fun write(credentials: Credentials) {
        val bytes = ByteArrayOutputStream()
        DataOutputStream(bytes).use { output ->
            output.writeInt(1)
            output.writeUTF(credentials.participantId)
            output.writeBoolean(credentials.sessionToken != null)
            credentials.sessionToken?.let(output::writeUTF)
            output.writeBoolean(credentials.sessionExpiresAt != null)
            credentials.sessionExpiresAt?.let(output::writeUTF)
            output.writeBoolean(credentials.device != null)
            credentials.device?.let { device ->
                output.writeUTF(device.deviceId)
                output.writeUTF(device.secret)
                output.writeInt(device.version)
            }
        }
        val plaintext = bytes.toByteArray()
        try { blob.write(cipher.encrypt(plaintext)) } finally { plaintext.fill(0) }
    }

    @Synchronized
    fun clear() = blob.clear()
}

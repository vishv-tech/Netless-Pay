package com.example.offlinewallet.data.auth

import org.junit.Assert.*
import org.junit.Test
import java.security.SecureRandom
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.spec.GCMParameterSpec

class CredentialStoreTest {
    private class MemoryBlob : CredentialBlob {
        var bytes: ByteArray? = null
        override fun read() = bytes?.clone()
        override fun write(bytes: ByteArray) { this.bytes = bytes.clone() }
        override fun clear() { bytes = null }
    }
    // Tests serialization/authenticated encryption behavior on the JVM, not Android Keystore hardware.
    private class TestCipher : CredentialCipher {
        val key = KeyGenerator.getInstance("AES").apply { init(256) }.generateKey()
        override fun encrypt(plaintext: ByteArray): ByteArray {
            val nonce = ByteArray(12).also(SecureRandom()::nextBytes)
            return nonce + Cipher.getInstance("AES/GCM/NoPadding").run {
                init(Cipher.ENCRYPT_MODE, key, GCMParameterSpec(128, nonce)); doFinal(plaintext)
            }
        }
        override fun decrypt(ciphertext: ByteArray): ByteArray = Cipher.getInstance("AES/GCM/NoPadding").run {
            init(Cipher.DECRYPT_MODE, key, GCMParameterSpec(128, ciphertext.copyOfRange(0, 12)))
            doFinal(ciphertext.copyOfRange(12, ciphertext.size))
        }
    }
    private val blob = MemoryBlob()
    private val store = CredentialStore(blob, TestCipher())
    private val repository = AuthRepository(store)
    private fun login(id: String = "participant") = repository.acceptLogin(LoginResponse(id, "synthetic-session", "future", "PARTICIPANT"))
    private fun device(secret: String = "synthetic-device", version: Int = 1) = repository.acceptDeviceEnrollment(
        DeviceEnrollmentResponse("device-id", "participant", secret, version, "pending"))

    @Test fun encryptedRoundTripAndNoPlaintext() {
        login(); device()
        assertEquals("synthetic-session", store.read()?.sessionToken)
        assertEquals("synthetic-device", store.read()?.device?.secret)
        assertFalse(String(blob.bytes!!).contains("synthetic"))
    }
    @Test fun tamperingFailsClosed() {
        login(); blob.bytes!![20] = (blob.bytes!![20].toInt() xor 1).toByte()
        assertThrows(CredentialsUnavailable::class.java) { store.read() }
        assertNull(blob.bytes)
    }
    @Test fun logoutClearsBothCredentials() {
        login(); device(); repository.clearOnLogout()
        assertNull(store.read())
    }
    @Test fun replacementClearsOldEvenIfResponseLost() {
        login(); device(); repository.beginDeviceReplacement()
        assertNull(store.read()?.device)
        assertEquals("synthetic-session", store.read()?.sessionToken)
        device("replacement-secret", 2)
        assertEquals(2, store.read()?.device?.version)
        assertEquals("replacement-secret", store.read()?.device?.secret)
    }
    @Test fun accountSwitchClearsPreviousDevice() {
        login(); device(); login("another-participant")
        assertNull(store.read()?.device)
    }
    @Test fun sameAccountLoginPreservesDevice() {
        login(); device(); login()
        assertNotNull(store.read()?.device)
    }
    @Test fun wrongOwnerEnrollmentIsRejected() {
        login("another-participant")
        assertThrows(IllegalArgumentException::class.java) { device() }
        assertNull(store.read()?.device)
    }
    @Test fun diagnosticStringsRedactCredentials() {
        login(); device()
        assertFalse(store.read().toString().contains("synthetic"))
        assertFalse(LoginResponse("id", "hidden-session", "future", "PARTICIPANT").toString().contains("hidden-session"))
        assertFalse(DeviceEnrollmentResponse("id", "p", "hidden-secret", 1, "pending").toString().contains("hidden-secret"))
    }
}

package com.example.offlinewallet.data.auth

import android.content.Context
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.AtomicFile
import java.io.File
import java.security.KeyStore
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

/** The alias identifies a generated, non-exportable key; it is not an encryption key. */
class AndroidKeystoreCipher : CredentialCipher {
    private val alias = "offlinewallet.credentials.v1"
    private val aad = "offlinewallet-local-credentials-v1".toByteArray(Charsets.UTF_8)

    @Synchronized
    private fun key(): SecretKey {
        val store = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
        (store.getKey(alias, null) as? SecretKey)?.let { return it }
        return KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore").apply {
            init(KeyGenParameterSpec.Builder(alias, KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT)
                .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                .setKeySize(256)
                .setRandomizedEncryptionRequired(true)
                .build())
        }.generateKey()
    }

    override fun encrypt(plaintext: ByteArray): ByteArray {
        val cipher = Cipher.getInstance("AES/GCM/NoPadding")
        cipher.init(Cipher.ENCRYPT_MODE, key())
        cipher.updateAAD(aad)
        check(cipher.iv.size == 12)
        return cipher.iv + cipher.doFinal(plaintext)
    }

    override fun decrypt(ciphertext: ByteArray): ByteArray {
        require(ciphertext.size >= 28)
        val cipher = Cipher.getInstance("AES/GCM/NoPadding")
        cipher.init(Cipher.DECRYPT_MODE, key(), GCMParameterSpec(128, ciphertext.copyOfRange(0, 12)))
        cipher.updateAAD(aad)
        return cipher.doFinal(ciphertext.copyOfRange(12, ciphertext.size))
    }
}

class AndroidCredentialBlob(context: Context) : CredentialBlob {
    private val file = AtomicFile(File(context.applicationContext.noBackupFilesDir, "credentials.enc"))
    @Synchronized
    override fun read(): ByteArray? = if (file.baseFile.exists()) file.readFully() else null

    @Synchronized
    override fun write(bytes: ByteArray) {
        val stream = file.startWrite()
        try {
            stream.write(bytes)
            file.finishWrite(stream)
        } catch (error: Exception) {
            file.failWrite(stream)
            throw error
        }
    }

    @Synchronized
    override fun clear() = file.delete()
}

fun androidCredentialStore(context: Context) = CredentialStore(AndroidCredentialBlob(context), AndroidKeystoreCipher())

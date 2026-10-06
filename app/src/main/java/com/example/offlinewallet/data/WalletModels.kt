package com.example.offlinewallet.data

data class ParticipantProfile(val participantId: String, val name: String, val phone: String, val phoneConfirmation: String, val status: String) {
    override fun toString() = "ParticipantProfile(redacted)"
}
data class WalletSummary(val walletId: String, val balancePaise: Long, val heldPaise: Long, val availablePaise: Long, val enabled: Boolean)
data class ConfirmedWallet(val summary: WalletSummary, val confirmedAt: Long)
data class ParticipantDevice(val deviceId: String, val participantId: String, val label: String, val status: String, val secretVersion: Int)
data class WalletTransaction(val id: String, val kind: String, val amountPaise: Long, val balanceDeltaPaise: Long, val heldDeltaPaise: Long, val createdAt: String)
data class HistoryPage(val items: List<WalletTransaction>, val total: Int, val offset: Int, val limit: Int)
data class CachedParticipant(val profile: ParticipantProfile, val wallet: ConfirmedWallet?)

enum class Failure { OFFLINE, SESSION, INVALID_LOGIN, ENROLLMENT, VALIDATION, DEVICE_APPROVAL, RATE_LIMIT, SERVER, CONFIGURATION, STORAGE }
class WalletFailure(val reason: Failure) : Exception(reason.name)

fun failureFor(status: Int, path: String): Failure = when (status) {
    401 -> if (path.endsWith("auth/login")) Failure.INVALID_LOGIN else Failure.SESSION
    403 -> Failure.DEVICE_APPROVAL
    400 -> if (path.endsWith("auth/redeem")) Failure.ENROLLMENT else Failure.VALIDATION
    422, 409 -> Failure.VALIDATION
    429 -> Failure.RATE_LIMIT
    else -> Failure.SERVER
}

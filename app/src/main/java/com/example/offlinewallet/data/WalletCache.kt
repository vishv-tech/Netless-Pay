package com.example.offlinewallet.data

import androidx.room.Dao
import androidx.room.Entity
import androidx.room.PrimaryKey
import androidx.room.Query
import androidx.room.Upsert

@Entity(tableName="participant_cache")
data class ParticipantCacheRow(
    @PrimaryKey val participantId: String, val name: String, val phone: String, val phoneConfirmation: String, val status: String,
    val walletId: String?, val balancePaise: Long?, val heldPaise: Long?, val availablePaise: Long?, val enabled: Boolean?, val confirmedAt: Long?,
)
@Dao
interface ParticipantCacheDao {
    @Query("SELECT * FROM participant_cache WHERE participantId = :participantId") suspend fun load(participantId: String): ParticipantCacheRow?
    @Upsert suspend fun save(row: ParticipantCacheRow)
    @Query("DELETE FROM participant_cache") suspend fun clear()
}
interface WalletCache {
    suspend fun load(id: String): CachedParticipant?
    suspend fun save(value: CachedParticipant)
    suspend fun clear()
}
class RoomWalletCache(private val dao: ParticipantCacheDao) : WalletCache {
    override suspend fun load(id: String): CachedParticipant? = dao.load(id)?.let { row ->
        val wallet = if (row.walletId != null && row.balancePaise != null && row.heldPaise != null && row.availablePaise != null && row.enabled != null && row.confirmedAt != null)
            ConfirmedWallet(WalletSummary(row.walletId, row.balancePaise, row.heldPaise, row.availablePaise, row.enabled), row.confirmedAt) else null
        CachedParticipant(ParticipantProfile(row.participantId, row.name, row.phone, row.phoneConfirmation, row.status), wallet)
    }
    override suspend fun save(value: CachedParticipant) {
        val p = value.profile; val w = value.wallet
        dao.save(ParticipantCacheRow(p.participantId,p.name,p.phone,p.phoneConfirmation,p.status,w?.summary?.walletId,
            w?.summary?.balancePaise,w?.summary?.heldPaise,w?.summary?.availablePaise,w?.summary?.enabled,w?.confirmedAt))
    }
    override suspend fun clear() = dao.clear()
}

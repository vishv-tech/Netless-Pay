package com.example.offlinewallet

import androidx.room.Room
import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import com.example.offlinewallet.data.*
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.runBlocking
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class WalletCacheMigrationTest {
    @Test fun versionOnePreferencesSurviveAndConfirmedCacheIsParticipantScoped() = runBlocking {
        val context = ApplicationProvider.getApplicationContext<TestWalletApplication>()
        val name = "isolated-sprint3-migration.db"
        context.deleteDatabase(name)
        context.openOrCreateDatabase(name, 0, null).use { legacy ->
            legacy.execSQL("CREATE TABLE ui_preferences (id INTEGER NOT NULL PRIMARY KEY, balanceHidden INTEGER NOT NULL)")
            legacy.execSQL("INSERT INTO ui_preferences VALUES (1, 1)")
            legacy.version = 1
        }
        val db = Room.databaseBuilder(context, WalletDatabase::class.java, name)
            .addMigrations(WalletDatabase.MIGRATION_1_2).build()
        try {
            assertTrue(db.uiPreferencesDao().observe().first()!!.balanceHidden)
            val cache = RoomWalletCache(db.participantCacheDao())
            val profile = ParticipantProfile("synthetic-a", "Synthetic", "+919876543210", "admin-confirmed phone", "active")
            cache.save(CachedParticipant(profile, ConfirmedWallet(WalletSummary("synthetic-wallet", 1234, 0, 1234, true), 1000)))
            assertEquals(1234L, cache.load(profile.participantId)!!.wallet!!.summary.balancePaise)
            assertEquals(1000L, cache.load(profile.participantId)!!.wallet!!.confirmedAt)
            assertNull(cache.load("synthetic-b"))
            cache.clear()
            assertNull(cache.load(profile.participantId))
        } finally { db.close(); context.deleteDatabase(name) }
    }
}

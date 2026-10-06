package com.example.offlinewallet.data

import android.content.Context
import androidx.room.Database
import androidx.room.Room
import androidx.room.RoomDatabase
import androidx.room.migration.Migration
import androidx.sqlite.db.SupportSQLiteDatabase

@Database(entities = [UiPreferences::class, ParticipantCacheRow::class], version = 2, exportSchema = true)
abstract class WalletDatabase : RoomDatabase() {
    abstract fun uiPreferencesDao(): UiPreferencesDao
    abstract fun participantCacheDao(): ParticipantCacheDao

    companion object {
        @Volatile private var instance: WalletDatabase? = null
        val MIGRATION_1_2 = object : Migration(1, 2) {
            override fun migrate(db: SupportSQLiteDatabase) {
                db.execSQL("CREATE TABLE IF NOT EXISTS participant_cache (participantId TEXT NOT NULL PRIMARY KEY, name TEXT NOT NULL, phone TEXT NOT NULL, phoneConfirmation TEXT NOT NULL, status TEXT NOT NULL, walletId TEXT, balancePaise INTEGER, heldPaise INTEGER, availablePaise INTEGER, enabled INTEGER, confirmedAt INTEGER)")
            }
        }

        fun getInstance(context: Context): WalletDatabase = instance ?: synchronized(this) {
            instance ?: Room.databaseBuilder(
                context.applicationContext,
                WalletDatabase::class.java,
                "wallet-local.db",
            ).addMigrations(MIGRATION_1_2).build().also { instance = it }
        }
    }
}

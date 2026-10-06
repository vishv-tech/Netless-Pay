package com.example.offlinewallet.data

import androidx.room.Dao
import androidx.room.Query
import androidx.room.Upsert
import kotlinx.coroutines.flow.Flow

@Dao
interface UiPreferencesDao {
    @Query("SELECT * FROM ui_preferences WHERE id = 1")
    fun observe(): Flow<UiPreferences?>

    @Upsert
    suspend fun save(preferences: UiPreferences)
}

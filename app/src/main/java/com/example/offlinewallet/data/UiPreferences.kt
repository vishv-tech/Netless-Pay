package com.example.offlinewallet.data

import androidx.room.Entity
import androidx.room.PrimaryKey

/** Nonfinancial local preferences; never a wallet ledger or a credential store. */
@Entity(tableName = "ui_preferences")
data class UiPreferences(
    @PrimaryKey val id: Int = 1,
    val balanceHidden: Boolean = true,
)

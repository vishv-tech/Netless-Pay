package com.example.offlinewallet.ui

interface LockPreferences {
    var enabled: Boolean
    var offered: Boolean
}

/** Monotonic timeout in memory; every new process starts locked when enabled. */
class AppLock(private val preferences: LockPreferences, private val elapsed: () -> Long) {
    var locked = preferences.enabled
        private set
    private var backgroundAt: Long? = null
    val enabled get() = preferences.enabled
    fun background() { if (backgroundAt == null) backgroundAt=elapsed() }
    fun foreground() {
        backgroundAt?.let { if (enabled && elapsed()-it >= 30000L) locked=true }
        backgroundAt=null
    }
    fun lock() { if (enabled) locked=true }
    fun authenticated(enable: Boolean = false) {
        if (enable) { preferences.enabled=true; preferences.offered=true }
        locked=false; backgroundAt=null
    }
    fun disableAfterAuthentication() { preferences.enabled=false; locked=false; backgroundAt=null }
    fun decline() { preferences.offered=true }
    fun shouldOffer() = !enabled && !preferences.offered
    fun clearAfterErasingLocalData() { preferences.enabled=false; locked=false; backgroundAt=null }
}

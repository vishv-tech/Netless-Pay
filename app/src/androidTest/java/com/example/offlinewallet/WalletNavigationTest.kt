package com.example.offlinewallet

import androidx.test.core.app.ActivityScenario
import androidx.test.core.app.ApplicationProvider
import androidx.test.espresso.Espresso.onView
import androidx.test.espresso.action.ViewActions.*
import androidx.test.espresso.assertion.ViewAssertions.matches
import androidx.test.espresso.matcher.ViewMatchers.*
import androidx.test.ext.junit.runners.AndroidJUnit4
import com.example.offlinewallet.data.auth.androidCredentialStore
import com.example.offlinewallet.data.auth.Credentials
import com.example.offlinewallet.data.auth.DeviceCredentials
import org.junit.Assert.*
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class WalletNavigationTest {
    private val app get()=ApplicationProvider.getApplicationContext<TestWalletApplication>()
    @Before fun reset() { app.fake.loggedIn=false;app.fake.activations=0;app.privacy.enabled=false;app.privacy.offered=true }
    @Test fun enrollmentAndLoginNavigation() {
        ActivityScenario.launch(MainActivity::class.java).use {
            onView(withId(R.id.switchMode)).perform(scrollTo(),click())
            onView(withId(R.id.token)).check(matches(isDisplayed()))
            onView(withId(R.id.token)).perform(replaceText("synthetic-token"))
            onView(withId(R.id.password)).perform(replaceText("Synthetic-river-7-stones"))
            onView(withId(R.id.confirmation)).perform(replaceText("Synthetic-river-7-stones"),closeSoftKeyboard())
            onView(withId(R.id.submit)).perform(scrollTo(),click())
            onView(withId(R.id.phone)).check(matches(isDisplayed()))
            onView(withId(R.id.phone)).perform(replaceText("9876543210"))
            onView(withId(R.id.password)).perform(replaceText("synthetic-password"),closeSoftKeyboard())
            onView(withId(R.id.submit)).perform(scrollTo(),click())
            onView(withId(R.id.balance)).check(matches(withText("•••")))
            assertEquals(1,app.fake.activations)
        }
    }
    @Test fun bottomNavigationProfileAndLogout() {
        app.fake.loggedIn=true
        ActivityScenario.launch(MainActivity::class.java).use {
            onView(withId(R.id.nav_add_money)).perform(click())
            onView(withId(R.id.accountTitle)).check(matches(withText(R.string.pool_unconfigured)))
            onView(withId(R.id.nav_profile)).perform(click())
            onView(withId(R.id.identity)).check(matches(withText("Synthetic Participant")))
            onView(withId(R.id.signOut)).perform(scrollTo(),click())
            onView(withText(R.string.confirm)).perform(click())
            onView(withId(R.id.phone)).check(matches(isDisplayed()))
            assertFalse(app.fake.loggedIn)
        }
    }
    @Test fun balanceRevealHideAndRotation() {
        app.fake.loggedIn=true
        ActivityScenario.launch(MainActivity::class.java).use { scenario ->
            onView(withId(R.id.balance)).check(matches(withText("•••")))
            onView(withId(R.id.balanceCard)).perform(click())
            onView(withId(R.id.balance)).check(matches(withText("₹12.34")))
            scenario.recreate()
            onView(withId(R.id.balance)).check(matches(withText("•••")))
        }
    }
    @Test fun homeLockIconOffersOptionalSetupWithoutEnrollment() {
        app.fake.loggedIn=true
        ActivityScenario.launch(MainActivity::class.java).use {
            onView(withId(R.id.lock)).perform(click())
            onView(withText(R.string.not_now)).check(matches(isDisplayed())).perform(click())
            onView(withId(R.id.balance)).check(matches(withText("•••")))
            assertFalse(app.privacy.enabled)
        }
    }
    @Test fun passwordAndTokenAreNotRestoredOnRecreation() {
        ActivityScenario.launch(MainActivity::class.java).use { scenario ->
            onView(withId(R.id.switchMode)).perform(scrollTo(),click())
            onView(withId(R.id.token)).perform(replaceText("synthetic-secret"))
            onView(withId(R.id.password)).perform(replaceText("synthetic-secret"),closeSoftKeyboard())
            scenario.recreate()
            onView(withId(R.id.token)).check(matches(withText("")))
            onView(withId(R.id.password)).check(matches(withText("")))
        }
    }
    @Test fun realAndroidKeystoreRoundTripAndClear() {
        val isolatedDir=java.io.File(app.noBackupFilesDir,"instrumentation-credentials").apply { mkdirs() }
        val isolatedContext=object : android.content.ContextWrapper(app) {
            override fun getApplicationContext(): android.content.Context=this
            override fun getNoBackupFilesDir(): java.io.File=isolatedDir
        }
        val store=androidCredentialStore(isolatedContext)
        try {
            store.write(Credentials("synthetic-id","synthetic-session","2099-01-01T00:00:00Z",DeviceCredentials("synthetic-device","synthetic-secret",1)))
            assertEquals("synthetic-session",store.read()!!.sessionToken)
            assertEquals("synthetic-secret",store.read()!!.device!!.secret)
            val bytes=java.io.File(isolatedDir,"credentials.enc").readBytes()
            assertFalse(String(bytes).contains("synthetic-secret"))
            store.clear();assertNull(store.read())
        } finally { store.clear() }
    }
}

import java.net.URI

plugins {
    alias(libs.plugins.android.application)
    alias(libs.plugins.ksp)
}

val walletApiUrl = providers.gradleProperty("WALLET_API_BASE_URL").orNull
fun quoted(value: String) = "\"" + value.replace("\\", "\\\\").replace("\"", "\\\"") + "\""

android {
    namespace = "com.example.offlinewallet"
    buildFeatures {
        viewBinding = true
        buildConfig = true
    }
    compileSdk {
        version = release(37)
    }

    defaultConfig {
        applicationId = "com.example.offlinewallet"
        minSdk = 26
        targetSdk = 36
        versionCode = 1
        versionName = "1.0"

        testInstrumentationRunner = "com.example.offlinewallet.WalletTestRunner"
    }

    buildTypes {
        debug {
            val endpoint = walletApiUrl ?: "http://10.0.2.2:8000/"
            val uri = URI(endpoint)
            require(uri.scheme == "https" || (uri.scheme == "http" && uri.host in listOf("10.0.2.2", "127.0.0.1", "localhost")))
            require(uri.userInfo == null && uri.query == null && uri.fragment == null)
            buildConfigField("String", "BACKEND_BASE_URL", quoted(endpoint))
        }
        release {
            val endpoint = walletApiUrl?.takeIf { it.startsWith("https://") } ?: ""
            buildConfigField("String", "BACKEND_BASE_URL", quoted(endpoint))
            isMinifyEnabled = false
            proguardFiles(
                getDefaultProguardFile("proguard-android-optimize.txt"),
                "proguard-rules.pro"
            )
        }
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_11
        targetCompatibility = JavaVersion.VERSION_11
    }
}

dependencies {
    implementation(libs.androidx.biometric)
    implementation(libs.androidx.lifecycle.runtime.ktx)
    implementation(libs.okhttp)
    testImplementation(libs.mockwebserver)
    testImplementation(libs.json.jvm)
    testImplementation(libs.coroutines.test)
    androidTestImplementation(libs.androidx.test.core.ktx)
    implementation(libs.androidx.lifecycle.viewmodel.ktx)
    implementation(libs.androidx.room.runtime)
    ksp(libs.androidx.room.compiler)
    implementation(libs.androidx.activity.ktx)
    implementation(libs.androidx.appcompat)
    implementation(libs.androidx.constraintlayout)
    implementation(libs.androidx.core.ktx)
    implementation(libs.material)
    testImplementation(libs.junit)
    androidTestImplementation(libs.androidx.espresso.core)
    androidTestImplementation(libs.androidx.junit)
}

ksp {
    arg("room.schemaLocation", "$projectDir/schemas")
}

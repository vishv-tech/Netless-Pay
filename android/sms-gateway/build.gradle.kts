plugins {
    alias(libs.plugins.android.application)
}

android {
    namespace = "com.example.offlinewallet.gateway"
    compileSdk {
        version = release(37)
    }
    defaultConfig {
        applicationId = "com.example.offlinewallet.gateway"
        minSdk = 26
        targetSdk = 36
        versionCode = 1
        versionName = "0.1.0"
    }
    buildFeatures { viewBinding = true }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_11
        targetCompatibility = JavaVersion.VERSION_11
    }
}

dependencies {
    implementation(libs.androidx.activity.ktx)
    implementation(libs.androidx.appcompat)
    implementation(libs.androidx.core.ktx)
}

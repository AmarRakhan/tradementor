plugins {
    alias(libs.plugins.android.application)
    alias(libs.plugins.kotlin.compose)
    id("com.google.gms.google-services") apply false
}

if (file("google-services.json").exists()) {
    apply(plugin = "com.google.gms.google-services")
}

android {
    namespace = "com.tradementor.app"

    compileSdk {
        version = release(37) {
            minorApiLevel = 1
        }
    }

    defaultConfig {
        applicationId = "com.tradementor.app"
        minSdk = 26
        targetSdk = 37
        versionCode = 234
        versionName = "2.65"

        buildConfigField("String", "REOWN_PROJECT_ID", "\"b0eb7c20f22a84fdbb98ab39b4df7959\"")
        buildConfigField("String", "CLOUD_API_URL", "\"https://tradementor-api-604335232956.europe-west4.run.app\"")
        buildConfigField("Boolean", "CLOUD_ACCOUNTS_ENABLED", "true")
        buildConfigField("String", "WALLET_REDIRECT", "\"tradementor://wallet\"")
        manifestPlaceholders["walletScheme"] = "tradementor"

        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"
    }

    flavorDimensions += "audience"
    productFlavors {
        create("admin") {
            dimension = "audience"
            buildConfigField("Boolean", "ADMIN_FEATURES", "true")
            resValue("string", "app_name", "TradeMentor - Amar Admin")
        }
        create("public") {
            dimension = "audience"
            buildConfigField("Boolean", "ADMIN_FEATURES", "false")
            resValue("string", "app_name", "TradeMentor")
        }
    }

    signingConfigs {
        getByName("debug") {
            // Stable local test key: keeps staging upgrades compatible across
            // Codex, Android Studio and manual builds. The key stays ignored
            // from Git and is never used for the public Play Store release.
            val stableDebugKeystore = rootProject.file(".android/debug.keystore")
            if (stableDebugKeystore.exists()) {
                storeFile = stableDebugKeystore
                storePassword = "android"
                keyAlias = "androiddebugkey"
                keyPassword = "android"
            }
        }
    }

    buildTypes {
        debug {
        }
        create("staging") {
            initWith(getByName("debug"))
            signingConfig = signingConfigs.getByName("debug")
            applicationIdSuffix = ".test"
            versionNameSuffix = "-test"
            buildConfigField("String", "WALLET_REDIRECT", "\"tradementortest://wallet\"")
            manifestPlaceholders["walletScheme"] = "tradementortest"
            resValue("string", "app_name", "TradeMentor Test")
            matchingFallbacks += listOf("debug")
        }
        release {
            optimization {
                enable = false
            }
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_11
        targetCompatibility = JavaVersion.VERSION_11
    }

    buildFeatures {
        compose = true
        buildConfig = true
        resValues = true
    }
}

dependencies {

    implementation(platform("com.google.firebase:firebase-bom:34.17.0"))
    implementation("com.google.firebase:firebase-auth")
    implementation("com.google.firebase:firebase-firestore")
    implementation("com.google.firebase:firebase-analytics")

    implementation(platform(libs.androidx.compose.bom))

    implementation(libs.androidx.activity.compose)
    implementation(libs.androidx.compose.material3)
    implementation(libs.androidx.compose.ui)
    implementation(libs.androidx.compose.ui.graphics)
    implementation(libs.androidx.compose.ui.tooling.preview)
    implementation(libs.androidx.core.ktx)
    implementation(libs.androidx.lifecycle.runtime.ktx)
    implementation(libs.androidx.work.runtime.ktx)

    // Retrofit
    implementation(libs.retrofit)
    implementation(libs.retrofit.gson)

    // OkHttp
    implementation(libs.okhttp)
    implementation(libs.okhttp.logging)
    implementation("org.web3j:crypto:4.9.8-hotfix")

    // Reown AppKit: alleen walletverbinding en openbaar accountadres.
    implementation(platform("com.reown:android-bom:1.6.13"))
    implementation("com.reown:android-core")
    implementation("com.reown:appkit")

    testImplementation(libs.junit)

    androidTestImplementation(platform(libs.androidx.compose.bom))
    androidTestImplementation(libs.androidx.compose.ui.test.junit4)
    androidTestImplementation(libs.androidx.espresso.core)
    androidTestImplementation(libs.androidx.junit)

    debugImplementation(libs.androidx.compose.ui.test.manifest)
    debugImplementation(libs.androidx.compose.ui.tooling)
}

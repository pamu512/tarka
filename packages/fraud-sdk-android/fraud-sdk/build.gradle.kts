plugins {
    id("com.android.library")
    kotlin("android")
}

android {
    namespace = "io.tarka.sdk"
    compileSdk = 35
    defaultConfig {
        minSdk = 26
        consumerProguardFiles("consumer-rules.pro")
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions {
        jvmTarget = "17"
    }
    testOptions {
        unitTests {
            // org.json is stubbed in android.jar and throws "not mocked" in
            // JVM unit tests; return defaults + real artifact below keep JSON
            // helpers testable off-device.
            isReturnDefaultValues = true
        }
    }
}

dependencies {
    implementation("com.google.android.play:integrity:1.4.0")
    implementation("com.squareup.okhttp3:okhttp:4.12.0")
    testImplementation("junit:junit:4.13.2")
    // Real org.json for JVM unit tests (android.jar stub throws "not mocked").
    testImplementation("org.json:json:20240303")
}

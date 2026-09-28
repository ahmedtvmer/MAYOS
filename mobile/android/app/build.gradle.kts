import java.util.Properties

plugins {
    id("com.android.application")
    // The Flutter Gradle Plugin must be applied after the Android and Kotlin Gradle plugins.
    id("dev.flutter.flutter-gradle-plugin")
}


// Release signing (issue #43). `key.properties` lives in `mobile/android/` (the
// rootProject for this build) and is gitignored together with `*.jks` /
// `*.keystore`. `storeFile` is resolved relative to `mobile/android/`, so an
// absolute path or `../upload-keystore.jks` both work.
//
// A release build WITHOUT this file must fail loudly rather than fall back to
// the debug key, so the guard below runs only when a release task is actually
// requested: debug builds, `flutter test`, and Gradle sync stay unaffected.
val keystoreProperties = Properties()
val keystorePropertiesFile = rootProject.file("key.properties")
if (keystorePropertiesFile.exists()) {
    keystorePropertiesFile.inputStream().use { keystoreProperties.load(it) }
}

val requiredKeystoreKeys = listOf("storeFile", "storePassword", "keyAlias", "keyPassword")
val missingKeystoreKeys = requiredKeystoreKeys.filter { keystoreProperties.getProperty(it).isNullOrBlank() }
val releaseSigningConfigured = keystorePropertiesFile.exists() && missingKeystoreKeys.isEmpty()
val keystoreFilePath = keystoreProperties.getProperty("storeFile") ?: ""
val keystoreFile = if (keystoreFilePath.isBlank()) null else rootProject.file(keystoreFilePath)
val releaseSigningUsable = releaseSigningConfigured && keystoreFile?.exists() == true

// A release build must fail loudly when signing is unconfigured. "Release" is
// not the only way to reach one: a bare `assemble`, `bundle`, or `build` builds
// every variant, release included, so those count too. Variant-suffixed tasks
// (`assembleDebug`) and Gradle sync do not, so debug builds and `flutter test`
// stay unaffected.
val releaseBuildRequested = gradle.startParameter.taskNames.any { name ->
    val task = name.substringAfterLast(':')
    task.contains("Release") || task == "assemble" || task == "bundle" || task == "build"
}
if (releaseBuildRequested) {
    if (!keystorePropertiesFile.exists()) {
        throw GradleException(
            "Release signing is not configured: mobile/android/key.properties is missing. " +
                "Create an upload keystore and key.properties (see docs/PLAY_RELEASE.md), " +
                "or build debug with `flutter build apk --debug`."
        )
    }
    if (missingKeystoreKeys.isNotEmpty()) {
        throw GradleException(
            "Release signing is not configured: mobile/android/key.properties is missing " +
                "or blank entries for: ${missingKeystoreKeys.joinToString(", ")}. " +
                "See docs/PLAY_RELEASE.md."
        )
    }
    if (keystoreFile?.exists() != true) {
        throw GradleException(
            "Release signing is not configured: key.properties storeFile points at " +
                "'$keystoreFilePath' (resolved to ${keystoreFile ?: "<blank>"}), which does not exist. " +
                "See docs/PLAY_RELEASE.md."
        )
    }
}

android {
    namespace = "com.mayos.mayos_mobile"
    compileSdk = flutter.compileSdkVersion
    ndkVersion = flutter.ndkVersion

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    defaultConfig {
        applicationId = "com.mayos.mayos_mobile"
        minSdk = flutter.minSdkVersion
        targetSdk = flutter.targetSdkVersion
        // versionCode/versionName come from pubspec.yaml (`version: 0.1.0+1`).
        // When using split APKs, 1000 * ABI_VERSION is added automatically by
        // Flutter. (https://flutter.dev/to/review/gradle-config)
        versionCode = flutter.versionCode
        versionName = flutter.versionName

        // Host for the App Link reset intent-filter. Override per deployment
        // with -PappLinkHost=api.example.com; defaults to the fly.toml app host.
        manifestPlaceholders["appLinkHost"] =
            (project.findProperty("appLinkHost") as String?) ?: "mayos-api.fly.dev"
    }

    signingConfigs {
        create("release") {
            if (releaseSigningUsable) {
                storeFile = checkNotNull(keystoreFile) {
                    "Release signing is marked usable without a keystore file."
                }
                storePassword = keystoreProperties.getProperty("storePassword")
                keyAlias = keystoreProperties.getProperty("keyAlias")
                keyPassword = keystoreProperties.getProperty("keyPassword")
            }
        }
    }

    buildTypes {
        release {
            // Never the debug key: with key.properties absent this config is
            // empty, and the guard above fails any requested release build with
            // a clear message instead of shipping a debug-signed artifact.
            signingConfig = signingConfigs.getByName("release")
        }
    }
}

kotlin {
    compilerOptions {
        jvmTarget = org.jetbrains.kotlin.gradle.dsl.JvmTarget.JVM_17
    }
}

flutter {
    source = "../.."
}

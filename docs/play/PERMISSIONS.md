# Android permissions review

Prepared for issue #750. Play Console asks for a justification for every
permission the app requests. This document lists every permission that ends up
in the **merged manifest** (the app's own `mobile/android/app/src/main/
AndroidManifest.xml` plus everything the Android Gradle plugin merges in from
dependencies), why it is needed, and where it comes from.

Verified against the manifests of the plugin versions resolved from
`mobile/pubspec.yaml` (flutter_local_notifications 22.3.1,
google_sign_in_android 7.2.17, image_picker_android 0.8.13+25, wakelock_plus,
flutter_timezone, posthog_flutter, file_picker, share_plus,
flutter_secure_storage, play_install_referrer): none of them adds any further
`uses-permission` entries.

## App manifest permissions

| Permission | Source | Why it is needed |
| :--- | :--- | :--- |
| `INTERNET` | App manifest (also merged in by `google_sign_in_android`) | The app's core function is talking to the MAYOS API (`https://api.mayos.online`); Google Sign-In also needs it. Expected — Play never flags plain `INTERNET`. |
| `ACCESS_NETWORK_STATE` | App manifest | Connectivity checks so network-dependent features (API reachability, reconnection refetching) can degrade gracefully instead of retrying blind. No user data is read from it. |
| `CAMERA` | App manifest | Lets the Player take a photo with the camera to decorate their **workout share card** (`image_picker`, `ImageSource.camera`). The photo is resized locally and stays on the device — it is never uploaded. The alternative source (gallery) uses the system photo picker and needs no permission. |
| `RECEIVE_BOOT_COMPLETED` | App manifest | Rest-end reminders (issue #125): after a reboot, the scheduled local notifications must be re-registered, or a Player's rest-end alarm silently disappears. Used only by the `flutter_local_notifications` boot receiver (non-exported). |
| `SCHEDULE_EXACT_ALARM` | App manifest | The end-of-rest buzz is a **user-set timer**: exact delivery at the moment the Player chose. Asked once during rest-alert onboarding; Android 14+ denies it by default and a refusal falls back to an inexact allow-while-idle alarm. See the dedicated section below. |

## Permissions merged in by plugins

| Permission | Source | Why it is needed |
| :--- | :--- | :--- |
| `POST_NOTIFICATIONS` | `flutter_local_notifications` 22.3.1 | Required on Android 13+ to show the rest-end timer notification (the whole point of the rest-alert feature, issue #125). The app requests it at most once, from the dedicated onboarding step, and the rest-alert feature degrades gracefully when denied. |
| `VIBRATE` | `flutter_local_notifications` 22.3.1 | Lets the rest-end notification vibrate. No standalone vibration API call is made. |
| `com.google.android.finsky.permission.BIND_GET_INSTALL_REFERRER_SERVICE` | `play_install_referrer` (Google's install-referrer library) | Lets the app read the Play install referrer once per install so registration records only parsed UTM labels (source/medium/campaign). The plugin's own manifest adds no permission; this one comes merged in from Google's referrer library (documented in `docs/PLAY_RELEASE.md` §8). |

Everything else merged in is not a permission: `file_picker` and the app's own
manifest add `<queries>` entries (documented intent visibility), and
`image_picker`/`share_plus`/`flutter_secure_storage` contribute only
file providers and an `uses-sdk` override.

## Exact alarms — user-set rest timer

`SCHEDULE_EXACT_ALARM` **is declared** in the app manifest. The end-of-rest
buzz is a **user-initiated timer**: the Player explicitly starts a rest in the
workout logger and expects the alarm at the moment they set. A late buzz is a
real training failure, so rest-end reminders use an **exact while-idle alarm**
while Android grants the permission, and fall back to an
**inexact, allow-while-idle alarm** when it is refused. Play's exact-alarm
policy exempts user-initiated timers (an alarm-clock-type use), which is what
this is.

- The permission is asked **once**, from the dedicated rest-alert onboarding
  step (issue #125's ask-once policy, recorded device-wide so the prompts
  never appear twice).
- On **Android 14+ (API 34)**, `SCHEDULE_EXACT_ALARM` is denied by default;
  the user must grant it from the system settings hand-off. A refusal is not
  an error: the rest-end alarm silently degrades to the inexact alarm, and the
  in-app rest bar remains the source of truth while the app is open.
- `USE_EXACT_ALARM` is **not** used — that permission is reserved for
  alarm/calendar apps and would be rejected in review for a fitness app.
- `endScheduleMode()` in `mobile/lib/src/core/rest_alerts.dart` returns exact
  when the grant exists and inexact otherwise; both `areGranted()` (used for
  onboarding messaging) and the schedule call go through this seam.

If Play review ever questions the permission, answer with exactly this: a
user-set rest timer between sets, asked once, with an inexact fallback —
matching the Play policy's allowance for user-initiated timers.

## Post-shipping checklist

- Re-verify this list against the actual merged manifest after each plugin
  upgrade:
  `cd mobile/android && ./gradlew :app:dependencies` or inspect
  `build/app/intermediates/merged_manifests/release/AndroidManifest.xml`
  after a release build.
- Play shows the merged permission list under **App content → Permissions**;
  keep each row's answer consistent with the table above.

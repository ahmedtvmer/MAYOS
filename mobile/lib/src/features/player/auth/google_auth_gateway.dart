import 'package:flutter/foundation.dart';
import 'package:google_sign_in/google_sign_in.dart';

/// How a screen offers Google sign-in on this build (#115, #127).
enum GoogleSignInButtonStyle {
  /// No button: the build carries no `GOOGLE_WEB_CLIENT_ID`, or the platform
  /// cannot drive `authenticate()` here. Web renders Google's own
  /// `renderButton()` instead, which lands with #127.
  hidden,

  /// The app's own full-width, Google-branded button (Android).
  appRendered,
}

/// What the Google SDK reported for one interactive sign-in attempt (#115).
sealed class GoogleAuthOutcome {
  const GoogleAuthOutcome();
}

/// The person finished the flow; [idToken] is the token to hand to
/// `POST /auth/google`.
final class GoogleAuthIdToken extends GoogleAuthOutcome {
  const GoogleAuthIdToken(this.idToken);

  final String idToken;
}

/// The person dismissed the sheet without choosing an account.
final class GoogleAuthCanceled extends GoogleAuthOutcome {
  const GoogleAuthCanceled();
}

/// The SDK refused (misconfiguration, dropped connection). [message] is safe to
/// show.
final class GoogleAuthFailed extends GoogleAuthOutcome {
  const GoogleAuthFailed(this.message);

  final String message;
}

/// The seam between the sign-in screens and `google_sign_in` (#115).
///
/// The screens only ever see this interface, so tests fake the SDK instead of
/// reaching a platform channel, and the web half (#127) plugs in behind the
/// same shape.
abstract class GoogleAuthGateway {
  /// Which button a screen should build for this platform and build config.
  GoogleSignInButtonStyle get buttonStyle;

  /// One interactive sign-in attempt: an ID token, a dismissal, or a failure.
  Future<GoogleAuthOutcome> authenticate();

  /// Drops the SDK's own sign-in state. Called whenever the MAYOS session
  /// ends — logout, a rejected token, account deletion — and whenever a
  /// half-finished sign-up is abandoned, so nothing lingers on the device.
  Future<void> clearSdkState();
}

/// The real `google_sign_in` v7 adapter.
///
/// One `initialize(serverClientId: GOOGLE_WEB_CLIENT_ID)`, `authenticate()` for
/// the ID token, and no scopes: MAYOS only ever needs to know who the person
/// is (#113). What `authenticate()` returns is the only sign-in fact this
/// class keeps — there is no second, event-derived copy of the SDK state.
class GoogleSdkAuthGateway implements GoogleAuthGateway {
  /// The single build-time configuration, supplied as
  /// `--dart-define=GOOGLE_WEB_CLIENT_ID=...`. Never hard-coded: without it
  /// Google sign-in stays switched off and the button stays hidden.
  static const String webClientId =
      String.fromEnvironment('GOOGLE_WEB_CLIENT_ID');

  Future<void>? _ready;

  bool get _configured => webClientId.isNotEmpty;

  @override
  GoogleSignInButtonStyle get buttonStyle {
    if (!_configured || kIsWeb) {
      return GoogleSignInButtonStyle.hidden;
    }
    return GoogleSignIn.instance.supportsAuthenticate()
        ? GoogleSignInButtonStyle.appRendered
        : GoogleSignInButtonStyle.hidden;
  }

  @override
  Future<GoogleAuthOutcome> authenticate() async {
    if (!_configured) {
      return const GoogleAuthFailed(
          'Google sign-in is not set up on this build.');
    }
    try {
      await _initialize();
      final GoogleSignInAccount account =
          await GoogleSignIn.instance.authenticate();
      final String? idToken = account.authentication.idToken;
      if (idToken == null || idToken.isEmpty) {
        return const GoogleAuthFailed(
            'Google did not return a sign-in token. Please try again.');
      }
      return GoogleAuthIdToken(idToken);
    } on GoogleSignInException catch (error) {
      if (error.code == GoogleSignInExceptionCode.canceled ||
          error.code == GoogleSignInExceptionCode.interrupted) {
        return const GoogleAuthCanceled();
      }
      return GoogleAuthFailed(_messageFor(error.code));
    } on Object {
      return const GoogleAuthFailed(
          'Could not reach Google. Check your connection and try again.');
    }
  }

  @override
  Future<void> clearSdkState() async {
    final Future<void>? ready = _ready;
    if (ready == null) {
      return;
    }
    try {
      await ready;
      await GoogleSignIn.instance.signOut();
    } on Object {
      // Best effort: a failed SDK sign-out must never block leaving the picker.
    }
  }

  /// The one `initialize()` call; every later entry reuses it. The SDK is
  /// only touched from a button tap, so this stays lazy.
  Future<void> _initialize() =>
      _ready ??= GoogleSignIn.instance.initialize(serverClientId: webClientId);

  static String _messageFor(GoogleSignInExceptionCode code) => switch (code) {
        GoogleSignInExceptionCode.clientConfigurationError =>
          'Google sign-in is not configured for this build.',
        GoogleSignInExceptionCode.providerConfigurationError =>
          'Google sign-in is unavailable on this device.',
        _ => 'Google sign-in failed. Please try again.',
      };
}

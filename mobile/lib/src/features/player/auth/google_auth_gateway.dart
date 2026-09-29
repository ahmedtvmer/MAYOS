import 'dart:async';

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

  /// Drops the SDK's own sign-in state, so leaving a half-finished sign-up
  /// leaves nothing behind on the device.
  Future<void> clearSdkState();
}

/// The real `google_sign_in` v7 adapter.
///
/// One `initialize(serverClientId: GOOGLE_WEB_CLIENT_ID)`, `authenticate()` for
/// the ID token, and no scopes: MAYOS only ever needs to know who the person
/// is (#113).
class GoogleSdkAuthGateway implements GoogleAuthGateway {
  /// The single build-time configuration, supplied as
  /// `--dart-define=GOOGLE_WEB_CLIENT_ID=...`. Never hard-coded: without it
  /// Google sign-in stays switched off and the button stays hidden.
  static const String webClientId =
      String.fromEnvironment('GOOGLE_WEB_CLIENT_ID');

  Future<void>? _ready;
  GoogleSignInAccount? _account;

  bool get _configured => webClientId.isNotEmpty;

  /// Whether the SDK currently holds a signed-in account, as reported by
  /// `authenticationEvents` — the v7 source of truth for SDK sign-in state.
  bool get hasSdkAccount => _account != null;

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
      _account = account;
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
      _account = null;
    } on Object {
      // Best effort: a failed SDK sign-out must never block leaving the picker.
    }
  }

  Future<void> _initialize() => _ready ??= _start();

  Future<void> _start() async {
    await GoogleSignIn.instance.initialize(serverClientId: webClientId);
    // `authenticationEvents` is the source of truth for the SDK's sign-in
    // state: on the platforms that expose no event stream of their own the
    // package synthesizes these events from `authenticate()`/`signOut()`. The
    // gateway is an app-lifetime singleton, so the listener outlives it.
    GoogleSignIn.instance.authenticationEvents.listen(
      (GoogleSignInAuthenticationEvent event) {
        if (event is GoogleSignInAuthenticationEventSignIn) {
          _account = event.user;
        } else if (event is GoogleSignInAuthenticationEventSignOut) {
          _account = null;
        }
      },
      onError: (Object _) {},
    );
  }

  static String _messageFor(GoogleSignInExceptionCode code) => switch (code) {
        GoogleSignInExceptionCode.clientConfigurationError =>
          'Google sign-in is not configured for this build.',
        GoogleSignInExceptionCode.providerConfigurationError =>
          'Google sign-in is unavailable on this device.',
        _ => 'Google sign-in failed. Please try again.',
      };
}

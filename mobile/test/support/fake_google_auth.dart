import 'dart:async';

import 'package:flutter/material.dart';
import 'package:mayos_mobile/src/core/theme/mayos_spacing.dart';
import 'package:mayos_mobile/src/features/player/auth/google_auth_gateway.dart';

/// A scripted stand-in for the Google SDK, so the sign-in flows run without a
/// platform channel (#115).
class FakeGoogleAuthGateway implements GoogleAuthGateway {
  FakeGoogleAuthGateway({this.buttonStyle = GoogleSignInButtonStyle.appRendered});

  @override
  GoogleSignInButtonStyle buttonStyle;

  /// The ID token the next [authenticate] hands back; null means the person
  /// dismissed the sheet.
  String? idToken = 'fake-google-id-token';

  /// Set to script a failure instead of a token or a dismissal.
  GoogleAuthOutcome? scriptedOutcome;

  final StreamController<GoogleAuthOutcome> _authenticationEvents =
      StreamController<GoogleAuthOutcome>.broadcast(sync: true);

  int authenticateCalls = 0;
  int clearSdkStateCalls = 0;
  int webButtonBuildCalls = 0;
  double? renderedButtonWidth;
  bool? renderedButtonDarkTheme;

  @override
  Stream<GoogleAuthOutcome> get authenticationEvents =>
      _authenticationEvents.stream;

  void emitAuthenticationOutcome(GoogleAuthOutcome outcome) {
    _authenticationEvents.add(outcome);
  }

  @override
  Widget buildWebButton({required bool darkTheme, required double width}) {
    webButtonBuildCalls += 1;
    renderedButtonWidth = width;
    renderedButtonDarkTheme = darkTheme;
    return SizedBox(
        key: const Key('fake_google_web_button'),
        height: kMayosMinTapTarget,
        width: width,
        child: const ColoredBox(color: Colors.transparent),
      );
  }

  @override
  Future<GoogleAuthOutcome> authenticate() async {
    authenticateCalls += 1;
    final GoogleAuthOutcome? scripted = scriptedOutcome;
    if (scripted != null) {
      return scripted;
    }
    final String? token = idToken;
    if (token == null) {
      return const GoogleAuthCanceled();
    }
    return GoogleAuthIdToken(token);
  }

  @override
  Future<void> clearSdkState() async {
    clearSdkStateCalls += 1;
  }
}

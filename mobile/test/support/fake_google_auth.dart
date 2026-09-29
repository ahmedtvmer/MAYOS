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

  int authenticateCalls = 0;
  int clearSdkStateCalls = 0;

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

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../../core/app_failure.dart';
import '../../../providers.dart';
import '../../../router.dart';
import 'auth_controller.dart';
import 'google_auth_gateway.dart';

/// The shared "Continue with Google" wiring for the sign-in screens (#115).
///
/// Login and register keep one navigation and error policy, and one busy flag
/// that backs **only** the Google button — a password submit leaves it idle, so
/// the two buttons never spin for each other.
mixin GoogleSignInAction<T extends ConsumerStatefulWidget> on ConsumerState<T> {
  bool _googleBusy = false;
  FailureMessage? _googleFailure;

  /// True while the Google flow is in flight; drives the button spinner.
  bool get googleBusy => _googleBusy;

  /// The last Google failure this screen should show, if any.
  FailureMessage? get googleFailure => _googleFailure;

  /// Routes first sign-in to its nudge or picker, a refusal to an inline
  /// notice, and ignores a dismissal or a session the router already handles.
  Future<void> continueWithGoogle() async {
    await _runGoogleFlow(
        () => ref.read(authControllerProvider.notifier).continueWithGoogle());
  }

  /// Handles Google's `authenticationEvents` when the web button completes.
  Future<void> continueWithGoogleOutcome(GoogleAuthOutcome outcome) async {
    await _runGoogleFlow(() => ref
        .read(authControllerProvider.notifier)
        .continueWithGoogleOutcome(outcome));
  }

  Future<void> _runGoogleFlow(
      Future<ContinueWithGoogleResult> Function() start) async {
    if (_googleBusy) {
      return;
    }
    setState(() {
      _googleBusy = true;
      _googleFailure = null;
    });
    try {
      final ContinueWithGoogleResult result = await start();
      if (!mounted) {
        return;
      }
      switch (result) {
        case GoogleSignUpPrompt():
          context.go(carryingLocation(context, googleSignupPath));
        case GoogleSignInRefused(:final message, :final failureMessage):
          setState(() =>
              _googleFailure = failureMessage ?? ServerFailureMessage(message));
        case GoogleSignInDone():
        case GoogleSignInDismissed():
          break;
      }
    } finally {
      if (mounted) {
        setState(() => _googleBusy = false);
      }
    }
  }
}

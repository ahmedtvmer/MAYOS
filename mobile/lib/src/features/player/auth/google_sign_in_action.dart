import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../../providers.dart';
import '../../../router.dart';
import 'auth_controller.dart';

/// The shared "Continue with Google" wiring for the sign-in screens (#115).
///
/// Login and register keep one navigation and error policy, and one busy flag
/// that backs **only** the Google button — a password submit leaves it idle, so
/// the two buttons never spin for each other.
mixin GoogleSignInAction<T extends ConsumerStatefulWidget> on ConsumerState<T> {
  bool _googleBusy = false;
  String? _googleError;

  /// True while the Google flow is in flight; drives the button spinner.
  bool get googleBusy => _googleBusy;

  /// The last Google failure this screen should show, if any.
  String? get googleError => _googleError;

  /// Runs the flow and routes each outcome: the picker for a first sign-in,
  /// an inline notice for a refusal, nothing for a dismissal or a session that
  /// the router already reacts to.
  Future<void> continueWithGoogle() async {
    if (_googleBusy) {
      return;
    }
    setState(() {
      _googleBusy = true;
      _googleError = null;
    });
    try {
      final ContinueWithGoogleResult result =
          await ref.read(authControllerProvider.notifier).continueWithGoogle();
      if (!mounted) {
        return;
      }
      switch (result) {
        case GoogleSignUpPrompt():
          context.go(withCarry(
            googleSignupPath,
            carryTargetFromUri(GoRouterState.of(context).uri),
          ));
        case GoogleSignInRefused(:final message):
          setState(() => _googleError = message);
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

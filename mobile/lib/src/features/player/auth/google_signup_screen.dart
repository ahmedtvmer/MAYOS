import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../../core/api_client.dart';
import '../../../core/theme/mayos_spacing.dart';
import '../../../core/theme/mayos_theme.dart';
import '../../../core/theme/mayos_typography.dart';
import '../../../core/ui/mayos_button.dart';
import '../../../core/ui/mayos_text_field.dart';
import '../../../providers.dart';
import '../../../router.dart';
import 'auth_controller.dart';
import 'auth_widgets.dart';

/// The picker a first Google sign-in lands on (#115).
///
/// It opens prefilled with the service's suggestion, validates the username
/// rule live, checks availability on a debounce, and only then creates the
/// account behind the pending signup ticket. Leaving without submitting
/// creates nothing and drops the Google SDK's own state.
class GoogleSignupScreen extends ConsumerStatefulWidget {
  const GoogleSignupScreen({super.key});

  @override
  ConsumerState<GoogleSignupScreen> createState() => _GoogleSignupScreenState();
}

/// The picker's rule, mirrored from `service/google_sign_in.py`: 3–30 of
/// `a–z 0–9 _ -`, lowercase.
final RegExp googleUsernamePattern = RegExp(r'^[a-z0-9_-]{3,30}$');

/// Null when [value] is a pickable username, else the visible format error.
String? googleUsernameFormatError(String value) =>
    googleUsernamePattern.hasMatch(value)
        ? null
        : 'Use 3–30 characters from a–z, 0–9, _ and - (lowercase).';

const String _kTakenMessage = 'That username is taken.';

enum _UsernameCheck { idle, checking, available, taken, unverified }

class _GoogleSignupScreenState extends ConsumerState<GoogleSignupScreen> {
  final TextEditingController _username = TextEditingController();
  late final AuthController _auth;
  Timer? _debounce;
  bool _touched = false;
  bool _busy = false;
  _UsernameCheck _check = _UsernameCheck.idle;
  String? _error;

  String _loginLocation() => carryingLocation(context, loginPath);

  @override
  void initState() {
    super.initState();
    _auth = ref.read(authControllerProvider.notifier);
    final PendingGoogleSignup? pending = _auth.pendingSignup;
    final String suggestion = pending?.suggestedUsername ?? '';
    if (googleUsernameFormatError(suggestion) == null) {
      _username.text = suggestion;
      _check = _UsernameCheck.checking;
      _scheduleCheck();
    }
  }

  @override
  void dispose() {
    _debounce?.cancel();
    _username.dispose();
    // Nothing was created if the picker never submitted: drop the pending
    // ticket and the Google SDK's own sign-in state (#115).
    unawaited(_auth.abandonGoogleSignup());
    super.dispose();
  }

  void _scheduleCheck() {
    _debounce?.cancel();
    _debounce = Timer(const Duration(milliseconds: 400), _checkAvailability);
  }

  void _onChanged(String value) {
    _touched = true;
    _error = null;
    if (googleUsernameFormatError(value.trim()) != null) {
      _debounce?.cancel();
      setState(() => _check = _UsernameCheck.idle);
      return;
    }
    setState(() => _check = _UsernameCheck.checking);
    _scheduleCheck();
  }

  Future<void> _checkAvailability() async {
    final String username = _username.text.trim();
    if (googleUsernameFormatError(username) != null) {
      return;
    }
    try {
      final bool available = await _auth.googleUsernameAvailable(username);
      // The field may have moved on while the probe was in flight; an answer
      // about an older value must never label the current one (#115).
      if (!mounted || _username.text.trim() != username) {
        return;
      }
      setState(() {
        _check = available ? _UsernameCheck.available : _UsernameCheck.taken;
      });
    } on ApiException catch (error) {
      if (!mounted) {
        return;
      }
      // A dead ticket is the same exit as a dead ticket on submit: back to
      // sign-in with the short explanation (#115).
      if (error.statusCode == 401) {
        await _auth.abandonGoogleSignup(notice: kGoogleSignupExpiredMessage);
        if (mounted) {
          context.go(_loginLocation());
        }
        return;
      }
      // Any other failure must not block the picker: the service re-checks on
      // submit, where a taken name answers 409.
      setState(() => _check = _UsernameCheck.unverified);
    }
  }

  bool get _formatValid =>
      googleUsernameFormatError(_username.text.trim()) == null;

  bool get _canSubmit =>
      !_busy &&
      _formatValid &&
      _check != _UsernameCheck.checking &&
      _check != _UsernameCheck.taken;

  String? get _fieldError {
    if (_touched) {
      final String? formatError =
          googleUsernameFormatError(_username.text.trim());
      if (formatError != null) {
        return formatError;
      }
    }
    return _check == _UsernameCheck.taken ? _kTakenMessage : null;
  }

  String? get _fieldHelper {
    switch (_check) {
      case _UsernameCheck.checking:
        return 'Checking availability…';
      case _UsernameCheck.available:
        return 'This username is free.';
      case _UsernameCheck.unverified:
        return 'Could not check availability.';
      case _UsernameCheck.idle:
      case _UsernameCheck.taken:
        return null;
    }
  }

  Future<void> _submit() async {
    if (!_canSubmit) {
      setState(() => _touched = true);
      return;
    }
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      final CompleteGoogleSignupResult result =
          await _auth.completeGoogleSignup(username: _username.text.trim());
      if (!mounted) {
        return;
      }
      switch (result) {
        case GoogleSignupDone():
          TextInput.finishAutofillContext();
        case GoogleUsernameTaken():
          setState(() => _check = _UsernameCheck.taken);
        case GoogleAccountAlreadyLinked():
          context.go(_loginLocation());
        case GoogleSignupTicketExpired():
          context.go(_loginLocation());
        case GoogleSignupRefused(:final message):
          setState(() => _error = message);
      }
    } finally {
      if (mounted) {
        setState(() => _busy = false);
      }
    }
  }

  Future<void> _leaveToLogin() async {
    await _auth.abandonGoogleSignup();
    if (mounted) {
      context.go(_loginLocation());
    }
  }

  @override
  Widget build(BuildContext context) {
    final PendingGoogleSignup? pending = _auth.pendingSignup;
    if (pending == null) {
      return _expiredView();
    }
    return AuthScaffold(
      title: 'Choose your username',
      lead: 'Pick the name you want to train under. It must be free.',
      wallpaper: true,
      message: _error == null ? null : AuthInlineNotice(message: _error!),
      primary: MayosButton(
        key: const Key('google_signup_submit'),
        label: 'Create account',
        loading: _busy,
        onPressed: _canSubmit ? _submit : null,
      ),
      links: <Widget>[
        AuthLink(
          key: const Key('google_signup_cancel'),
          label: 'Back to sign in',
          onPressed: _busy ? null : _leaveToLogin,
        ),
      ],
      children: <Widget>[
        MayosTextField(
          fieldKey: const Key('google_signup_username'),
          controller: _username,
          label: 'Username',
          enabled: !_busy,
          autocorrect: false,
          enableSuggestions: false,
          textInputAction: TextInputAction.done,
          keyboardType: TextInputType.text,
          autofillHints: const <String>[AutofillHints.newUsername],
          helperText: _fieldHelper,
          errorText: _fieldError,
          onChanged: _onChanged,
          onSubmitted: (_) => _submit(),
        ),
        const SizedBox(height: MayosSpacing.md),
        AuthLink(
          key: const Key('google_signup_login_link'),
          label:
              'Already have a MAYOS account? Log in with your password, then connect Google in Settings',
          onPressed: _busy ? null : _leaveToLogin,
        ),
      ],
    );
  }

  /// The pending ticket is only ever missing when the flow was interrupted:
  /// say so instead of showing an empty form.
  Widget _expiredView() {
    final MayosThemeExtension c = MayosTheme.of(context);
    return AuthScaffold(
      title: 'Choose your username',
      wallpaper: true,
      message: const AuthInlineNotice(message: kGoogleSignupExpiredMessage),
      primary: MayosButton(
        key: const Key('google_signup_submit'),
        label: 'Back to sign in',
        onPressed: () => context.go(_loginLocation()),
      ),
      children: <Widget>[
        Text(
          'The Google sign-in could not be finished, so no account was created.',
          style: MayosTypography.bodySecondary
              .copyWith(color: c.textSecondary, height: 1.5),
        ),
      ],
    );
  }
}

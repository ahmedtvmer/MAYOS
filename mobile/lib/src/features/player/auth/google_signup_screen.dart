import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../../core/api_client.dart';
import '../../../core/display_language/catalog.dart';
import '../../../core/display_language/controller.dart';
import '../../../core/theme/mayos_spacing.dart';
import '../../../core/theme/mayos_theme.dart';
import '../../../core/theme/mayos_typography.dart';
import '../../../core/ui/mayos_button.dart';
import '../../../core/ui/mayos_text_field.dart';
import '../../../providers.dart';
import '../../../router.dart';
import 'auth_controller.dart';
import 'auth_widgets.dart';

/// The nudge or username picker for a first Google sign-in (#115/#174).
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

enum _UsernameCheck { idle, checking, available, taken, unverified }

class _GoogleSignupScreenState extends ConsumerState<GoogleSignupScreen> {
  final TextEditingController _username = TextEditingController();
  late final AuthController _auth;
  Timer? _debounce;
  bool _touched = false;
  bool _showPicker = false;
  bool _busy = false;
  _UsernameCheck _check = _UsernameCheck.idle;
  String? _error;

  String _loginLocation() => carryingLocation(context, loginPath);

  @override
  void initState() {
    super.initState();
    _auth = ref.read(authControllerProvider.notifier);
    final PendingGoogleSignup? pending = _auth.pendingSignup;
    if (pending?.existingAccountHint != true && _prefillSuggestion()) {
      _check = _UsernameCheck.checking;
      _scheduleCheck();
    }
  }

  bool _prefillSuggestion() {
    final String suggestion = _auth.pendingSignup?.suggestedUsername ?? '';
    if (googleUsernameFormatError(suggestion) != null) {
      return false;
    }
    _username.text = suggestion;
    return true;
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
        await _auth.abandonGoogleSignup(
            notice: MayosCopy(ref.read(displayLanguageProvider))
                .googleSignupExpired);
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
    final MayosCopy copy = MayosCopy(ref.read(displayLanguageProvider));
    if (_touched) {
      final String? formatError =
          googleUsernameFormatError(_username.text.trim());
      if (formatError != null) {
        return copy.usernameFormatError;
      }
    }
    return _check == _UsernameCheck.taken ? copy.usernameTaken : null;
  }

  String? get _fieldHelper {
    final MayosCopy copy = MayosCopy(ref.read(displayLanguageProvider));
    switch (_check) {
      case _UsernameCheck.checking:
        return copy.checkingAvailability;
      case _UsernameCheck.available:
        return copy.usernameAvailable;
      case _UsernameCheck.unverified:
        return copy.availabilityCheckFailed;
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
          await _auth.completeGoogleSignup(
              username: _username.text.trim(),
              displayLanguage: ref.read(displayLanguageProvider));
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

  void _createSeparateAccount() {
    if (!_prefillSuggestion()) {
      return;
    }
    setState(() {
      _showPicker = true;
      _check = _UsernameCheck.checking;
    });
    _scheduleCheck();
  }

  @override
  Widget build(BuildContext context) {
    return _withBackNavigation(_signupContent());
  }

  Widget _signupContent() {
    final MayosCopy copy = MayosCopy(ref.watch(displayLanguageProvider));
    final PendingGoogleSignup? pending = _auth.pendingSignup;
    if (pending == null) {
      return _expiredView();
    }
    if (pending.existingAccountHint && !_showPicker) {
      return _existingAccountHintView();
    }
    return AuthScaffold(
      title: copy.chooseUsername,
      lead: copy.chooseUsernameLead,
      wallpaper: true,
      message: _error == null ? null : AuthInlineNotice(message: _error!),
      primary: MayosButton(
        key: const Key('google_signup_submit'),
        label: copy.createAccount,
        loading: _busy,
        onPressed: _canSubmit ? _submit : null,
      ),
      links: <Widget>[
        AuthLink(
          key: const Key('google_signup_cancel'),
          label: copy.backToSignIn,
          onPressed: _busy ? null : _leaveToLogin,
        ),
      ],
      children: <Widget>[
        MayosTextField(
          fieldKey: const Key('google_signup_username'),
          controller: _username,
          label: copy.username,
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
          label: copy.existingAccountNudge,
          onPressed: _busy ? null : _leaveToLogin,
        ),
      ],
    );
  }

  Widget _withBackNavigation(Widget child) {
    return PopScope<Object?>(
      canPop: false,
      onPopInvokedWithResult: (bool didPop, Object? _) {
        if (!didPop) {
          unawaited(_leaveToLogin());
        }
      },
      child: child,
    );
  }

  Widget _existingAccountHintView() {
    final MayosCopy copy = MayosCopy(ref.watch(displayLanguageProvider));
    return AuthScaffold(
      title: copy.existingAccountTitle,
      lead: copy.existingAccountLead,
      wallpaper: true,
      primary: MayosButton(
        key: const Key('google_existing_account_login'),
        label: copy.logIn,
        onPressed: _leaveToLogin,
      ),
      children: <Widget>[
        MayosButton(
          key: const Key('google_existing_account_create_separate'),
          label: copy.createSeparateAccount,
          variant: MayosButtonVariant.secondary,
          onPressed: _createSeparateAccount,
        ),
      ],
    );
  }

  /// The pending ticket is only ever missing when the flow was interrupted:
  /// say so instead of showing an empty form.
  Widget _expiredView() {
    final MayosThemeExtension c = MayosTheme.of(context);
    final MayosCopy copy = MayosCopy(ref.watch(displayLanguageProvider));
    return AuthScaffold(
      title: copy.chooseUsername,
      wallpaper: true,
      message: AuthInlineNotice(message: copy.googleSignupExpired),
      primary: MayosButton(
        key: const Key('google_signup_submit'),
        label: copy.backToSignIn,
        onPressed: () => context.go(_loginLocation()),
      ),
      children: <Widget>[
        Text(
          copy.googleSignupIncomplete,
          style: MayosTypography.bodySecondary
              .copyWith(color: c.textSecondary, height: 1.5),
        ),
      ],
    );
  }
}

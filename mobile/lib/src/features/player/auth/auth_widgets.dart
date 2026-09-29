import 'package:flutter/material.dart';

import '../../../core/connectivity.dart';
import '../../../core/theme/mayos_spacing.dart';
import '../../../core/theme/mayos_theme.dart';
import '../../../core/theme/mayos_typography.dart';
import '../../../core/ui/mayos_button.dart';
import '../../../core/ui/mayos_logo.dart';
import '../../../core/ui/mayos_text_field.dart';
import '../../../core/ui/mayos_wallpaper.dart';

/// The shared MAYOS composition for the authentication and recovery screens.
///
/// It mirrors the onboarding shell: a brand-lockup hero, an editorial serif
/// heading with a short sans line, scrolling content, and a deliberate bottom
/// action bar that stays above the keyboard. No screen invents its own chrome.

/// The auth/recovery page frame.
///
/// The body scrolls (so fields stay reachable at large text scales and small
/// phones) while the action bar is pinned inside the resized body, keeping the
/// primary action visible when the keyboard is open.
///
/// Keyboard behaviour: when the keyboard is open the hero is dropped on short
/// screens, the tertiary links move to the end of the scrollable content, and
/// the pinned bar keeps only the compact primary action so the fields stay
/// visible.
class AuthScaffold extends StatelessWidget {
  const AuthScaffold({
    super.key,
    required this.title,
    required this.children,
    required this.primary,
    this.lead,
    this.links = const <Widget>[],
    this.message,
    this.wallpaper = false,
    this.homeScreenInstallHint,
  });

  final String title;
  final String? lead;
  final List<Widget> children;
  final Widget primary;
  final List<Widget> links;

  /// An optional inline notice shown pinned above the primary action.
  final Widget? message;

  /// Draws the dark gym photo backdrop (#110) and forces the white lockup and
  /// the wallpaper theme. Only the logged-out sign-in surfaces opt in; the
  /// recovery-email gate stays plain and theme-following.
  final bool wallpaper;

  /// Optional, fixed-height Home Screen hint slot for login and registration.
  final Widget? homeScreenInstallHint;

  @override
  Widget build(BuildContext context) {
    final MayosThemeExtension c = MayosTheme.of(context);
    final bool keyboardOpen = MediaQuery.viewInsetsOf(context).bottom > 0;
    // On short screens the hero would push the fields and CTA out of the
    // shrunken viewport, so it is dropped while the keyboard is open.
    final bool showHero =
        !(keyboardOpen && MediaQuery.sizeOf(context).height < 700);
    final Widget scaffold = Scaffold(
      backgroundColor: wallpaper ? Colors.transparent : c.canvas,
      resizeToAvoidBottomInset: true,
      body: SafeArea(
        // A phone-width column on desktop (#133); a no-op on phones. Applied at
        // every width so the fields' widget tree never changes shape.
        child: Align(
          alignment: Alignment.topCenter,
          child: ConstrainedBox(
            constraints: const BoxConstraints(
                maxWidth: MayosLayout.playerColumnMaxWidth),
            child: AutofillGroup(
              child: Column(
                children: <Widget>[
                  const OfflineBannerSlot(),
                  Expanded(
                    child: LayoutBuilder(
                      builder:
                          (BuildContext context, BoxConstraints constraints) {
                        final double byWidth = constraints.maxWidth * 0.42;
                        final double byHeight = constraints.maxHeight * 0.17;
                        final double logoHeight =
                            (byWidth < byHeight ? byWidth : byHeight)
                                .clamp(72.0, 120.0);
                        return SingleChildScrollView(
                          keyboardDismissBehavior:
                              ScrollViewKeyboardDismissBehavior.onDrag,
                          padding: EdgeInsets.fromLTRB(
                            MayosSpacing.lg,
                            keyboardOpen ? MayosSpacing.sm : MayosSpacing.md,
                            MayosSpacing.lg,
                            MayosSpacing.lg,
                          ),
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: <Widget>[
                              // One fixed slot, never a conditional spread: shifting
                              // the fields' positions rebuilds them, dropping focus
                              // and closing the keyboard (an open/close loop on
                              // mobile Safari).
                              Visibility(
                                visible: showHero,
                                child: Padding(
                                  padding: const EdgeInsets.only(
                                      bottom: MayosSpacing.xl),
                                  child: Center(
                                    child: MayosBrandLockup(
                                      height: logoHeight,
                                      variant: wallpaper
                                          ? MayosBrandVariant.white
                                          : MayosBrandVariant.auto,
                                    ),
                                  ),
                                ),
                              ),
                              if (homeScreenInstallHint != null)
                                SizedBox(
                                  height: keyboardOpen
                                      ? 0.0
                                      : kMayosMinTapTarget + MayosSpacing.xs,
                                  child: keyboardOpen
                                      ? const SizedBox.shrink()
                                      : homeScreenInstallHint,
                                ),
                              AuthHeading(title: title, lead: lead),
                              const SizedBox(height: MayosSpacing.xl),
                              ...children,
                              if (keyboardOpen && links.isNotEmpty) ...<Widget>[
                                const SizedBox(height: MayosSpacing.md),
                                Wrap(
                                  alignment: WrapAlignment.center,
                                  spacing: MayosSpacing.xs,
                                  runSpacing: MayosSpacing.xxs,
                                  children: links,
                                ),
                              ],
                            ],
                          ),
                        );
                      },
                    ),
                  ),
                  AuthActionBar(
                    primary: primary,
                    message: message,
                    links: keyboardOpen ? const <Widget>[] : links,
                    compact: keyboardOpen,
                    wallpaper: wallpaper,
                  ),
                ],
              ),
            ),
          ),
        ),
      ),
    );
    if (!wallpaper) {
      return scaffold;
    }
    return Theme(
      data: MayosTheme.wallpaper,
      child: MayosWallpaper(child: scaffold),
    );
  }
}

/// The editorial serif heading and its short sans explanation.
class AuthHeading extends StatelessWidget {
  const AuthHeading({super.key, required this.title, this.lead});

  final String title;
  final String? lead;

  @override
  Widget build(BuildContext context) {
    final MayosThemeExtension c = MayosTheme.of(context);
    final double width = MediaQuery.sizeOf(context).width;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: <Widget>[
        Text(
          title,
          style: MayosTypography.pageHeading.copyWith(
            color: c.textPrimary,
            fontSize: width < 400 ? 28 : 32,
            height: 1.12,
          ),
        ),
        if (lead != null) ...<Widget>[
          const SizedBox(height: MayosSpacing.sm),
          Text(
            lead!,
            style: MayosTypography.bodySecondary.copyWith(
              color: c.textSecondary,
              height: 1.5,
            ),
          ),
        ],
      ],
    );
  }
}

enum AuthNoticeKind { error, success, info }

/// An inline, left-aligned message for local validation and server responses.
class AuthInlineNotice extends StatelessWidget {
  const AuthInlineNotice({
    super.key,
    required this.message,
    this.kind = AuthNoticeKind.error,
  });

  final String message;
  final AuthNoticeKind kind;

  @override
  Widget build(BuildContext context) {
    final MayosThemeExtension c = MayosTheme.of(context);
    final (Color color, IconData icon) = switch (kind) {
      AuthNoticeKind.error => (c.danger, Icons.error_outline),
      AuthNoticeKind.success => (c.success, Icons.check_circle_outline),
      AuthNoticeKind.info => (c.textSecondary, Icons.info_outline),
    };
    return Semantics(
      liveRegion: true,
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          Icon(icon, size: 16, color: color),
          const SizedBox(width: MayosSpacing.xs),
          Expanded(
            child: Text(
              message,
              style: MayosTypography.bodySecondary.copyWith(color: color),
            ),
          ),
        ],
      ),
    );
  }
}

/// The pinned bottom action bar: an optional notice, the primary action, and
/// quiet links. It sits inside the resized body so the keyboard never hides it.
class AuthActionBar extends StatelessWidget {
  const AuthActionBar({
    super.key,
    required this.primary,
    this.message,
    this.links = const <Widget>[],
    this.compact = false,
    this.wallpaper = false,
  });

  final Widget primary;
  final Widget? message;
  final List<Widget> links;

  /// Tightens the vertical padding when the keyboard is open.
  final bool compact;

  /// Drops the opaque surface so the photo shows behind the action bar.
  final bool wallpaper;

  @override
  Widget build(BuildContext context) {
    final MayosThemeExtension c = MayosTheme.of(context);
    return DecoratedBox(
      decoration: BoxDecoration(
        color: wallpaper ? Colors.transparent : c.canvas,
        border: wallpaper ? null : Border(top: BorderSide(color: c.border)),
      ),
      child: SafeArea(
        top: false,
        child: Padding(
          padding: EdgeInsets.fromLTRB(
            MayosSpacing.lg,
            compact ? MayosSpacing.xs : MayosSpacing.sm,
            MayosSpacing.lg,
            compact ? MayosSpacing.xs : MayosSpacing.md,
          ),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: <Widget>[
              if (message != null) ...<Widget>[
                message!,
                SizedBox(height: compact ? MayosSpacing.xs : MayosSpacing.sm),
              ],
              primary,
              if (links.isNotEmpty) ...<Widget>[
                const SizedBox(height: MayosSpacing.xxs),
                Wrap(
                  alignment: WrapAlignment.center,
                  spacing: MayosSpacing.xs,
                  children: links,
                ),
              ],
            ],
          ),
        ),
      ),
    );
  }
}

/// A compact, whole-row consent control (ADR 010 "Keep me signed in").
///
/// The indicator is aligned to the field's left edge, the label is body weight,
/// and the entire 48dp-high row is tappable with a checked semantics state.
class AuthConsentRow extends StatelessWidget {
  const AuthConsentRow({
    super.key,
    required this.label,
    required this.value,
    required this.onChanged,
    this.enabled = true,
  });

  final String label;
  final bool value;
  final ValueChanged<bool>? onChanged;
  final bool enabled;

  @override
  Widget build(BuildContext context) {
    final MayosThemeExtension c = MayosTheme.of(context);
    final bool interactive = enabled && onChanged != null;
    final Color labelColor = interactive ? c.textPrimary : c.textDisabled;
    final VoidCallback? toggle = interactive ? () => onChanged!(!value) : null;
    return Semantics(
      container: true,
      checked: value,
      enabled: interactive,
      label: label,
      onTap: toggle,
      child: ExcludeSemantics(
        child: InkWell(
          onTap: toggle,
          borderRadius: MayosRadii.smallRadius,
          child: ConstrainedBox(
            constraints: const BoxConstraints(minHeight: 48),
            child: Row(
              children: <Widget>[
                _ConsentCheckbox(value: value, enabled: interactive),
                const SizedBox(width: MayosSpacing.sm),
                Expanded(
                  child: Text(
                    label,
                    style: MayosTypography.body.copyWith(color: labelColor),
                  ),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

class _ConsentCheckbox extends StatelessWidget {
  const _ConsentCheckbox({required this.value, required this.enabled});

  final bool value;
  final bool enabled;

  @override
  Widget build(BuildContext context) {
    final MayosThemeExtension c = MayosTheme.of(context);
    final Color borderColor =
        value ? c.accent : (enabled ? c.borderStrong : c.textDisabled);
    return AnimatedContainer(
      duration: MayosMotion.fast,
      curve: MayosMotion.standard,
      width: 20,
      height: 20,
      decoration: BoxDecoration(
        color: value ? c.accent : Colors.transparent,
        borderRadius: BorderRadius.circular(6),
        border: Border.all(color: borderColor, width: 1.5),
      ),
      child: value
          ? Icon(Icons.check, size: 14, color: c.onAccent)
          : const SizedBox.shrink(),
    );
  }
}

/// The client-side new-password rules, shared by register and reset so
/// the same rule is worded identically on every screen.
const int kMinPasswordLength = 8;
const String kPasswordMinLengthMessage = 'Use at least 8 characters.';
const String kPasswordMismatchMessage = 'Passwords do not match.';

/// The min-length check for a chosen password, or null when it is long enough.
String? passwordLengthError(String password) =>
    password.length < kMinPasswordLength ? kPasswordMinLengthMessage : null;

/// The confirmation check, or null when the two entries match.
String? passwordConfirmationError(String password, String confirm) =>
    password == confirm ? null : kPasswordMismatchMessage;

/// The shared new-password validator: the length rule first, then the match
/// rule, or null when both pass.
String? validateNewPassword(String password, String confirm) =>
    passwordLengthError(password) ??
    passwordConfirmationError(password, confirm);

/// A password input with an obscured default and a labelled visibility toggle.
class AuthPasswordField extends StatefulWidget {
  const AuthPasswordField({
    super.key,
    required this.controller,
    this.label = 'Password',
    this.helperText,
    this.errorText,
    this.textInputAction,
    this.autofillHints,
    this.focusNode,
    this.onSubmitted,
    this.fieldKey,
    this.toggleKey,
  });

  final TextEditingController controller;
  final String label;
  final String? helperText;
  final String? errorText;
  final TextInputAction? textInputAction;
  final Iterable<String>? autofillHints;
  final FocusNode? focusNode;
  final ValueChanged<String>? onSubmitted;
  final Key? fieldKey;
  final Key? toggleKey;

  @override
  State<AuthPasswordField> createState() => _AuthPasswordFieldState();
}

class _AuthPasswordFieldState extends State<AuthPasswordField> {
  bool _obscure = true;

  @override
  Widget build(BuildContext context) {
    return MayosTextField(
      fieldKey: widget.fieldKey,
      controller: widget.controller,
      label: widget.label,
      helperText: widget.helperText,
      errorText: widget.errorText,
      obscureText: _obscure,
      keyboardType: TextInputType.visiblePassword,
      textInputAction: widget.textInputAction,
      autofillHints: widget.autofillHints,
      autocorrect: false,
      enableSuggestions: false,
      focusNode: widget.focusNode,
      onSubmitted: widget.onSubmitted,
      suffixIcon: IconButton(
        key: widget.toggleKey,
        tooltip: _obscure ? 'Show password' : 'Hide password',
        onPressed: () => setState(() => _obscure = !_obscure),
        icon: Icon(
          _obscure ? Icons.visibility_outlined : Icons.visibility_off_outlined,
          size: 20,
        ),
      ),
    );
  }
}

/// A quiet link built from the shared tertiary button.
class AuthLink extends StatelessWidget {
  const AuthLink({super.key, required this.label, required this.onPressed});

  final String label;
  final VoidCallback? onPressed;

  @override
  Widget build(BuildContext context) {
    return MayosButton(
      label: label,
      variant: MayosButtonVariant.tertiary,
      expand: false,
      onPressed: onPressed,
    );
  }
}

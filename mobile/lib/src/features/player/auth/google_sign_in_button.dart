import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/theme/mayos_spacing.dart';
import '../../../core/theme/mayos_theme.dart';
import '../../../core/theme/mayos_typography.dart';
import '../../../providers.dart';
import 'google_auth_gateway.dart';

/// Google's published brand colours for the sign-in button and the "G" mark
/// (#115).
///
/// This is the documented exception to "no literal hex colours outside
/// `core/theme/`" (see `mobile/DESIGN.md`): a third-party mark must render
/// exactly as published, so its palette lives in one commented block here
/// instead of being folded into `MayosPalette`.
abstract final class GoogleBrand {
  /// The four standard "G" segments (Google branding guidelines).
  static const Color red = Color(0xFFEA4335);
  static const Color yellow = Color(0xFFFBBC05);
  static const Color green = Color(0xFF34A853);
  static const Color blue = Color(0xFF4285F4);

  /// Button *light* theme: white fill, #747775 stroke, #1F1F1F label.
  static const Color lightFill = Color(0xFFFFFFFF);
  static const Color lightStroke = Color(0xFF747775);
  static const Color lightLabel = Color(0xFF1F1F1F);

  /// Button *dark* theme: #131314 fill, #8E918F stroke, #E3E3E3 label.
  static const Color darkFill = Color(0xFF131314);
  static const Color darkStroke = Color(0xFF8E918F);
  static const Color darkLabel = Color(0xFFE3E3E3);
}

/// The Google option and the rule that separates it from the password form
/// (#115).
///
/// It renders nothing on a build or platform that cannot offer Google
/// sign-in, so hiding the button is decided in exactly one place:
/// [GoogleAuthGateway.buttonStyle].
class GoogleSignInSection extends ConsumerWidget {
  const GoogleSignInSection({
    super.key,
    required this.onPressed,
    required this.onWebOutcome,
    this.loading = false,
  });

  /// Starts "Continue with Google"; null disables the button.
  final Future<void> Function()? onPressed;

  /// Handles authentication events from Google's rendered web button.
  final Future<void> Function(GoogleAuthOutcome outcome) onWebOutcome;

  /// Swaps the label for a spinner while a sign-in is in flight.
  final bool loading;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final GoogleAuthGateway gateway = ref.watch(googleAuthGatewayProvider);
    if (gateway.buttonStyle == GoogleSignInButtonStyle.hidden) {
      return const SizedBox.shrink();
    }
    final Widget button = gateway.buttonStyle ==
            GoogleSignInButtonStyle.webRendered
        ? GoogleWebSignInButton(
            loading: loading,
            onOutcome: onWebOutcome,
          )
        : GoogleSignInButton(onPressed: onPressed, loading: loading);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: <Widget>[
        button,
        const SizedBox(height: MayosSpacing.md),
        const AuthOrDivider(),
        const SizedBox(height: MayosSpacing.md),
      ],
    );
  }
}

/// A fixed-height, centred host for Google's web-rendered button.
class GoogleWebSignInButton extends ConsumerStatefulWidget {
  const GoogleWebSignInButton({
    super.key,
    required this.onOutcome,
    this.fixedWidth,
    this.loading = false,
  });

  final Future<void> Function(GoogleAuthOutcome outcome) onOutcome;
  final double? fixedWidth;
  final bool loading;

  @override
  ConsumerState<GoogleWebSignInButton> createState() =>
      _GoogleWebSignInButtonState();
}

class _GoogleWebSignInButtonState extends ConsumerState<GoogleWebSignInButton> {
  StreamSubscription<GoogleAuthOutcome>? _events;
  GoogleAuthGateway? _cachedGateway;
  bool? _cachedDarkTheme;
  double? _cachedWidth;
  Widget? _cachedWebButton;

  @override
  void initState() {
    super.initState();
    final GoogleAuthGateway gateway = ref.read(googleAuthGatewayProvider);
    if (gateway.buttonStyle == GoogleSignInButtonStyle.webRendered) {
      _events = gateway.authenticationEvents.listen(
        (GoogleAuthOutcome outcome) => unawaited(widget.onOutcome(outcome)),
        onError: (Object error, StackTrace stack) {
          if (mounted) {
            unawaited(widget.onOutcome(const GoogleAuthFailed(
                'Could not reach Google. Check your connection and try again.')));
          }
        },
      );
    }
  }

  @override
  void dispose() {
    _events?.cancel();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final GoogleAuthGateway gateway = ref.watch(googleAuthGatewayProvider);
    if (gateway.buttonStyle != GoogleSignInButtonStyle.webRendered) {
      return const SizedBox.shrink();
    }
    final bool darkTheme = Theme.of(context).brightness == Brightness.dark;
    final double? fixedWidth = widget.fixedWidth;
    if (fixedWidth != null) {
      return _button(gateway, darkTheme, fixedWidth);
    }
    return LayoutBuilder(
      builder: (BuildContext context, BoxConstraints constraints) {
        final double width = constraints.maxWidth.isFinite
            ? constraints.maxWidth
            : MayosLayout.googleButtonMaxWidth;
        return _button(gateway, darkTheme, width);
      },
    );
  }

  Widget _button(
    GoogleAuthGateway gateway,
    bool darkTheme,
    double availableWidth,
  ) {
    final double? width = _widthBucket(availableWidth);
    if (width == null) {
      return const SizedBox(height: kMayosMinTapTarget);
    }
    _updateCachedButton(gateway, darkTheme, width);
    return _buttonSlot(width, _cachedWebButton!);
  }

  double? _widthBucket(double availableWidth) {
    final double width = availableWidth
        .clamp(0.0, MayosLayout.googleButtonMaxWidth)
        .floorToDouble();
    return width < MayosSpacing.xxs ? null : width;
  }

  void _updateCachedButton(
      GoogleAuthGateway gateway, bool darkTheme, double width) {
    if (!identical(_cachedGateway, gateway) ||
        _cachedDarkTheme != darkTheme ||
        _cachedWidth != width) {
      _cachedGateway = gateway;
      _cachedDarkTheme = darkTheme;
      _cachedWidth = width;
      _cachedWebButton =
          gateway.buildWebButton(darkTheme: darkTheme, width: width);
    }
  }

  Widget _buttonSlot(double width, Widget webButton) => SizedBox(
        height: kMayosMinTapTarget,
        child: Center(
          child: SizedBox(
            width: width,
            height: kMayosMinTapTarget,
            child: AbsorbPointer(
              absorbing: widget.loading,
              child: webButton,
            ),
          ),
        ),
      );
}

/// The full-width "Continue with Google" button (#115), following Google's
/// branding: the standard-colour "G", the approved wording, and the light or
/// dark theme that matches the surface it sits on.
class GoogleSignInButton extends StatelessWidget {
  const GoogleSignInButton({
    super.key,
    required this.onPressed,
    this.loading = false,
  });

  /// Starts "Continue with Google"; null disables the button.
  final Future<void> Function()? onPressed;

  /// Swaps the label for a spinner while a sign-in is in flight.
  final bool loading;

  @override
  Widget build(BuildContext context) {
    // Google allows one light and one dark theme; pick the one matching the
    // surface (the sign-in screens run on the dark wallpaper).
    final bool dark = Theme.of(context).brightness == Brightness.dark;
    final Color fill = dark ? GoogleBrand.darkFill : GoogleBrand.lightFill;
    final Color stroke =
        dark ? GoogleBrand.darkStroke : GoogleBrand.lightStroke;
    final Color labelColor =
        dark ? GoogleBrand.darkLabel : GoogleBrand.lightLabel;
    final bool enabled = onPressed != null && !loading;

    return Semantics(
      button: true,
      enabled: enabled,
      label: 'Continue with Google',
      child: SizedBox(
        width: double.infinity,
        child: Material(
          type: MaterialType.button,
          color: fill,
          clipBehavior: Clip.antiAlias,
          shape: RoundedRectangleBorder(
            borderRadius: MayosRadii.smallRadius,
            side: BorderSide(color: stroke, width: 1),
          ),
          child: InkWell(
            onTap: enabled ? () => onPressed!() : null,
            borderRadius: MayosRadii.smallRadius,
            child: SizedBox(
              height: kMayosMinTapTarget,
              child: Row(
                mainAxisAlignment: MainAxisAlignment.center,
                children: <Widget>[
                  if (loading)
                    SizedBox(
                      height: 18,
                      width: 18,
                      child: CircularProgressIndicator(
                        strokeWidth: 2,
                        color: labelColor,
                      ),
                    )
                  else ...<Widget>[
                    const GoogleGLogo(size: 18),
                    const SizedBox(width: 10),
                    Text(
                      'Continue with Google',
                      style: TextStyle(
                        fontFamily: MayosTypography.uiFamily,
                        fontSize: 14,
                        height: 20 / 14,
                        fontWeight: FontWeight.w500,
                        color: labelColor,
                      ),
                    ),
                  ],
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }
}

/// The standard-colour Google "G", drawn as four arcs plus the bar (#115).
class GoogleGLogo extends StatelessWidget {
  const GoogleGLogo({super.key, this.size = 18});

  final double size;

  @override
  Widget build(BuildContext context) =>
      CustomPaint(size: Size.square(size), painter: _GoogleGPainter());
}

/// The quiet "or" rule between the Google button and the password form (#115).
class AuthOrDivider extends StatelessWidget {
  const AuthOrDivider({super.key});

  @override
  Widget build(BuildContext context) {
    final MayosThemeExtension c = MayosTheme.of(context);
    return Row(
      children: <Widget>[
        Expanded(child: Divider(height: 1, thickness: 1, color: c.border)),
        Padding(
          padding: const EdgeInsets.symmetric(horizontal: MayosSpacing.sm),
          child: Text(
            'or',
            style: MayosTypography.bodySecondary.copyWith(color: c.textMuted),
          ),
        ),
        Expanded(child: Divider(height: 1, thickness: 1, color: c.border)),
      ],
    );
  }
}

/// Draws the "G" inside Google's own 48×48 coordinate box: a ring of outer
/// radius 24 and inner radius 14, split into the four brand segments, plus the
/// horizontal bar. Angles are screen degrees — 0° is east and positive turns
/// clockwise — and the segment boundaries are the ones Google's published mark
/// uses, so the mark reads correctly at the 18dp the button renders it at.
class _GoogleGPainter extends CustomPainter {
  static const Offset _centre = Offset(24, 24);
  static const double _inner = 14;
  static const double _outer = 24;

  @override
  void paint(Canvas canvas, Size size) {
    canvas.scale(size.width / 48, size.width / 48);
    // The bar runs to the rim; clipping keeps its square end on the circle.
    canvas.clipPath(
        Path()..addOval(Rect.fromCircle(center: _centre, radius: _outer)));
    canvas.drawPath(_arc(202.75, 311.2), Paint()..color = GoogleBrand.red);
    canvas.drawPath(_arc(147.5, 202.75), Paint()..color = GoogleBrand.yellow);
    canvas.drawPath(_arc(52.5, 147.5), Paint()..color = GoogleBrand.green);
    final Paint blue = Paint()..color = GoogleBrand.blue;
    canvas.drawPath(_arc(0, 52.5), blue);
    canvas.drawRect(const Rect.fromLTWH(24, 20, 24, 9), blue);
  }

  static Path _arc(double fromDegrees, double toDegrees) {
    const double toRadians = 3.141592653589793 / 180;
    final double sweep = (toDegrees - fromDegrees) * toRadians;
    return Path()
      ..arcTo(
        Rect.fromCircle(center: _centre, radius: _outer),
        fromDegrees * toRadians,
        sweep,
        true,
      )
      ..arcTo(
        Rect.fromCircle(center: _centre, radius: _inner),
        toDegrees * toRadians,
        -sweep,
        false,
      )
      ..close();
  }

  @override
  bool shouldRepaint(covariant _GoogleGPainter oldDelegate) => false;
}

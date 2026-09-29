import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/theme/mayos_spacing.dart';
import '../../../core/theme/mayos_theme.dart';
import '../../../core/theme/mayos_typography.dart';
import '../../../providers.dart';
import 'google_auth_gateway.dart';

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
    this.loading = false,
  });

  /// Starts "Continue with Google"; null disables the button.
  final Future<void> Function()? onPressed;

  /// Swaps the label for a spinner while a sign-in is in flight.
  final bool loading;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final GoogleAuthGateway gateway = ref.watch(googleAuthGatewayProvider);
    if (gateway.buttonStyle == GoogleSignInButtonStyle.hidden) {
      return const SizedBox.shrink();
    }
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: <Widget>[
        GoogleSignInButton(onPressed: onPressed, loading: loading),
        const SizedBox(height: MayosSpacing.md),
        const AuthOrDivider(),
        const SizedBox(height: MayosSpacing.md),
      ],
    );
  }
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
    // Google's branding allows one light and one dark theme; pick the one that
    // matches the surface this screen is drawn on (the sign-in screens run on
    // the dark wallpaper).
    final bool dark = Theme.of(context).brightness == Brightness.dark;
    final Color fill = dark ? const Color(0xFF131314) : const Color(0xFFFFFFFF);
    final Color stroke =
        dark ? const Color(0xFF8E918F) : const Color(0xFF747775);
    final Color labelColor =
        dark ? const Color(0xFFE3E3E3) : const Color(0xFF1F1F1F);
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

/// The standard-colour Google "G", drawn at 48×48 from Google's published
/// sign-in asset paths so the mark is never recoloured or redrawn (#115).
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

class _GoogleGPainter extends CustomPainter {
  static final List<(Path, Color)> _segments = <(Path, Color)>[
    (_svgPath(
        'M24 9.5c3.54 0 6.71 1.22 9.21 3.6l6.85-6.85C35.9 2.38 30.47 0 24 0 '
        '14.62 0 6.51 5.38 2.56 13.22l7.98 6.19C12.43 13.72 17.74 9.5 24 9.5z'),
        const Color(0xFFEA4335)),
    (_svgPath(
        'M46.98 24.55c0-1.57-.15-3.09-.38-4.55H24v9.02h12.94c-.58 2.96-2.26 '
        '5.48-4.78 7.18l7.73 6c4.51-4.18 7.09-10.36 7.09-17.65z'),
        const Color(0xFF4285F4)),
    (_svgPath(
        'M10.53 28.59c-.48-1.45-.76-2.99-.76-4.59s.27-3.14.76-4.59l-7.98-6.19'
        'C.92 16.46 0 20.12 0 24c0 3.88.92 7.54 2.56 10.78l7.97-6.19z'),
        const Color(0xFFFBBC05)),
    (_svgPath(
        'M24 48c6.48 0 11.93-2.13 15.89-5.81l-7.73-6c-2.15 1.45-4.92 2.3-8.16 '
        '2.3-6.26 0-11.57-4.22-13.47-9.91l-7.98 6.19C6.51 42.62 14.62 48 24 48z'),
        const Color(0xFF34A853)),
  ];

  @override
  void paint(Canvas canvas, Size size) {
    final double scale = size.width / 48;
    canvas.scale(scale, scale);
    for (final (Path path, Color color) in _segments) {
      canvas.drawPath(path, Paint()..color = color);
    }
  }

  @override
  bool shouldRepaint(covariant _GoogleGPainter oldDelegate) => false;
}

/// Parses the subset of SVG path data the Google mark uses (M/m, L/l, H/h,
/// V/v, C/c, S/s, Z/z) into a [Path]; an unsupported command stops the parse
/// rather than drawing something wrong.
Path _svgPath(String source) {
  const String tokenPattern =
      r'[A-Za-z]|[-+]?(?:\d*\.\d+|\d+)(?:[eE][-+]?\d+)?';
  final List<String> tokens = RegExp(tokenPattern)
      .allMatches(source)
      .map((Match match) => match.group(0)!)
      .toList(growable: false);
  final Path path = Path();
  int i = 0;
  double number() {
    final double value = double.parse(tokens[i]);
    i += 1;
    return value;
  }

  double x = 0;
  double y = 0;
  double startX = 0;
  double startY = 0;
  double lastControlX = 0;
  double lastControlY = 0;
  String command = '';
  while (i < tokens.length) {
    final String token = tokens[i];
    if (RegExp(r'^[A-Za-z]$').hasMatch(token)) {
      command = token;
      i += 1;
      if (command == 'Z' || command == 'z') {
        path.close();
        x = startX;
        y = startY;
        continue;
      }
    } else if (!_isNumberToken(token)) {
      break;
    }
    switch (command) {
      case 'M':
        x = number();
        y = number();
        path.moveTo(x, y);
        startX = x;
        startY = y;
        command = 'L';
      case 'm':
        x += number();
        y += number();
        path.moveTo(x, y);
        startX = x;
        startY = y;
        command = 'l';
      case 'L':
        x = number();
        y = number();
        path.lineTo(x, y);
      case 'l':
        x += number();
        y += number();
        path.lineTo(x, y);
      case 'H':
        x = number();
        path.lineTo(x, y);
      case 'h':
        x += number();
        path.lineTo(x, y);
      case 'V':
        y = number();
        path.lineTo(x, y);
      case 'v':
        y += number();
        path.lineTo(x, y);
      case 'C':
        final double x1 = number();
        final double y1 = number();
        final double x2 = number();
        final double y2 = number();
        x = number();
        y = number();
        path.cubicTo(x1, y1, x2, y2, x, y);
        lastControlX = x2;
        lastControlY = y2;
      case 'c':
        final double x1 = x + number();
        final double y1 = y + number();
        final double x2 = x + number();
        final double y2 = y + number();
        final double endX = x + number();
        final double endY = y + number();
        path.cubicTo(x1, y1, x2, y2, endX, endY);
        x = endX;
        y = endY;
        lastControlX = x2;
        lastControlY = y2;
      case 'S':
        final double x1 = 2 * x - lastControlX;
        final double y1 = 2 * y - lastControlY;
        final double x2 = number();
        final double y2 = number();
        x = number();
        y = number();
        path.cubicTo(x1, y1, x2, y2, x, y);
        lastControlX = x2;
        lastControlY = y2;
      case 's':
        final double x1 = 2 * x - lastControlX;
        final double y1 = 2 * y - lastControlY;
        final double x2 = x + number();
        final double y2 = y + number();
        final double endX = x + number();
        final double endY = y + number();
        path.cubicTo(x1, y1, x2, y2, endX, endY);
        x = endX;
        y = endY;
        lastControlX = x2;
        lastControlY = y2;
      default:
        return path;
    }
  }
  return path;
}

bool _isNumberToken(String token) {
  if (token.isEmpty) {
    return false;
  }
  final int first = token.codeUnitAt(0);
  return first == 45 ||
      first == 43 ||
      first == 46 ||
      (first >= 48 && first <= 57);
}

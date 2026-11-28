import 'package:flutter/material.dart';

import '../display_language/copy_context.dart';
import '../theme/mayos_colors.dart';
import '../theme/mayos_theme.dart';
import '../theme/mayos_typography.dart';

/// Which colour the "MAYOS" word under the mark takes. The mark itself is
/// always the logo red (#886).
enum MayosBrandVariant {
  /// Picks by effective theme: dark → white word, light → near-black word.
  auto,
  white,
  black,
}

/// Geometry of the dumbbell M, in the supplied SVG's 512-unit space
/// (`assets/brand/mark-*.svg` at the repo root). The mark
/// is drawn, not shipped as an image, so it stays sharp at every size and
/// never needs a per-theme file.
abstract final class _MarkGeometry {
  /// Tight box around the artwork: x 56–456, y 136–376 (5:3).
  static const Rect bounds = Rect.fromLTWH(56, 136, 400, 240);
  static const double aspectRatio = 400 / 240;

  static const List<Offset> v = <Offset>[
    Offset(144, 176),
    Offset(256, 330),
    Offset(368, 176),
  ];
  static const double strokeWidth = 34;
  static const double miterLimit = 12;

  static final List<RRect> bars = <RRect>[
    RRect.fromLTRBR(108, 138, 180, 374, const Radius.circular(36)),
    RRect.fromLTRBR(332, 138, 404, 374, const Radius.circular(36)),
    RRect.fromLTRBR(60, 192, 100, 320, const Radius.circular(20)),
    RRect.fromLTRBR(412, 192, 452, 320, const Radius.circular(20)),
  ];
}

class _MarkPainter extends CustomPainter {
  const _MarkPainter(this.color);

  final Color color;

  @override
  void paint(Canvas canvas, Size size) {
    final double scale = size.height / _MarkGeometry.bounds.height;
    canvas
      ..save()
      ..scale(scale)
      ..translate(-_MarkGeometry.bounds.left, -_MarkGeometry.bounds.top);
    final Paint fill = Paint()
      ..color = color
      ..isAntiAlias = true;
    for (final RRect bar in _MarkGeometry.bars) {
      canvas.drawRRect(bar, fill);
    }
    final Path v = Path()
      ..moveTo(_MarkGeometry.v[0].dx, _MarkGeometry.v[0].dy)
      ..lineTo(_MarkGeometry.v[1].dx, _MarkGeometry.v[1].dy)
      ..lineTo(_MarkGeometry.v[2].dx, _MarkGeometry.v[2].dy);
    canvas.drawPath(
      v,
      Paint()
        ..color = color
        ..isAntiAlias = true
        ..style = PaintingStyle.stroke
        ..strokeWidth = _MarkGeometry.strokeWidth
        ..strokeJoin = StrokeJoin.miter
        ..strokeMiterLimit = _MarkGeometry.miterLimit
        ..strokeCap = StrokeCap.butt,
    );
    canvas.restore();
  }

  @override
  bool shouldRepaint(_MarkPainter oldDelegate) => oldDelegate.color != color;
}

/// The MAYOS dumbbell M on its own, in the logo red. [size] is its height;
/// the width follows the artwork's 5:3 shape. Used in the app header (alone,
/// with no word under it), onboarding and the install prompt.
class MayosBrandMark extends StatelessWidget {
  const MayosBrandMark({
    super.key,
    this.size = 24,
    this.color = MayosPalette.red,
  });

  final double size;
  final Color color;

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      key: const ValueKey<String>('mayos_brand_mark'),
      height: size,
      width: size * _MarkGeometry.aspectRatio,
      child: CustomPaint(painter: _MarkPainter(color)),
    );
  }
}

/// The mark with "MAYOS" under it in the wordmark face (A drawn as Λ), widely
/// letter-spaced. Used where people first meet the app: the splash, the
/// logged-out screens and the share card.
///
/// [height] is the whole lockup's height. [gap] is the fixed space between
/// mark and word, chosen by Thomas: 5 on the splash, 4 on sign-in.
class MayosBrandLockup extends StatelessWidget {
  const MayosBrandLockup({
    super.key,
    this.height = 120,
    this.gap = 5,
    this.variant = MayosBrandVariant.auto,
  });

  final double height;
  final double gap;
  final MayosBrandVariant variant;

  /// The word's size and line height relative to the mark's height.
  static const double _wordToMark = 0.36;
  static const double _wordLineHeight = 1.2;
  static const double _letterSpacing = 0.42;

  @override
  Widget build(BuildContext context) {
    final String brandName = displayCopyOf(context).brandName;
    final MayosThemeExtension c = MayosTheme.of(context);
    final MayosBrandVariant resolved = variant == MayosBrandVariant.auto
        ? (c.isDark ? MayosBrandVariant.white : MayosBrandVariant.black)
        : variant;
    final Color wordColor = resolved == MayosBrandVariant.white
        ? MayosPalette.darkTextPrimary
        : MayosPalette.lightTextPrimary;
    final double markHeight =
        ((height - gap) / (1 + _wordToMark * _wordLineHeight))
            .clamp(0.0, double.infinity);
    final double fontSize = markHeight * _wordToMark;
    return Semantics(
      label: brandName,
      image: true,
      excludeSemantics: true,
      child: MediaQuery.withNoTextScaling(
        child: Column(
          key: const ValueKey<String>('mayos_brand_lockup'),
          mainAxisSize: MainAxisSize.min,
          children: <Widget>[
            MayosBrandMark(size: markHeight),
            SizedBox(height: gap),
            // A fixed box for the word keeps mark + gap + word exactly at
            // [height], whatever line metrics the platform reports.
            SizedBox(
              key: const ValueKey<String>('mayos_brand_word'),
              height: fontSize * _wordLineHeight,
              child: Center(
                child: Text(
                  'MAYOS',
                  textDirection: TextDirection.ltr,
                  maxLines: 1,
                  softWrap: false,
                  overflow: TextOverflow.visible,
                  style: MayosTypography.brandWordmark.copyWith(
                    fontSize: fontSize,
                    height: _wordLineHeight,
                    letterSpacing: fontSize * _letterSpacing,
                    color: wordColor,
                  ),
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

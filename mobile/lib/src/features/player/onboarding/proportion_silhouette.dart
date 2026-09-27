import 'package:flutter/material.dart';

import '../../../core/theme/mayos_theme.dart';

/// The three relative leg/torso proportions the intake supports. Only the hip
/// line differs; the standing height is constant across the three.
enum ProportionShape { longLegs, balanced, longTorso }

/// An original, theme-aware MAYOS proportion silhouette.
///
/// A neutral anatomical-leaning figure: head, neck, shoulders tapering to the
/// waist, hips, arms hanging to mid-thigh, and legs with a slight taper. The
/// total standing height is constant; only the hip line moves (leg length
/// ≈ 0.53 / 0.48 / 0.43 of standing height), and a dashed hip guide makes the
/// comparison read at a glance.
class ProportionSilhouette extends StatelessWidget {
  const ProportionSilhouette({
    super.key,
    required this.shape,
    this.selected = false,
  });

  final ProportionShape shape;
  final bool selected;

  @override
  Widget build(BuildContext context) {
    final MayosThemeExtension c = MayosTheme.of(context);
    final Color body = selected
        ? c.accent.withValues(alpha: c.isDark ? 0.95 : 0.92)
        : c.textMuted.withValues(alpha: c.isDark ? 0.6 : 0.5);
    return ExcludeSemantics(
      child: CustomPaint(
        painter: _ProportionSilhouettePainter(
          shape: shape,
          body: body,
          guide: selected
              ? c.accent.withValues(alpha: 0.9)
              : c.textMuted.withValues(alpha: 0.65),
        ),
        child: const SizedBox(width: double.infinity, height: double.infinity),
      ),
    );
  }
}

class _ProportionSilhouettePainter extends CustomPainter {
  _ProportionSilhouettePainter({
    required this.shape,
    required this.body,
    required this.guide,
  });

  final ProportionShape shape;
  final Color body;
  final Color guide;

  @override
  void paint(Canvas canvas, Size size) {
    final double w = size.width;
    final double h = size.height;
    if (w <= 0 || h <= 0) {
      return;
    }

    final double cx = w / 2;
    final double top = h * 0.02;
    final double bottom = h * 0.98;
    final double standing = bottom - top;

    // Leg length as a fraction of standing height. This is the only quantity
    // that changes between the choices.
    final double legFrac = switch (shape) {
      ProportionShape.longLegs => 0.53,
      ProportionShape.balanced => 0.48,
      ProportionShape.longTorso => 0.43,
    };

    final double headR = standing * 0.058;
    final double headCy = top + headR;
    final double neckTop = headCy + headR * 0.92;
    final double neckHalf = standing * 0.022;
    final double shoulderY = neckTop + standing * 0.03;
    final double hipY = bottom - legFrac * standing;
    final double torsoH = hipY - shoulderY;
    final double waistY = shoulderY + torsoH * 0.62;

    final double shoulderHalf = standing * 0.115;
    final double waistHalf = standing * 0.078;
    final double hipHalf = standing * 0.10;

    final Paint paint = Paint()
      ..style = PaintingStyle.fill
      ..color = body
      ..isAntiAlias = true;

    // Torso + neck as one closed outline, tapering in at the waist and out at
    // the hips, so the figure never reads as a floating block.
    final Path torso = Path()
      ..moveTo(cx - neckHalf, neckTop)
      ..lineTo(cx + neckHalf, neckTop)
      ..lineTo(cx + neckHalf, shoulderY)
      ..quadraticBezierTo(cx + shoulderHalf * 0.7, shoulderY - standing * 0.005,
          cx + shoulderHalf, shoulderY + torsoH * 0.06)
      ..quadraticBezierTo(cx + waistHalf, waistY, cx + hipHalf, hipY)
      ..lineTo(cx - hipHalf, hipY)
      ..quadraticBezierTo(
          cx - waistHalf, waistY, cx - shoulderHalf, shoulderY + torsoH * 0.06)
      ..quadraticBezierTo(cx - shoulderHalf * 0.7, shoulderY - standing * 0.005,
          cx - neckHalf, shoulderY)
      ..close();
    canvas.drawPath(torso, paint);

    // Head.
    canvas.drawOval(
      Rect.fromCenter(
        center: Offset(cx, headCy),
        width: headR * 1.84,
        height: headR * 2.1,
      ),
      paint,
    );

    // Arms hang from the shoulder to mid-thigh, tapering to the wrist.
    final double midThigh = hipY + (bottom - hipY) * 0.5;
    final double armTopW = standing * 0.05;
    final double armWristW = standing * 0.032;
    _limb(
      canvas,
      paint,
      Offset(cx - shoulderHalf * 0.82, shoulderY + torsoH * 0.05),
      Offset(cx - shoulderHalf * 0.98, midThigh),
      armTopW,
      armWristW,
    );
    _limb(
      canvas,
      paint,
      Offset(cx + shoulderHalf * 0.82, shoulderY + torsoH * 0.05),
      Offset(cx + shoulderHalf * 0.98, midThigh),
      armTopW,
      armWristW,
    );

    // Legs from the hips to the feet, slightly tapered.
    _limb(
      canvas,
      paint,
      Offset(cx - hipHalf * 0.5, hipY),
      Offset(cx - hipHalf * 0.6, bottom),
      standing * 0.06,
      standing * 0.036,
    );
    _limb(
      canvas,
      paint,
      Offset(cx + hipHalf * 0.5, hipY),
      Offset(cx + hipHalf * 0.6, bottom),
      standing * 0.06,
      standing * 0.036,
    );

    // Dashed hip guide across the figure.
    _dashedLine(
      canvas,
      Offset(cx - shoulderHalf * 1.35, hipY),
      Offset(cx + shoulderHalf * 1.35, hipY),
      Paint()
        ..color = guide
        ..strokeWidth = 1.4
        ..isAntiAlias = true,
    );
  }

  /// A tapered limb from [top] to [bottom]: a quad with widths at each end.
  void _limb(
    Canvas canvas,
    Paint paint,
    Offset top,
    Offset bottom,
    double topWidth,
    double bottomWidth,
  ) {
    final Offset axis = bottom - top;
    final double len = axis.distance;
    if (len == 0) {
      return;
    }
    final Offset normal = Offset(-axis.dy / len, axis.dx / len);
    final Path path = Path()
      ..moveTo(
          top.dx + normal.dx * topWidth / 2, top.dy + normal.dy * topWidth / 2)
      ..lineTo(bottom.dx + normal.dx * bottomWidth / 2,
          bottom.dy + normal.dy * bottomWidth / 2)
      ..lineTo(bottom.dx - normal.dx * bottomWidth / 2,
          bottom.dy - normal.dy * bottomWidth / 2)
      ..lineTo(
          top.dx - normal.dx * topWidth / 2, top.dy - normal.dy * topWidth / 2)
      ..close();
    canvas.drawPath(path, paint);
  }

  void _dashedLine(
    Canvas canvas,
    Offset a,
    Offset b,
    Paint paint, {
    double dash = 5,
    double gap = 4,
  }) {
    final Offset axis = b - a;
    final double total = axis.distance;
    if (total == 0) {
      return;
    }
    final Offset dir = axis / total;
    double travelled = 0;
    while (travelled < total) {
      final double end = (travelled + dash).clamp(0, total);
      canvas.drawLine(a + dir * travelled, a + dir * end, paint);
      travelled += dash + gap;
    }
  }

  @override
  bool shouldRepaint(_ProportionSilhouettePainter oldDelegate) =>
      oldDelegate.shape != shape ||
      oldDelegate.body != body ||
      oldDelegate.guide != guide;
}

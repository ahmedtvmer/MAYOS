import 'dart:math' as math;

import 'package:flutter/material.dart';

import '../../../core/theme/mayos_theme.dart';
import '../../../core/theme/mayos_typography.dart';

/// One plotted point: an ISO `YYYY-MM-DD` session date and its metric value.
class ProgressChartPoint {
  const ProgressChartPoint({required this.date, required this.value});

  final String date;
  final double value;
}

/// A minimal progression line chart drawn with a [CustomPainter].
///
/// The brand-blue principal series (theme `chartPrimary`), restrained
/// horizontal gridlines, dated x-axis and unit-formatted y-axis. A single
/// point renders as one marker. A subtle draw-in animation runs once
/// ([MayosMotion.slow], 320 ms) and never blocks readability. Selecting a point
/// highlights it; the caller owns the callout with the session's real values.
class ProgressLineChart extends StatefulWidget {
  const ProgressLineChart({
    super.key,
    required this.points,
    required this.metricLabel,
    required this.unit,
    required this.exerciseName,
    this.selectedIndex,
    this.onPointSelected,
    this.height = 208,
  });

  final List<ProgressChartPoint> points;

  /// Explicit metric name, e.g. "Estimated 1RM".
  final String metricLabel;

  /// Explicit unit, e.g. "kg".
  final String unit;
  final String exerciseName;
  final int? selectedIndex;
  final ValueChanged<int>? onPointSelected;
  final double height;

  /// The accessibility summary read in place of the painted chart.
  String get semanticsSummary {
    if (points.isEmpty) {
      return '$metricLabel for $exerciseName: no sessions.';
    }
    final String first = shortDate(points.first.date);
    if (points.length == 1) {
      return '$metricLabel for $exerciseName: 1 session on $first, '
          '${_formatValue(points.first.value)} $unit.';
    }
    final String last = shortDate(points.last.date);
    return '$metricLabel for $exerciseName, ${points.length} sessions from '
        '$first to $last, latest ${_formatValue(points.last.value)} $unit.';
  }

  @override
  State<ProgressLineChart> createState() => _ProgressLineChartState();
}

class _ProgressLineChartState extends State<ProgressLineChart> {
  static const double _padLeft = 42;
  static const double _padRight = 14;

  int? _hitTest(Offset position, double width) {
    final int count = widget.points.length;
    if (count == 0) {
      return null;
    }
    if (count == 1) {
      return 0;
    }
    final double chartWidth = width - _padLeft - _padRight;
    if (chartWidth <= 0) {
      return null;
    }
    final double fraction =
        ((position.dx - _padLeft) / chartWidth).clamp(0.0, 1.0);
    return (fraction * (count - 1)).round().clamp(0, count - 1);
  }

  @override
  Widget build(BuildContext context) {
    final MayosThemeExtension c = MayosTheme.of(context);
    final TextScaler scaler = MediaQuery.textScalerOf(context);
    final TextDirection direction =
        Directionality.maybeOf(context) ?? TextDirection.ltr;

    return Semantics(
      label: widget.semanticsSummary,
      container: true,
      child: LayoutBuilder(
        builder: (BuildContext context, BoxConstraints constraints) {
          final double width = constraints.maxWidth;
          return GestureDetector(
            behavior: HitTestBehavior.opaque,
            onTapUp: widget.onPointSelected == null
                ? null
                : (TapUpDetails details) {
                    final int? index = _hitTest(details.localPosition, width);
                    if (index != null) {
                      widget.onPointSelected!(index);
                    }
                  },
            child: TweenAnimationBuilder<double>(
              tween: Tween<double>(begin: 0, end: 1),
              duration: const Duration(milliseconds: 320),
              curve: Curves.easeOutCubic,
              builder: (BuildContext context, double progress, Widget? child) {
                return CustomPaint(
                  size: Size(width, widget.height),
                  painter: _ProgressLinePainter(
                    points: widget.points,
                    unit: widget.unit,
                    selectedIndex: widget.selectedIndex,
                    color: c.chartPrimary,
                    gridColor: c.border,
                    labelColor: c.textMuted,
                    surfaceColor: c.surface,
                    progress: progress,
                    textScaler: scaler,
                    textDirection: direction,
                  ),
                );
              },
            ),
          );
        },
      ),
    );
  }
}

class _ProgressLinePainter extends CustomPainter {
  _ProgressLinePainter({
    required this.points,
    required this.unit,
    required this.selectedIndex,
    required this.color,
    required this.gridColor,
    required this.labelColor,
    required this.surfaceColor,
    required this.progress,
    required this.textScaler,
    required this.textDirection,
  });

  final List<ProgressChartPoint> points;
  final String unit;
  final int? selectedIndex;
  final Color color;
  final Color gridColor;
  final Color labelColor;
  final Color surfaceColor;
  final double progress;
  final TextScaler textScaler;
  final TextDirection textDirection;

  @override
  void paint(Canvas canvas, Size size) {
    if (points.isEmpty) {
      return;
    }
    const double padLeft = 42;
    const double padTop = 12;
    const double padRight = 14;
    const double padBottom = 26;
    final double left = padLeft;
    final double top = padTop;
    final double right = math.max(left + 1, size.width - padRight);
    final double bottom = math.max(top + 1, size.height - padBottom);
    final double chartWidth = right - left;
    final double chartHeight = bottom - top;

    double minValue = points.first.value;
    double maxValue = points.first.value;
    for (final ProgressChartPoint point in points) {
      minValue = math.min(minValue, point.value);
      maxValue = math.max(maxValue, point.value);
    }
    final double span = maxValue - minValue;
    if (span < 0.001) {
      final double pad = maxValue.abs() < 1 ? 1.0 : maxValue.abs() * 0.05;
      minValue -= pad;
      maxValue += pad;
    } else {
      final double pad = span * 0.1;
      minValue -= pad;
      maxValue += pad;
    }

    double yFor(double value) =>
        bottom - ((value - minValue) / (maxValue - minValue)) * chartHeight;
    double xFor(int index) => points.length == 1
        ? left + chartWidth / 2
        : left + chartWidth * index / (points.length - 1);

    final Paint gridPaint = Paint()
      ..color = gridColor
      ..strokeWidth = 1;

    final List<double> gridValues = <double>[
      maxValue,
      (minValue + maxValue) / 2,
      minValue,
    ];
    for (final double value in gridValues) {
      final double y = yFor(value);
      canvas.drawLine(Offset(left, y), Offset(right, y), gridPaint);
      _paintText(
        canvas,
        _formatValue(value),
        Offset(left - 6, y),
        alignRight: true,
        centerVertically: true,
      );
    }

    _paintText(canvas, shortDate(points.first.date), Offset(left, bottom + 6),
        alignTop: true);
    if (points.length > 1) {
      _paintText(
        canvas,
        shortDate(points.last.date),
        Offset(right, bottom + 6),
        alignRight: true,
        alignTop: true,
      );
    }

    final int? selected = selectedIndex;
    if (selected != null && selected >= 0 && selected < points.length) {
      final double x = xFor(selected);
      canvas.drawLine(
        Offset(x, top),
        Offset(x, bottom),
        Paint()
          ..color = gridColor
          ..strokeWidth = 1,
      );
    }

    canvas.save();
    canvas.clipRect(
        Rect.fromLTWH(left, 0, chartWidth * progress + 0.5, size.height));

    final Paint linePaint = Paint()
      ..color = color
      ..style = PaintingStyle.stroke
      ..strokeWidth = 2.4
      ..strokeCap = StrokeCap.round
      ..strokeJoin = StrokeJoin.round;
    final Path path = Path();
    for (int i = 0; i < points.length; i++) {
      final Offset offset = Offset(xFor(i), yFor(points[i].value));
      if (i == 0) {
        path.moveTo(offset.dx, offset.dy);
      } else {
        path.lineTo(offset.dx, offset.dy);
      }
    }
    canvas.drawPath(path, linePaint);

    for (int i = 0; i < points.length; i++) {
      final Offset offset = Offset(xFor(i), yFor(points[i].value));
      final bool isSelected = i == selected;
      final double radius = isSelected ? 6 : 3.5;
      canvas.drawCircle(
          offset, radius, Paint()..color = isSelected ? color : surfaceColor);
      canvas.drawCircle(
        offset,
        radius,
        Paint()
          ..color = color
          ..style = PaintingStyle.stroke
          ..strokeWidth = isSelected ? 2.4 : 1.6,
      );
    }
    canvas.restore();
  }

  void _paintText(
    Canvas canvas,
    String text,
    Offset anchor, {
    bool alignRight = false,
    bool alignTop = false,
    bool centerVertically = false,
  }) {
    final TextPainter painter = TextPainter(
      text: TextSpan(
        text: text,
        style: MayosTypography.caption.copyWith(color: labelColor),
      ),
      textDirection: textDirection,
      textScaler: textScaler,
      maxLines: 1,
    )..layout();
    double dx = anchor.dx;
    double dy = anchor.dy;
    if (alignRight) {
      dx -= painter.width;
    }
    if (alignTop) {
      // anchor.dy is the top of the label area.
    } else if (centerVertically) {
      dy -= painter.height / 2;
    } else {
      dy -= painter.height;
    }
    painter.paint(canvas, Offset(dx, dy));
  }

  @override
  bool shouldRepaint(_ProgressLinePainter oldDelegate) {
    return oldDelegate.progress != progress ||
        oldDelegate.selectedIndex != selectedIndex ||
        oldDelegate.color != color ||
        oldDelegate.gridColor != gridColor ||
        oldDelegate.labelColor != labelColor ||
        oldDelegate.surfaceColor != surfaceColor ||
        !_samePoints(oldDelegate.points, points);
  }

  static bool _samePoints(
      List<ProgressChartPoint> a, List<ProgressChartPoint> b) {
    if (identical(a, b)) {
      return true;
    }
    if (a.length != b.length) {
      return false;
    }
    for (int i = 0; i < a.length; i++) {
      if (a[i].date != b[i].date || a[i].value != b[i].value) {
        return false;
      }
    }
    return true;
  }
}

/// Formats an ISO date as a short axis/report label ("2026-06-03" → "Jun 3").
String shortDate(String iso) {
  final DateTime? parsed = DateTime.tryParse(iso);
  if (parsed == null) {
    return iso;
  }
  const List<String> months = <String>[
    'Jan',
    'Feb',
    'Mar',
    'Apr',
    'May',
    'Jun',
    'Jul',
    'Aug',
    'Sep',
    'Oct',
    'Nov',
    'Dec',
  ];
  return '${months[parsed.month - 1]} ${parsed.day}';
}

String _formatValue(double value) {
  if ((value - value.roundToDouble()).abs() < 0.05) {
    return value.round().toString();
  }
  return value.toStringAsFixed(1);
}

import 'dart:math' as math;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api_client.dart';
import '../../core/refetch_on_reconnect.dart';
import '../../core/connectivity_message.dart';
import '../../core/display_language/copy_context.dart';
import '../../core/display_language/nutrition_copy.dart';
import '../../core/models.dart';
import '../../providers.dart';
import '../nutrition/pace_proposal_card.dart';

class CoachChartsSegment extends ConsumerStatefulWidget {
  const CoachChartsSegment({super.key, required this.assignmentId});
  final String assignmentId;

  @override
  ConsumerState<CoachChartsSegment> createState() => _CoachChartsSegmentState();
}

class _CoachChartsSegmentState extends ConsumerState<CoachChartsSegment>
    with RefetchOnReconnect<CoachChartsSegment> {
  @override
  Future<void> refreshAfterReconnect() => _load();

  CoachNutritionState? _state;
  bool _failed = false;
  bool _deciding = false;
  String? _decisionError;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      final CoachNutritionState value = await ref.read(apiClientProvider).coachPlayerNutrition(widget.assignmentId, days: 28);
      if (mounted) setState(() => _state = value);
    } on ApiException {
      if (mounted) setState(() => _failed = true);
    }
  }

  @override
  Widget build(BuildContext context) {
    final NutritionCopy copy = displayCopyOf(context).nutrition;
    final CoachNutritionState? state = _state;
    if (state == null) return Center(child: _failed ? Text(copy.coachChartLoadError) : const CircularProgressIndicator());
    final Map<String, String?> adherence = <String, String?>{
      for (final Map<String, dynamic> day in state.adherenceDays)
        '${day['date']}': day['value'] as String?,
    };
    final Map<String, double> weights = <String, double>{
      for (final Map<String, dynamic> point in state.weightTrend)
        if (point['weight_kg'] is num) '${point['date']}': (point['weight_kg'] as num).toDouble(),
    };
    final List<Map<String, dynamic>> days = state.adherenceDays;
    final List<String> weightDates = weights.keys.toList()..sort();
    final String? firstWeightDate = weightDates.isEmpty ? null : weightDates.first;
    final int firstWeightIndex = days.indexWhere((Map<String, dynamic> day) => day['date'] == firstWeightDate);
    final double signedRate = state.plannedWeeklyRatePct ??
        ((state.goal == 'lose' ? -1 : state.goal == 'gain' ? 1 : 0) *
            ((state.targets?['weekly_rate_pct'] as num?)?.toDouble() ?? 0));
    final List<double?> planned = List<double?>.filled(28, null);
    if (firstWeightDate != null && firstWeightIndex >= 0) {
      final double first = weights[firstWeightDate]!;
      for (int i = firstWeightIndex; i < planned.length; i++) {
        planned[i] = first * (1 + signedRate / 100 * (i - firstWeightIndex) / 7);
      }
    }
    final bool hasData = weights.isNotEmpty || adherence.values.any((String? v) => v != null);
    final String summary = _accessibleSummary(copy, weights, adherence,
        state.plannedWeeklyRatePct ?? 0, firstWeightDate);
    return Directionality(textDirection: copy.isArabic ? TextDirection.rtl : TextDirection.ltr, child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: <Widget>[
      if (state.paceProposal != null) ...<Widget>[
        PaceProposalCard(proposal: state.paceProposal!, canDecide: state.authority == 'coach',
          busy: _deciding, onDecision: _decidePaceProposal),
        if (_decisionError != null) Text(_decisionError!,
            style: TextStyle(color: Theme.of(context).colorScheme.error)),
        const SizedBox(height: 12),
      ],
      Text(copy.coachWeightAdherence, style: Theme.of(context).textTheme.titleLarge),
      const SizedBox(height: 8),
      SizedBox(
        height: 260,
        child: hasData ? Semantics(label: summary, child: ExcludeSemantics(child: CustomPaint(painter: _NutritionChartPainter(
          weights: List<double?>.generate(28, (int i) => weights[state.adherenceDays[i]['date']]),
          planned: planned,
          adherence: List<String?>.generate(28, (int i) => adherence[state.adherenceDays[i]['date']]),
          rtl: copy.isArabic,
          startLabel: copy.coachChartStart,
          todayLabel: copy.coachToday,
          colors: Theme.of(context).colorScheme,
        )))) : Center(child: Text(copy.coachNoChartData)),
      ),
      Row(children: <Widget>[
        _Legend(color: Theme.of(context).colorScheme.primary, label: copy.coachWeightTrend),
        const SizedBox(width: 16),
        _Legend(color: Theme.of(context).colorScheme.tertiary, label: copy.coachPlannedPace),
        const SizedBox(width: 16),
        _Legend(color: Theme.of(context).colorScheme.error, label: copy.coachChartAdherence),
      ]),
      const SizedBox(height: 8),
      if (hasData) ExcludeSemantics(child: Text(summary)),
    ]));
  }

  Future<void> _decidePaceProposal(String decision) async {
    final Object? rawId = _state?.paceProposal?['id'];
    final int? proposalId = rawId is num ? rawId.toInt() : int.tryParse('$rawId');
    if (proposalId == null || _deciding) return;
    setState(() { _deciding = true; _decisionError = null; });
    try {
      final CoachNutritionState state = await ref.read(apiClientProvider)
          .decideCoachPaceProposal(widget.assignmentId, proposalId, decision);
      if (mounted) setState(() { _state = state; _deciding = false; });
    } on ApiException catch (error) {
      if (mounted) {
        setState(() {
          _deciding = false;
          _decisionError = displayCopyOf(context).failureMessage(apiFailureMessage(error));
        });
      }
    }
  }

  String _accessibleSummary(NutritionCopy copy, Map<String, double> weights,
      Map<String, String?> adherence, double plannedRate, String? startDate) {
    if (weights.isEmpty && !adherence.values.any((String? value) => value != null)) {
      return copy.coachNoChartData;
    }
    final List<String> dates = weights.keys.toList()..sort();
    final String? weightSummary = dates.isEmpty ? null :
        copy.coachWeightChange(weights[dates.first]!, weights[dates.last]!);
    final int onTarget = adherence.values.where((String? value) => value == 'on_target').length;
    final int roughly = adherence.values.where((String? value) => value == 'roughly').length;
    final int off = adherence.values.where((String? value) => value == 'off').length;
    final bool hasAdherence = onTarget + roughly + off > 0;
    final String? paceSummary = startDate == null ? null : copy.coachPlannedRate(plannedRate, startDate);
    final List<String> summary = <String>[
      if (weightSummary != null) weightSummary,
      if (paceSummary != null) paceSummary,
      if (hasAdherence) copy.coachAdherenceSummary(onTarget, roughly, off),
    ];
    return summary.join(' ');
  }
}

class _Legend extends StatelessWidget {
  const _Legend({required this.color, required this.label});
  final Color color;
  final String label;
  @override
  Widget build(BuildContext context) => Expanded(child: Row(children: <Widget>[
    Container(width: 10, height: 10, color: color), const SizedBox(width: 5),
    Flexible(child: Text(label, style: Theme.of(context).textTheme.labelSmall)),
  ]));
}

class _NutritionChartPainter extends CustomPainter {
  _NutritionChartPainter({required this.weights, required this.planned, required this.adherence, required this.rtl, required this.startLabel, required this.todayLabel, required this.colors});
  final List<double?> weights, planned;
  final List<String?> adherence;
  final bool rtl;
  final String startLabel, todayLabel;
  final ColorScheme colors;

  @override
  void paint(Canvas canvas, Size size) {
    const double left = 12, right = 12, top = 12, bottom = 24;
    final Rect plot = Rect.fromLTRB(left, top, size.width - right, size.height - bottom);
    final List<double> present = <double>[...weights.whereType<double>(), ...planned.whereType<double>()];
    double low = present.isEmpty ? 0 : present.reduce(math.min);
    double high = present.isEmpty ? 1 : present.reduce(math.max);
    final double pad = math.max((high - low) * .12, .5); low -= pad; high += pad;
    double x(int i) => rtl ? plot.right - plot.width * i / 27 : plot.left + plot.width * i / 27;
    double y(double v) => plot.bottom - (v - low) / (high - low) * plot.height;
    final Paint bar = Paint()..color = colors.error.withValues(alpha: .5);
    for (int i = 0; i < adherence.length; i++) {
      final double h = switch (adherence[i]) { 'on_target' => 20, 'roughly' => 13, 'off' => 7, _ => 0 };
      if (h > 0) canvas.drawRect(Rect.fromLTWH(x(i) - 3, plot.bottom - h, 6, h), bar);
    }
    _drawSeries(canvas, weights, x, y, colors.primary, false);
    _drawSeries(canvas, planned, x, y, colors.tertiary, true);
    final TextPainter labels = TextPainter(textDirection: rtl ? TextDirection.rtl : TextDirection.ltr);
    labels.text = TextSpan(text: startLabel, style: TextStyle(color: colors.onSurfaceVariant, fontSize: 10));
    labels.layout(); labels.paint(canvas, Offset(rtl ? plot.right - labels.width : plot.left, plot.bottom + 5));
    labels.text = TextSpan(text: todayLabel, style: TextStyle(color: colors.onSurfaceVariant, fontSize: 10));
    labels.layout(); labels.paint(canvas, Offset(rtl ? plot.left : plot.right - labels.width, plot.bottom + 5));
  }

  void _drawSeries(Canvas canvas, List<double?> series, double Function(int) x, double Function(double) y, Color color, bool dashed) {
    final Paint paint = Paint()..color = color..strokeWidth = 2..style = PaintingStyle.stroke;
    for (int i = 1; i < series.length; i++) {
      final double? a = series[i - 1], b = series[i];
      if (a == null || b == null) continue;
      if (dashed) {
        final double dx = (x(i) - x(i - 1)) / 4;
        for (int part = 0; part < 4; part += 2) {
          final double x1 = x(i - 1) + dx * part, x2 = x(i - 1) + dx * (part + 1);
          final double t1 = part / 4, t2 = (part + 1) / 4;
          canvas.drawLine(Offset(x1, y(a + (b - a) * t1)), Offset(x2, y(a + (b - a) * t2)), paint);
        }
      } else {
        canvas.drawLine(Offset(x(i - 1), y(a)), Offset(x(i), y(b)), paint);
      }
    }
    if (!dashed) for (int i = 0; i < series.length; i++) { final double? v = series[i]; if (v != null) canvas.drawCircle(Offset(x(i), y(v)), 3, Paint()..color = color); }
  }

  @override
  bool shouldRepaint(_NutritionChartPainter old) => true;
}

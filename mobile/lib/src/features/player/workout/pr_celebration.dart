import 'dart:async';

import 'package:flutter/material.dart';

import '../../../core/theme/mayos_colors.dart';

import '../../../core/display_language/workout_copy.dart';
import '../../../core/personal_records.dart';

/// Short, non-interactive finish moment. It never participates in saving.
class PrCelebration extends StatefulWidget {
  const PrCelebration({required this.records, required this.languageCode, required this.onComplete, super.key});

  final List<WorkoutRecord> records;
  final String languageCode;
  final VoidCallback onComplete;

  @override
  State<PrCelebration> createState() => _PrCelebrationState();
}

class _PrCelebrationState extends State<PrCelebration> with SingleTickerProviderStateMixin {
  Timer? _timer;
  late final AnimationController _confettiController;

  @override
  void initState() {
    super.initState();
    _confettiController = AnimationController(vsync: this, duration: const Duration(seconds: 2))..forward();
    _timer = Timer(const Duration(seconds: 2), widget.onComplete);
  }

  @override
  void dispose() {
    _timer?.cancel();
    _confettiController.dispose();
    super.dispose();
  }

  WorkoutRecord _headline() {
    int priority(PrRecordKind kind) => switch (kind) {
          PrRecordKind.weight => 0,
          PrRecordKind.e1rm => 1,
          PrRecordKind.mostReps => 2,
        };
    final List<WorkoutRecord> sorted = [...widget.records]
      ..sort((WorkoutRecord a, WorkoutRecord b) {
        final int byKind = priority(a.kind).compareTo(priority(b.kind));
        return byKind != 0 ? byKind : b.value.compareTo(a.value);
      });
    return sorted.first;
  }

  @override
  Widget build(BuildContext context) {
    final WorkoutRecord record = _headline();
    final bool reduceMotion = MediaQuery.disableAnimationsOf(context);
    return GestureDetector(
      key: const ValueKey<String>('prCelebration.skip'),
      behavior: HitTestBehavior.opaque,
      onTap: () {
        _timer?.cancel();
        widget.onComplete();
      },
      child: Semantics(
      liveRegion: true,
      child: Stack(
        fit: StackFit.expand,
        children: <Widget>[
          const ColoredBox(color: MayosPalette.darkCanvas),
          if (!reduceMotion)
            IgnorePointer(
              child: AnimatedBuilder(
                animation: _confettiController,
                builder: (BuildContext context, Widget? child) => CustomPaint(
                  key: const ValueKey<String>('prCelebration.confetti'),
                  painter: PrConfettiPainter(_confettiController.value),
                  child: child,
                ),
              ),
            ),
          Center(
            child: Padding(
              padding: const EdgeInsets.all(28),
              child: Column(mainAxisSize: MainAxisSize.min, children: <Widget>[
                const Icon(Icons.emoji_events, size: 92, color: Color(0xffffd166)),
                const SizedBox(height: 20),
                Text(WorkoutCopy(widget.languageCode).newPr,
                    style: Theme.of(context).textTheme.headlineMedium?.copyWith(color: Colors.white)),
                const SizedBox(height: 12),
                Text(WorkoutCopy(widget.languageCode).prHeadline(record),
                    textAlign: TextAlign.center,
                    style: Theme.of(context).textTheme.titleLarge?.copyWith(color: Colors.white)),
              ]),
            ),
          ),
        ],
      ),
      ),
    );
  }
}

class PrConfettiPainter extends CustomPainter {
  const PrConfettiPainter(this.progress);
  final double progress;

  List<Offset> particlePositions(Size size) => List<Offset>.generate(
        48,
        (int i) => Offset(
          ((i * 73) % 101) / 100 * size.width,
          ((((i * 47) % 97) / 100) +
                  progress * (0.35 + (i % 4) * .08)) %
              1 *
              size.height,
        ),
      );

  @override
  void paint(Canvas canvas, Size size) {
    const List<Color> colors = <Color>[MayosPalette.red, Color(0xffffd166), Colors.white];
    final Paint paint = Paint()..style = PaintingStyle.fill;
    final List<Offset> positions = particlePositions(size);
    for (int i = 0; i < positions.length; i++) {
      final double x = positions[i].dx;
      final double y = positions[i].dy;
      final double w = 4 + (i % 3) * 2;
      paint.color = colors[i % colors.length].withValues(alpha: .8 * (1 - progress));
      canvas.drawRect(Rect.fromCenter(center: Offset(x, y), width: w, height: w * 2), paint);
    }
  }

  @override
  bool shouldRepaint(PrConfettiPainter oldDelegate) => oldDelegate.progress != progress;
}

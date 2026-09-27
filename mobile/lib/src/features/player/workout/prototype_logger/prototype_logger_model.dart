// PROTOTYPE — throwaway (wayfinder #107). Not production code; do not merge.
//
// In-memory Active workout with stub baselines, derived Personal-record
// badges, and a rest timer. Shared by every layout variant so the variants
// differ only in how they render and drive it.

import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';

enum PrKind { weight, e1rm }

String prLabel(PrKind k) => k == PrKind.weight ? 'Heaviest' : 'Best e1RM';

class ProtoPrevSet {
  const ProtoPrevSet(this.kg, this.reps, this.rir);
  final double kg;
  final int reps;
  final int? rir;
  String get label => '${fmtKg(kg)} × $reps${rir == null ? '' : ' @$rir'}';
}

/// What `GET /workouts/baselines` would return for one exercise, frozen at
/// workout start.
class ProtoBaseline {
  const ProtoBaseline(this.maxKg, this.bestE1rm, this.lastSets);
  final double maxKg;
  final double bestE1rm;
  final List<ProtoPrevSet> lastSets;
}

class ProtoSet {
  ProtoSet();
  double? kg;
  int? reps;
  int? rir;
  bool done = false;
  int doneSeq = 0;
}

class ProtoExercise {
  ProtoExercise(this.name,
      {required this.restSeconds,
      this.baseline,
      this.planned = true,
      int sets = 3}) {
    for (int i = 0; i < sets; i++) {
      this.sets.add(ProtoSet());
    }
  }
  final String name;
  final bool planned;
  int restSeconds;
  final ProtoBaseline? baseline;
  final List<ProtoSet> sets = <ProtoSet>[];

  ProtoPrevSet? previousFor(int index) {
    final List<ProtoPrevSet> last = baseline?.lastSets ?? const <ProtoPrevSet>[];
    if (last.isEmpty) return null;
    return index < last.length ? last[index] : null;
  }

  int get doneCount => sets.where((ProtoSet s) => s.done).length;
}

class ProtoRest {
  ProtoRest(this.exercise, this.total, this.endsAt);
  final ProtoExercise exercise;
  int total;
  DateTime endsAt;
  int get remaining {
    final int ms = endsAt.difference(DateTime.now()).inMilliseconds;
    return ms <= 0 ? 0 : (ms / 1000).ceil();
  }
}

/// Library stubs for "Add exercise" (Unplanned exercises).
final List<(String, ProtoBaseline?)> protoLibrary = <(String, ProtoBaseline?)>[
  (
    'Cable Fly',
    const ProtoBaseline(22.5, 30.8, <ProtoPrevSet>[
      ProtoPrevSet(20, 12, 2),
      ProtoPrevSet(22.5, 10, 1),
    ])
  ),
  ('Weighted Dip', null),
  (
    'Triceps Pushdown',
    const ProtoBaseline(35, 47.8, <ProtoPrevSet>[
      ProtoPrevSet(32.5, 12, 2),
      ProtoPrevSet(35, 10, 1),
      ProtoPrevSet(35, 9, 0),
    ])
  ),
];

double e1rm(double kg, int reps, int? rir) =>
    kg * (1 + (reps + (rir ?? 0)) / 30);

String fmtKg(double kg) =>
    kg == kg.roundToDouble() ? kg.toStringAsFixed(0) : kg.toString();

String fmtClock(int seconds) =>
    '${seconds ~/ 60}:${(seconds % 60).toString().padLeft(2, '0')}';

class ProtoSession extends ChangeNotifier {
  ProtoSession() {
    _seed();
    _ticker = Timer.periodic(const Duration(milliseconds: 250), (_) => _tick());
  }

  final List<ProtoExercise> exercises = <ProtoExercise>[];
  final List<String> log = <String>[];
  ProtoRest? rest;
  int _seq = 0;
  late final Timer _ticker;

  /// Badges held right now, and badges that a later set in this session beat.
  Map<ProtoSet, Set<PrKind>> badges = <ProtoSet, Set<PrKind>>{};
  Map<ProtoSet, Set<PrKind>> beaten = <ProtoSet, Set<PrKind>>{};

  void _seed() {
    exercises
      ..clear()
      ..add(ProtoExercise('Bench Press',
          restSeconds: 180,
          sets: 4,
          baseline: const ProtoBaseline(100, 116.7, <ProtoPrevSet>[
            ProtoPrevSet(95, 6, 2),
            ProtoPrevSet(100, 5, 1),
            ProtoPrevSet(100, 4, 1),
            ProtoPrevSet(92.5, 6, 2),
          ])))
      ..add(ProtoExercise('Incline Dumbbell Press',
          restSeconds: 120,
          baseline: const ProtoBaseline(34, 44.2, <ProtoPrevSet>[
            ProtoPrevSet(32, 10, 2),
            ProtoPrevSet(34, 8, 1),
            ProtoPrevSet(34, 7, 1),
          ])))
      // No baseline: this is the exercise's first session, so it only
      // establishes the baseline and never earns a badge.
      ..add(ProtoExercise('Lateral Raise', restSeconds: 90));
    log.clear();
    rest = null;
    _seq = 0;
    badges = <ProtoSet, Set<PrKind>>{};
    beaten = <ProtoSet, Set<PrKind>>{};
  }

  void reset() {
    _seed();
    _log('Reset workout');
    notifyListeners();
  }

  void _log(String line) {
    log.insert(0, line);
    if (log.length > 30) log.removeLast();
  }

  // ---- editing -------------------------------------------------------------

  void setKg(ProtoSet s, double? v) {
    s.kg = v;
    _recompute(silent: true);
    notifyListeners();
  }

  void setReps(ProtoSet s, int? v) {
    s.reps = v;
    _recompute(silent: true);
    notifyListeners();
  }

  void setRir(ProtoSet s, int? v) {
    s.rir = v;
    _recompute(silent: true);
    notifyListeners();
  }

  /// Returns false when there is nothing to complete (no value and no
  /// previous to fall back to).
  bool toggle(ProtoExercise ex, ProtoSet s) {
    final int index = ex.sets.indexOf(s);
    if (s.done) {
      s.done = false;
      _log('Unticked ${ex.name} set ${index + 1} → records recalculated');
      _recompute();
      notifyListeners();
      return true;
    }
    final ProtoPrevSet? prev = ex.previousFor(index);
    s.kg ??= prev?.kg;
    s.reps ??= prev?.reps;
    s.rir ??= s.kg != null && prev != null ? prev.rir : null;
    if (s.kg == null || s.reps == null) return false;
    s.done = true;
    s.doneSeq = ++_seq;
    HapticFeedback.selectionClick();
    _log('Ticked ${ex.name} set ${index + 1}: ${fmtKg(s.kg!)} × ${s.reps}'
        '${s.rir == null ? ' (RIR unrated → plain Epley)' : ' @RIR ${s.rir}'}');
    _recompute(justTicked: s);
    startRest(ex);
    notifyListeners();
    return true;
  }

  void addSet(ProtoExercise ex) {
    final ProtoSet s = ProtoSet();
    ex.sets.add(s);
    _log('Added set ${ex.sets.length} to ${ex.name}');
    notifyListeners();
  }

  void removeSet(ProtoExercise ex, ProtoSet s) {
    ex.sets.remove(s);
    _log('Removed a set from ${ex.name}');
    _recompute();
    notifyListeners();
  }

  ProtoExercise addUnplanned(String name, ProtoBaseline? baseline) {
    final ProtoExercise ex = ProtoExercise(name,
        restSeconds: 120, planned: false, baseline: baseline, sets: 1);
    exercises.add(ex);
    _log('Added Unplanned exercise $name (rest defaults to 2:00)');
    notifyListeners();
    return ex;
  }

  /// The player's per-exercise change is remembered (on the device).
  void setExerciseRest(ProtoExercise ex, int seconds) {
    ex.restSeconds = seconds.clamp(0, 600);
    _log('${ex.name} rest set to ${fmtClock(ex.restSeconds)} (remembered)');
    notifyListeners();
  }

  // ---- personal records ---------------------------------------------------

  void _recompute({ProtoSet? justTicked, bool silent = false}) {
    final Map<ProtoSet, Set<PrKind>> nextBadges = <ProtoSet, Set<PrKind>>{};
    final Map<ProtoSet, Set<PrKind>> nextBeaten = <ProtoSet, Set<PrKind>>{};
    for (final ProtoExercise ex in exercises) {
      final ProtoBaseline? b = ex.baseline;
      if (b == null) continue; // first session: baseline only
      final List<ProtoSet> done = ex.sets
          .where((ProtoSet s) => s.done && s.kg != null && s.reps != null)
          .toList()
        ..sort((ProtoSet a, ProtoSet c) => a.doneSeq.compareTo(c.doneSeq));
      double bestW = b.maxKg;
      double bestE = b.bestE1rm;
      ProtoSet? holderW;
      ProtoSet? holderE;
      for (final ProtoSet s in done) {
        if (s.kg! > bestW) {
          if (holderW != null) {
            (nextBeaten[holderW] ??= <PrKind>{}).add(PrKind.weight);
          }
          holderW = s;
          bestW = s.kg!;
        }
        final double e = e1rm(s.kg!, s.reps!, s.rir);
        if (e > bestE + 0.05) {
          if (holderE != null) {
            (nextBeaten[holderE] ??= <PrKind>{}).add(PrKind.e1rm);
          }
          holderE = s;
          bestE = e;
        }
      }
      if (holderW != null) {
        (nextBadges[holderW] ??= <PrKind>{}).add(PrKind.weight);
      }
      if (holderE != null) {
        (nextBadges[holderE] ??= <PrKind>{}).add(PrKind.e1rm);
      }
    }
    final Set<PrKind> gained = justTicked == null
        ? <PrKind>{}
        : (nextBadges[justTicked] ?? <PrKind>{});
    if (gained.isNotEmpty && !silent) {
      HapticFeedback.heavyImpact();
      _log('  ★ Personal record: ${gained.map(prLabel).join(' + ')}'
          '${nextBeaten.length > beaten.length ? ' (beats an earlier set)' : ''}');
    }
    badges = nextBadges;
    beaten = nextBeaten;
  }

  Set<PrKind> badgesOf(ProtoSet s) => badges[s] ?? const <PrKind>{};
  Set<PrKind> beatenOf(ProtoSet s) => beaten[s] ?? const <PrKind>{};

  List<(ProtoExercise, ProtoSet, PrKind)> get records =>
      <(ProtoExercise, ProtoSet, PrKind)>[
        for (final ProtoExercise ex in exercises)
          for (final ProtoSet s in ex.sets)
            for (final PrKind k in badgesOf(s)) (ex, s, k),
      ];

  // ---- rest timer ---------------------------------------------------------

  void startRest(ProtoExercise ex) {
    if (ex.restSeconds == 0) return;
    rest = ProtoRest(ex, ex.restSeconds,
        DateTime.now().add(Duration(seconds: ex.restSeconds)));
  }

  void adjustRest(int delta) {
    final ProtoRest? r = rest;
    if (r == null) return;
    r.endsAt = r.endsAt.add(Duration(seconds: delta));
    r.total = (r.total + delta).clamp(1, 1200);
    if (r.remaining <= 0) rest = null;
    notifyListeners();
  }

  void skipRest() {
    rest = null;
    _log('Rest skipped');
    notifyListeners();
  }

  void _tick() {
    final ProtoRest? r = rest;
    if (r == null) return;
    if (r.remaining <= 0) {
      rest = null;
      HapticFeedback.vibrate();
      SystemSound.play(SystemSoundType.alert);
      _log('Rest over for ${r.exercise.name} → vibrate + sound');
    }
    notifyListeners();
  }

  // ---- finish -------------------------------------------------------------

  /// Sets that were never ticked but would complete (a value or a previous).
  int get untickedFillable {
    int n = 0;
    for (final ProtoExercise ex in exercises) {
      for (int i = 0; i < ex.sets.length; i++) {
        final ProtoSet s = ex.sets[i];
        if (!s.done &&
            ((s.kg != null && s.reps != null) || ex.previousFor(i) != null)) {
          n++;
        }
      }
    }
    return n;
  }

  int get untickedTotal => exercises.fold(
      0, (int n, ProtoExercise ex) => n + ex.sets.length - ex.doneCount);

  void discardUnticked() {
    for (final ProtoExercise ex in exercises) {
      ex.sets.removeWhere((ProtoSet s) => !s.done);
    }
    _log('Finish: discarded unticked sets');
    _recompute();
    notifyListeners();
  }

  /// The UI surfaces for the next set to log: the first unticked set.
  (ProtoExercise, ProtoSet)? get nextUp {
    for (final ProtoExercise ex in exercises) {
      for (final ProtoSet s in ex.sets) {
        if (!s.done) return (ex, s);
      }
    }
    return null;
  }

  @override
  void dispose() {
    _ticker.cancel();
    super.dispose();
  }
}

/// Survives variant switches (each switch rebuilds the route).
final ProtoSession protoSession = ProtoSession();

/// Which field the in-app keypad is editing.
enum ProtoField { kg, reps, rir }

class ProtoFocus {
  const ProtoFocus(this.exercise, this.set, this.field);
  final ProtoExercise exercise;
  final ProtoSet set;
  final ProtoField field;
}

/// Types into the focused field; the keypad owns the text buffer so "95."
/// can be typed on the way to "95.5".
class ProtoKeypadBuffer {
  String text = '';
  void load(ProtoSession s, ProtoFocus f) {
    switch (f.field) {
      case ProtoField.kg:
        text = f.set.kg == null ? '' : fmtKg(f.set.kg!);
      case ProtoField.reps:
        text = f.set.reps?.toString() ?? '';
      case ProtoField.rir:
        text = f.set.rir?.toString() ?? '';
    }
  }

  void press(ProtoSession s, ProtoFocus f, String key) {
    if (key == '⌫') {
      if (text.isNotEmpty) text = text.substring(0, text.length - 1);
    } else if (key == '.') {
      if (f.field == ProtoField.kg && !text.contains('.')) text += '.';
    } else {
      if (text.length < 5) text += key;
    }
    switch (f.field) {
      case ProtoField.kg:
        s.setKg(f.set, double.tryParse(text));
      case ProtoField.reps:
        s.setReps(f.set, int.tryParse(text));
      case ProtoField.rir:
        s.setRir(f.set, int.tryParse(text));
    }
  }
}

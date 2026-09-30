import 'package:flutter/material.dart';

import '../../../core/active_workout.dart';
import '../../../core/theme/mayos_spacing.dart';
import '../../../core/theme/mayos_theme.dart';
import '../../../core/theme/mayos_typography.dart';

/// Which table cell the in-app keypad is editing (#123).
enum LoggerField { kg, reps, rir }

/// The keypad's caption for one field: `Bench Press · set 1 · Weight (kg)`.
String loggerFieldLabel(LoggerField field) => switch (field) {
      LoggerField.kg => 'Weight (kg)',
      LoggerField.reps => 'Reps',
      LoggerField.rir => 'Reps in reserve',
    };

/// One focused table cell, addressed by position in the Active workout.
@immutable
class LoggerCellFocus {
  const LoggerCellFocus(this.exerciseIndex, this.setIndex, this.field);

  final int exerciseIndex;
  final int setIndex;
  final LoggerField field;

  @override
  bool operator ==(Object other) =>
      other is LoggerCellFocus &&
      other.exerciseIndex == exerciseIndex &&
      other.setIndex == setIndex &&
      other.field == field;

  @override
  int get hashCode => Object.hash(exerciseIndex, setIndex, field);

  @override
  String toString() =>
      'LoggerCellFocus($exerciseIndex.$setIndex.${field.name})';
}

/// The keypad's Next order: kg → reps → RIR → the next set's kg, then null so
/// the keypad hides (#107 resolution).
LoggerCellFocus? nextLoggerCellFocus(
    ActiveWorkout workout, LoggerCellFocus focus) {
  if (focus.exerciseIndex < 0 ||
      focus.exerciseIndex >= workout.exercises.length) {
    return null;
  }
  final List<ActiveWorkoutSet> sets =
      workout.exercises[focus.exerciseIndex].sets;
  if (focus.setIndex < 0 || focus.setIndex >= sets.length) {
    return null;
  }
  switch (focus.field) {
    case LoggerField.kg:
      return LoggerCellFocus(
          focus.exerciseIndex, focus.setIndex, LoggerField.reps);
    case LoggerField.reps:
      return LoggerCellFocus(
          focus.exerciseIndex, focus.setIndex, LoggerField.rir);
    case LoggerField.rir:
      if (focus.setIndex + 1 < sets.length) {
        return LoggerCellFocus(
            focus.exerciseIndex, focus.setIndex + 1, LoggerField.kg);
      }
      return null;
  }
}

/// The app's own keypad that slides up when a cell is tapped: no system
/// keyboard, no steppers. RIR switches to one-tap chips 0–5+ and Unrated
/// (#107 resolution, #111) — whole numbers only, never a decimal field.
class LoggerKeypad extends StatefulWidget {
  const LoggerKeypad({
    super.key,
    required this.exerciseName,
    required this.setNumber,
    required this.field,
    required this.initialText,
    required this.onText,
    required this.onNext,
    required this.onHide,
    this.onRir,
    this.selectedRir,
  });

  final String exerciseName;
  final int setNumber;
  final LoggerField field;

  /// The cell's current text, used to seed the buffer whenever the focus
  /// moves to another cell.
  final String initialText;

  /// Called on every numeric key press with the edited buffer.
  final ValueChanged<String> onText;

  /// Called by the tall Next key.
  final VoidCallback onNext;

  /// Called by Hide (and by the RIR chips' Done affordance).
  final VoidCallback onHide;

  /// One-tap RIR chips: null means Unrated (#111).
  final ValueChanged<double?>? onRir;

  /// The focused set's current RIR, for the selected-chip highlight.
  final double? selectedRir;

  @override
  State<LoggerKeypad> createState() => _LoggerKeypadState();
}

class _LoggerKeypadState extends State<LoggerKeypad> {
  /// Key geometry in spacing tokens: a 4-based gap around a 56dp key
  /// (`xxl + xl`), so the keypad has no literal sizes of its own (#123 item
  /// 11).
  static const double _keyPadding = MayosSpacing.xxs;
  static const double _keyHeight = MayosSpacing.xxl + MayosSpacing.xl;

  late String _text = widget.initialText;
  late String _loadedFor = _focusKeyOf(widget);

  static String _focusKeyOf(LoggerKeypad k) =>
      '${k.exerciseName}#${k.setNumber}#${k.field.name}';

  @override
  void didUpdateWidget(LoggerKeypad oldWidget) {
    super.didUpdateWidget(oldWidget);
    final String key = _focusKeyOf(widget);
    if (key != _loadedFor) {
      _text = widget.initialText;
      _loadedFor = key;
    }
  }

  void _press(String label) {
    String next = _text;
    if (label == '⌫') {
      next = _text.isEmpty ? '' : _text.substring(0, _text.length - 1);
    } else if (label == '.') {
      if (widget.field == LoggerField.kg && !_text.contains('.')) {
        next = '$_text.';
      } else {
        return;
      }
    } else {
      if (_text.length >= 5) {
        return;
      }
      next = '$_text$label';
    }
    setState(() => _text = next);
    widget.onText(next);
  }

  @override
  Widget build(BuildContext context) {
    final MayosThemeExtension c = MayosTheme.of(context);
    final double rowHeight = _keyHeight + 2 * _keyPadding;

    Widget key(String label,
        {VoidCallback? onTap, Color? bg, Color? fg, Key? key}) {
      final bool enabled = onTap != null;
      return Expanded(
        child: Padding(
          padding: const EdgeInsets.all(_keyPadding),
          child: Material(
            color: bg ?? c.surfaceElevated,
            borderRadius: MayosRadii.mediumRadius,
            child: InkWell(
              key: key,
              borderRadius: MayosRadii.mediumRadius,
              onTap: onTap,
              child: Opacity(
                opacity: enabled ? 1 : 0.35,
                child: SizedBox(
                  height: _keyHeight,
                  child: Center(
                    child: Text(label,
                        style: MayosTypography.numericMedium
                            .copyWith(color: fg ?? c.textPrimary)),
                  ),
                ),
              ),
            ),
          ),
        ),
      );
    }

    final Widget body;
    if (widget.field == LoggerField.rir) {
      final double? selected = widget.selectedRir;
      body = Column(
        children: <Widget>[
          Row(
            children: <Widget>[
              for (final int v in <int>[0, 1, 2, 3, 4, 5])
                key(v == 5 ? '5+' : '$v',
                    key: ValueKey<String>('logger.rir.$v'),
                    onTap: () => widget.onRir?.call(v.toDouble()),
                    bg: selected == v.toDouble() ? c.accent : null,
                    fg: selected == v.toDouble() ? c.onAccent : null),
            ],
          ),
          Row(
            children: <Widget>[
              key('Unrated',
                  key: const ValueKey<String>('logger.rir.unrated'),
                  onTap: () => widget.onRir?.call(null)),
              key('Hide',
                  key: const ValueKey<String>('logger.key.hide'),
                  onTap: widget.onHide,
                  bg: c.secondarySurface),
              key('Next',
                  key: const ValueKey<String>('logger.key.next'),
                  onTap: widget.onNext,
                  bg: c.accent,
                  fg: c.onAccent),
            ],
          ),
        ],
      );
    } else {
      body = Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          Expanded(
            flex: 3,
            child: Column(
              children: <Widget>[
                Row(children: <Widget>[
                  for (final String label in <String>['1', '2', '3'])
                    key(label,
                        key: ValueKey<String>('logger.key.$label'),
                        onTap: () => _press(label)),
                ]),
                Row(children: <Widget>[
                  for (final String label in <String>['4', '5', '6'])
                    key(label,
                        key: ValueKey<String>('logger.key.$label'),
                        onTap: () => _press(label)),
                ]),
                Row(children: <Widget>[
                  for (final String label in <String>['7', '8', '9'])
                    key(label,
                        key: ValueKey<String>('logger.key.$label'),
                        onTap: () => _press(label)),
                ]),
                Row(
                  children: <Widget>[
                    key(widget.field == LoggerField.kg ? '.' : ' ',
                        key: const ValueKey<String>('logger.key.dot'),
                        onTap: widget.field == LoggerField.kg
                            ? () => _press('.')
                            : null),
                    key('0',
                        key: const ValueKey<String>('logger.key.0'),
                        onTap: () => _press('0')),
                    key('⌫',
                        key: const ValueKey<String>('logger.key.backspace'),
                        onTap: () => _press('⌫')),
                  ],
                ),
              ],
            ),
          ),
          Expanded(
            child: Column(
              children: <Widget>[
                Row(children: <Widget>[
                  key('Hide',
                      key: const ValueKey<String>('logger.key.hide'),
                      onTap: widget.onHide,
                      bg: c.secondarySurface),
                ]),
                SizedBox(
                  height: rowHeight * 3,
                  child: Row(
                    children: <Widget>[
                      Expanded(
                        child: Padding(
                          padding: const EdgeInsets.all(_keyPadding),
                          child: Material(
                            color: c.accent,
                            borderRadius: MayosRadii.mediumRadius,
                            child: InkWell(
                              key: const ValueKey<String>('logger.key.next'),
                              borderRadius: MayosRadii.mediumRadius,
                              onTap: widget.onNext,
                              child: Center(
                                child: Text('Next',
                                    style: MayosTypography.label
                                        .copyWith(color: c.onAccent)),
                              ),
                            ),
                          ),
                        ),
                      ),
                    ],
                  ),
                ),
              ],
            ),
          ),
        ],
      );
    }

    return Container(
      decoration: BoxDecoration(
        color: c.surface,
        border: Border(top: BorderSide(color: c.border)),
      ),
      // The keypad takes its own bottom safe area inside its surface, the
      // way the bottom bar does, so the keys stay above the system
      // navigation even though the frame no longer insets the body (#160).
      child: SafeArea(
        top: false,
        // The route Scaffold may clear padding while retaining viewPadding.
        maintainBottomViewPadding: true,
        child: Padding(
          padding: const EdgeInsets.fromLTRB(MayosSpacing.xs,
              MayosSpacing.xs, MayosSpacing.xs, MayosSpacing.xs),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: <Widget>[
              Padding(
                padding: const EdgeInsets.fromLTRB(
                    MayosSpacing.xs, 0, MayosSpacing.xs, MayosSpacing.xs),
                child: Text(
                  '${widget.exerciseName} · set ${widget.setNumber} · '
                  '${loggerFieldLabel(widget.field)}',
                  style: MayosTypography.caption.copyWith(color: c.textMuted),
                ),
              ),
              body,
            ],
          ),
        ),
      ),
    );
  }
}

import 'package:flutter/material.dart';

import '../../../core/models.dart';
import '../../../core/theme/mayos_spacing.dart';
import '../../../core/theme/mayos_theme.dart';
import '../../../core/theme/mayos_typography.dart';
import '../../../core/ui/mayos_card.dart';
import '../../../core/ui/mayos_choice_card.dart';
import '../../../core/ui/mayos_scaffold.dart';
import '../../../core/ui/mayos_text_field.dart';
import 'proportion_silhouette.dart';

// ---------------------------------------------------------------------------
// Domain presentation helpers
//
// The set of fields, allowed values, ranges, and explanation text all come from
// the intake API response. These helpers only turn a wire value into a readable
// label or a unit; they never define the domain.
// ---------------------------------------------------------------------------

/// A readable label for one allowed value of a field.
String optionLabel(String fieldName, String value) {
  switch (value) {
    case 'long_legs':
      return 'Legs longer than torso';
    case 'long_torso':
      return 'Torso longer than legs';
    case 'balanced':
      return 'Balanced';
    case 'male':
      return 'Male';
    case 'female':
      return 'Female';
    case 'low':
      return 'Low';
    case 'high':
      return 'High';
  }
  return value
      .split('_')
      .map((String part) =>
          part.isEmpty ? part : '${part[0].toUpperCase()}${part.substring(1)}')
      .join(' ');
}

/// The measurement unit shown beside a numeric field, or null.
String? unitFor(String fieldName) => switch (fieldName) {
      'height_cm' => 'cm',
      'weight_kg' => 'kg',
      'age' => 'years',
      'training_age_years' => 'years',
      _ => null,
    };

/// The editorial question for one field.
String questionFor(String fieldName) => switch (fieldName) {
      'gender' => 'Which specialization should shape your training?',
      'proportions' => 'Which best describes your body proportions?',
      'age' => 'How old are you?',
      'height_cm' => 'How tall are you?',
      'weight_kg' => 'What do you weigh?',
      'training_age_years' => 'How long have you been training?',
      'current_goal' => "What's your main goal right now?",
      'long_term_goal' => 'Where do you want to be long term?',
      'weekly_frequency' => 'How many days a week can you train?',
      'equipment_access' => 'What can you train with?',
      'injuries_or_limitations' => 'Anything to work around?',
      'stress_and_sleep' => "How's your recovery?",
      'rep_preference' => 'What rep range do you prefer?',
      _ => optionLabel('', fieldName),
    };

/// A short line under the question. The API's own explanation is used verbatim
/// when it provides one, so the app never invents a training claim.
String? explanationFor(IntakeField field) {
  final String? explanation = field.explanation;
  if (explanation == null || explanation.isEmpty) {
    return null;
  }
  return explanation;
}

/// How one saved answer reads on the review screen.
String displayAnswer(IntakeField field) {
  final Object? answer = field.answer;
  if (answer == null) {
    return 'Not answered';
  }
  switch (field.type) {
    case 'enum':
      final String value = answer.toString();
      if (field.name == 'rep_preference' && value == 'balanced') {
        return 'Balanced';
      }
      return optionLabel(field.name, value);
    case 'int':
    case 'float':
      final num? value = answer is num ? answer : num.tryParse('$answer');
      if (value == null) {
        return answer.toString();
      }
      if (field.name == 'weekly_frequency') {
        final int days = value.round();
        return '$days ${days == 1 ? 'day' : 'days'}/week';
      }
      final String unit = unitFor(field.name) ?? '';
      final String number = value == value.roundToDouble()
          ? value.round().toString()
          : value.toString();
      return unit.isEmpty ? number : '$number $unit';
    default:
      return answer.toString();
  }
}

/// A compact label shown on the review screen.
String reviewLabel(String fieldName) => switch (fieldName) {
      'gender' => 'Specialization',
      'proportions' => 'Proportions',
      'age' => 'Age',
      'height_cm' => 'Height',
      'weight_kg' => 'Weight',
      'training_age_years' => 'Training age',
      'current_goal' => 'Current goal',
      'long_term_goal' => 'Long-term goal',
      'weekly_frequency' => 'Weekly frequency',
      'equipment_access' => 'Equipment',
      'injuries_or_limitations' => 'Injuries or limitations',
      'stress_and_sleep' => 'Stress and sleep',
      'rep_preference' => 'Rep preference',
      _ => optionLabel('', fieldName),
    };

ProportionShape proportionShapeFor(String value) => switch (value) {
      'long_legs' => ProportionShape.longLegs,
      'long_torso' => ProportionShape.longTorso,
      _ => ProportionShape.balanced,
    };

/// Whether a submitted value satisfies the field's contract locally, so the
/// Continue action can be disabled before a round trip. The server re-validates.
bool isFieldAnswerValid(IntakeField field, Object? value) {
  if (!field.isRequired && (value == null || value == '')) {
    return true;
  }
  switch (field.type) {
    case 'enum':
      return value is String && field.allowedValues.contains(value);
    case 'int':
    case 'float':
      final num? number = value is num ? value : num.tryParse('$value');
      if (number == null) {
        return false;
      }
      if (field.type == 'int' && number != number.roundToDouble()) {
        return false;
      }
      final double? min = field.minimum;
      final double? max = field.maximum;
      if (min != null && number < min) {
        return false;
      }
      if (max != null && number > max) {
        return false;
      }
      return true;
    default:
      return value is String && value.trim().length >= 2;
  }
}

// ---------------------------------------------------------------------------
// Screen chrome
// ---------------------------------------------------------------------------

/// The shared frame for every onboarding step: a back affordance, a thin
/// segmented progress bar, a scrolling body, and a deliberate bottom action.
class OnboardingScaffold extends StatelessWidget {
  const OnboardingScaffold({
    super.key,
    required this.child,
    this.onBack,
    this.answered = 0,
    this.total = 0,
    this.bottomBar,
  });

  final Widget child;
  final VoidCallback? onBack;
  final int answered;
  final int total;
  final Widget? bottomBar;

  @override
  Widget build(BuildContext context) {
    return MayosScaffold(
      header: _OnboardingHeader(
        onBack: onBack,
        answered: answered,
        total: total,
      ),
      body: child,
      bottomBar: bottomBar,
    );
  }
}

class _OnboardingHeader extends StatelessWidget {
  const _OnboardingHeader({
    required this.onBack,
    required this.answered,
    required this.total,
  });

  final VoidCallback? onBack;
  final int answered;
  final int total;

  @override
  Widget build(BuildContext context) {
    final MayosThemeExtension c = MayosTheme.of(context);
    return Padding(
      padding: const EdgeInsets.fromLTRB(
          MayosSpacing.lg, MayosSpacing.sm, MayosSpacing.lg, MayosSpacing.xs),
      child: Row(
        children: <Widget>[
          SizedBox(
            width: 48,
            child: onBack == null
                ? null
                : IconButton(
                    key: const Key('onboarding_back'),
                    tooltip: 'Back',
                    onPressed: onBack,
                    icon: const Icon(Icons.arrow_back),
                  ),
          ),
          Expanded(
            child: total > 0
                ? OnboardingProgressBar(answered: answered, total: total)
                : const SizedBox.shrink(),
          ),
          if (total > 0) ...<Widget>[
            const SizedBox(width: MayosSpacing.sm),
            Text(
              '$answered/$total',
              style: MayosTypography.caption.copyWith(color: c.textMuted),
            ),
          ] else
            const SizedBox(width: 48),
        ],
      ),
    );
  }
}

/// A subtle segmented progress indicator. The count in the header is quiet
/// metadata, never the dominant element.
class OnboardingProgressBar extends StatelessWidget {
  const OnboardingProgressBar({
    super.key,
    required this.answered,
    required this.total,
  });

  final int answered;
  final int total;

  @override
  Widget build(BuildContext context) {
    final MayosThemeExtension c = MayosTheme.of(context);
    return Semantics(
      label: 'Progress: $answered of $total answered',
      child: Row(
        children: <Widget>[
          for (int i = 0; i < total; i++)
            Expanded(
              child: AnimatedContainer(
                duration: MayosMotion.fast,
                curve: MayosMotion.standard,
                height: 3,
                margin: const EdgeInsets.symmetric(horizontal: 1.5),
                decoration: BoxDecoration(
                  color: i < answered ? c.accent : c.surfaceSunken,
                  borderRadius: BorderRadius.circular(999),
                ),
              ),
            ),
        ],
      ),
    );
  }
}

/// The large editorial question and its short sans explanation.
class OnboardingQuestion extends StatelessWidget {
  const OnboardingQuestion({
    super.key,
    required this.question,
    this.explanation,
    this.note,
  });

  final String question;
  final String? explanation;

  /// An optional quiet line (for example, "Saved from your earlier setup").
  final String? note;

  @override
  Widget build(BuildContext context) {
    final MayosThemeExtension c = MayosTheme.of(context);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: <Widget>[
        Text(
          question,
          style: MayosTypography.pageHeading.copyWith(
            color: c.textPrimary,
            fontSize: 30,
            height: 1.12,
          ),
        ),
        if (explanation != null) ...<Widget>[
          const SizedBox(height: MayosSpacing.sm),
          Text(
            explanation!,
            style: MayosTypography.bodySecondary.copyWith(
              color: c.textSecondary,
              height: 1.5,
            ),
          ),
        ],
        if (note != null) ...<Widget>[
          const SizedBox(height: MayosSpacing.xs),
          Row(
            children: <Widget>[
              Icon(Icons.history, size: 14, color: c.textMuted),
              const SizedBox(width: MayosSpacing.xxs),
              Flexible(
                child: Text(
                  note!,
                  style: MayosTypography.caption.copyWith(color: c.textMuted),
                ),
              ),
            ],
          ),
        ],
      ],
    );
  }
}

/// A left-aligned inline error, used for local and server validation messages.
class OnboardingInlineError extends StatelessWidget {
  const OnboardingInlineError({super.key, required this.message});

  final String message;

  @override
  Widget build(BuildContext context) {
    final MayosThemeExtension c = MayosTheme.of(context);
    return Semantics(
      liveRegion: true,
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          Icon(Icons.error_outline, size: 16, color: c.danger),
          const SizedBox(width: MayosSpacing.xs),
          Expanded(
            child: Text(
              message,
              style: MayosTypography.bodySecondary.copyWith(color: c.danger),
            ),
          ),
        ],
      ),
    );
  }
}

/// The bottom action bar: a full-width primary action with optional quiet
/// actions beneath it. Kept above the keyboard by the scaffold's resize.
class OnboardingActions extends StatelessWidget {
  const OnboardingActions({
    super.key,
    required this.primary,
    this.secondary,
  });

  final Widget primary;
  final Widget? secondary;

  @override
  Widget build(BuildContext context) {
    final MayosThemeExtension c = MayosTheme.of(context);
    return DecoratedBox(
      decoration: BoxDecoration(
        color: c.canvas,
        border: Border(top: BorderSide(color: c.border)),
      ),
      child: SafeArea(
        top: false,
        child: Padding(
          padding: const EdgeInsets.fromLTRB(MayosSpacing.lg, MayosSpacing.sm,
              MayosSpacing.lg, MayosSpacing.md),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: <Widget>[
              primary,
              if (secondary != null) ...<Widget>[
                const SizedBox(height: MayosSpacing.xs),
                secondary!,
              ],
            ],
          ),
        ),
      ),
    );
  }
}

/// A vertically scrolling step body with consistent padding.
class OnboardingStepBody extends StatelessWidget {
  const OnboardingStepBody({super.key, required this.children});

  final List<Widget> children;

  @override
  Widget build(BuildContext context) {
    return SingleChildScrollView(
      padding: const EdgeInsets.fromLTRB(
          MayosSpacing.lg, MayosSpacing.xl, MayosSpacing.lg, MayosSpacing.xxl),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: children,
      ),
    );
  }
}

// ---------------------------------------------------------------------------
// Choice interactions
// ---------------------------------------------------------------------------

/// One selectable enum option.
class OnboardingChoiceOption {
  const OnboardingChoiceOption({
    required this.value,
    required this.label,
    this.subtitle,
    this.icon,
  });

  final String value;
  final String label;
  final String? subtitle;
  final IconData? icon;
}

/// A column of large choice cards for a plain enum field.
class OnboardingChoiceList extends StatelessWidget {
  const OnboardingChoiceList({
    super.key,
    required this.fieldName,
    required this.options,
    required this.selected,
    required this.onSelected,
  });

  final String fieldName;
  final List<OnboardingChoiceOption> options;
  final String? selected;
  final ValueChanged<String> onSelected;

  @override
  Widget build(BuildContext context) {
    final MayosThemeExtension c = MayosTheme.of(context);
    return Column(
      children: <Widget>[
        for (final OnboardingChoiceOption option in options)
          Padding(
            padding: const EdgeInsets.only(bottom: MayosSpacing.sm),
            child: MayosChoiceCard(
              key: Key('${fieldName}_option_${option.value}'),
              title: option.label,
              subtitle: option.subtitle,
              selected: option.value == selected,
              onTap: () => onSelected(option.value),
              leading: option.icon == null
                  ? null
                  : Container(
                      width: 42,
                      height: 42,
                      decoration: BoxDecoration(
                        color: option.value == selected
                            ? c.accentSubtle
                            : c.secondarySurface,
                        borderRadius: BorderRadius.circular(12),
                      ),
                      child: Icon(
                        option.icon,
                        size: 22,
                        color: option.value == selected
                            ? c.accent
                            : c.textSecondary,
                      ),
                    ),
            ),
          ),
      ],
    );
  }
}

/// The three expressive proportion choices. Uses a horizontal composition when
/// space allows and falls back to compact stacked rows for large text scales or
/// small screens, so the heading, all three choices, and the CTA fit.
class ProportionSelector extends StatelessWidget {
  const ProportionSelector({
    super.key,
    required this.field,
    required this.selected,
    required this.onSelected,
  });

  final IntakeField field;
  final String? selected;
  final ValueChanged<String> onSelected;

  @override
  Widget build(BuildContext context) {
    final double scale = MediaQuery.textScalerOf(context).scale(14) / 14;
    return LayoutBuilder(
      builder: (BuildContext context, BoxConstraints constraints) {
        final bool stacked = scale > 1.35 || constraints.maxWidth < 340;
        final bool wide = constraints.maxWidth > 520;
        final List<Widget> cards = <Widget>[
          for (final String value in field.allowedValues)
            _ProportionCard(
              value: value,
              title: optionLabel(field.name, value),
              caption: field.optionDescriptions[value],
              silhouette: ProportionSilhouette(
                shape: proportionShapeFor(value),
                selected: value == selected,
              ),
              selected: value == selected,
              onTap: () => onSelected(value),
              stacked: stacked,
            ),
        ];
        if (stacked) {
          return Column(
            children: <Widget>[
              for (final Widget card in cards)
                Padding(
                  padding: const EdgeInsets.only(bottom: MayosSpacing.xs),
                  child: card,
                ),
            ],
          );
        }
        return IntrinsicHeight(
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: <Widget>[
              for (int i = 0; i < cards.length; i++) ...<Widget>[
                if (i > 0)
                  SizedBox(width: wide ? MayosSpacing.md : MayosSpacing.xs),
                Expanded(child: cards[i]),
              ],
            ],
          ),
        );
      },
    );
  }
}

class _ProportionCard extends StatefulWidget {
  const _ProportionCard({
    required this.value,
    required this.title,
    required this.caption,
    required this.silhouette,
    required this.selected,
    required this.onTap,
    required this.stacked,
  });

  final String value;
  final String title;
  final String? caption;
  final Widget silhouette;
  final bool selected;
  final VoidCallback onTap;
  final bool stacked;

  @override
  State<_ProportionCard> createState() => _ProportionCardState();
}

class _ProportionCardState extends State<_ProportionCard> {
  bool _pressed = false;

  @override
  Widget build(BuildContext context) {
    final MayosThemeExtension c = MayosTheme.of(context);
    final bool selected = widget.selected;
    final Widget art = SizedBox(
      width: widget.stacked ? 58 : null,
      height: widget.stacked ? 70 : 126,
      child: widget.silhouette,
    );
    final Widget label = Text(
      widget.title,
      textAlign: widget.stacked ? TextAlign.start : TextAlign.center,
      style: MayosTypography.exerciseTitle.copyWith(
        color: selected ? c.accent : c.textPrimary,
      ),
    );
    final Widget? caption = widget.caption == null
        ? null
        : Text(
            widget.caption!,
            textAlign: widget.stacked ? TextAlign.start : TextAlign.center,
            style: MayosTypography.caption.copyWith(color: c.textSecondary),
          );

    return Semantics(
      button: true,
      selected: selected,
      label:
          '${widget.title}. ${widget.caption ?? ''} ${selected ? 'Selected' : 'Not selected'}',
      excludeSemantics: true,
      child: AnimatedScale(
        scale: _pressed ? 0.98 : 1,
        duration: MayosMotion.fast,
        curve: MayosMotion.standard,
        child: AnimatedContainer(
          key: Key('proportions_option_${widget.value}'),
          duration: MayosMotion.base,
          curve: MayosMotion.standard,
          padding: EdgeInsets.all(
              widget.stacked ? MayosSpacing.sm : MayosSpacing.sm + 2),
          decoration: BoxDecoration(
            color: selected ? c.selectedSurface : c.surface,
            borderRadius: BorderRadius.circular(18),
            border: Border.all(
              color: selected ? c.selectedBorder : c.border,
              width: selected ? 1.6 : 1,
            ),
          ),
          child: Material(
            type: MaterialType.transparency,
            child: InkWell(
              onTap: widget.onTap,
              onHighlightChanged: (bool pressed) =>
                  setState(() => _pressed = pressed),
              splashFactory: NoSplash.splashFactory,
              highlightColor: Colors.transparent,
              hoverColor: Colors.transparent,
              focusColor: Colors.transparent,
              borderRadius: BorderRadius.circular(18),
              child: widget.stacked
                  ? Row(
                      children: <Widget>[
                        art,
                        const SizedBox(width: MayosSpacing.sm),
                        Expanded(
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            mainAxisSize: MainAxisSize.min,
                            children: <Widget>[
                              label,
                              if (caption != null) ...<Widget>[
                                const SizedBox(height: 2),
                                caption,
                              ],
                            ],
                          ),
                        ),
                        const SizedBox(width: MayosSpacing.xs),
                        _SelectionMark(selected: selected),
                      ],
                    )
                  : Column(
                      mainAxisSize: MainAxisSize.min,
                      children: <Widget>[
                        Stack(
                          alignment: Alignment.topRight,
                          children: <Widget>[
                            Padding(
                              padding: const EdgeInsets.symmetric(
                                  horizontal: MayosSpacing.xs),
                              child: art,
                            ),
                            _SelectionMark(selected: selected),
                          ],
                        ),
                        const SizedBox(height: MayosSpacing.xs),
                        label,
                        if (caption != null) ...<Widget>[
                          const SizedBox(height: 2),
                          caption,
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

class _SelectionMark extends StatelessWidget {
  const _SelectionMark({required this.selected});

  final bool selected;

  @override
  Widget build(BuildContext context) {
    final MayosThemeExtension c = MayosTheme.of(context);
    return AnimatedContainer(
      duration: MayosMotion.base,
      curve: MayosMotion.standard,
      width: 22,
      height: 22,
      decoration: BoxDecoration(
        shape: BoxShape.circle,
        color: selected ? c.accent : Colors.transparent,
        border: Border.all(
          color: selected ? c.accent : c.borderStrong,
          width: 1.5,
        ),
      ),
      child: selected ? Icon(Icons.check, size: 14, color: c.onAccent) : null,
    );
  }
}

// ---------------------------------------------------------------------------
// Numeric interaction
// ---------------------------------------------------------------------------

/// A large stepper with a direct-entry fallback, constrained to the field's
/// API range.
class NumericFieldEditor extends StatefulWidget {
  const NumericFieldEditor({
    super.key,
    required this.fieldName,
    required this.minimum,
    required this.maximum,
    required this.integer,
    required this.step,
    required this.unit,
    required this.value,
    required this.onChanged,
  });

  final String fieldName;
  final double minimum;
  final double maximum;
  final bool integer;
  final double step;
  final String? unit;
  final num? value;
  final ValueChanged<num?> onChanged;

  @override
  State<NumericFieldEditor> createState() => _NumericFieldEditorState();
}

class _NumericFieldEditorState extends State<NumericFieldEditor> {
  late final TextEditingController _controller =
      TextEditingController(text: _format(widget.value));
  bool _direct = false;

  @override
  void didUpdateWidget(NumericFieldEditor oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (widget.value != oldWidget.value && !_direct) {
      final String next = _format(widget.value);
      if (_controller.text != next) {
        _controller.text = next;
      }
    }
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  String _format(num? value) {
    if (value == null) {
      return '';
    }
    if (widget.integer || value == value.roundToDouble()) {
      return value.round().toString();
    }
    return value.toString();
  }

  void _emit(num? value) {
    if (value == null) {
      widget.onChanged(null);
      return;
    }
    double clamped = value.toDouble().clamp(widget.minimum, widget.maximum);
    if (widget.integer) {
      clamped = clamped.roundToDouble();
    }
    widget.onChanged(clamped);
  }

  void _step(int direction) {
    if (!_direct) {
      _controller.text = _format(widget.value);
    }
    final double base = widget.value?.toDouble() ??
        (direction > 0
            ? widget.minimum - widget.step
            : widget.maximum + widget.step);
    _emit(base + widget.step * direction);
  }

  bool get _canDecrement =>
      widget.value == null || widget.value!.toDouble() > widget.minimum;
  bool get _canIncrement =>
      widget.value == null || widget.value!.toDouble() < widget.maximum;

  @override
  Widget build(BuildContext context) {
    final MayosThemeExtension c = MayosTheme.of(context);
    final String display = widget.value == null ? '—' : _format(widget.value);
    final String range = widget.integer
        ? '${widget.minimum.round()}–${widget.maximum.round()}'
        : '${_trim(widget.minimum)}–${_trim(widget.maximum)}';

    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: <Widget>[
        Container(
          padding: const EdgeInsets.symmetric(
              horizontal: MayosSpacing.md, vertical: MayosSpacing.lg),
          decoration: BoxDecoration(
            color: c.surface,
            borderRadius: BorderRadius.circular(20),
            border: Border.all(color: c.border),
          ),
          child: Column(
            children: <Widget>[
              Semantics(
                label:
                    '${widget.fieldName} $display ${widget.unit ?? ''}'.trim(),
                excludeSemantics: true,
                child: Row(
                  mainAxisAlignment: MainAxisAlignment.center,
                  crossAxisAlignment: CrossAxisAlignment.baseline,
                  textBaseline: TextBaseline.alphabetic,
                  children: <Widget>[
                    Flexible(
                      child: Text(
                        display,
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                        style: MayosTypography.numeric.copyWith(
                          fontSize: 56,
                          color: c.textPrimary,
                        ),
                      ),
                    ),
                    if (widget.unit != null) ...<Widget>[
                      const SizedBox(width: MayosSpacing.xs),
                      Padding(
                        padding: const EdgeInsets.only(bottom: 8),
                        child: Text(
                          widget.unit!,
                          style: MayosTypography.label
                              .copyWith(color: c.textSecondary),
                        ),
                      ),
                    ],
                  ],
                ),
              ),
              const SizedBox(height: MayosSpacing.md),
              Row(
                children: <Widget>[
                  Expanded(
                    child: _StepButton(
                      buttonKey: Key('${widget.fieldName}_decrement'),
                      icon: Icons.remove,
                      semanticsLabel: 'Decrease',
                      onPressed: _canDecrement ? () => _step(-1) : null,
                    ),
                  ),
                  const SizedBox(width: MayosSpacing.xs),
                  Expanded(
                    child: _StepButton(
                      buttonKey: Key('${widget.fieldName}_increment'),
                      icon: Icons.add,
                      semanticsLabel: 'Increase',
                      onPressed: _canIncrement ? () => _step(1) : null,
                    ),
                  ),
                ],
              ),
            ],
          ),
        ),
        const SizedBox(height: MayosSpacing.xs),
        Row(
          children: <Widget>[
            Expanded(
              child: Text(
                widget.unit == null ? range : '$range ${widget.unit}',
                style: MayosTypography.caption.copyWith(color: c.textMuted),
              ),
            ),
            Flexible(
              child: TextButton(
                key: Key('${widget.fieldName}_direct_toggle'),
                onPressed: () => setState(() => _direct = !_direct),
                child: Text(
                  _direct ? 'Use the stepper' : 'Type a value',
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                ),
              ),
            ),
          ],
        ),
        if (_direct) ...<Widget>[
          const SizedBox(height: MayosSpacing.xs),
          MayosTextField(
            fieldKey: Key('${widget.fieldName}_input'),
            controller: _controller,
            keyboardType: widget.integer
                ? TextInputType.number
                : const TextInputType.numberWithOptions(decimal: true),
            hint: '${widget.minimum.round()} to ${widget.maximum.round()}',
            onChanged: (String text) {
              final String trimmed = text.trim();
              if (trimmed.isEmpty) {
                widget.onChanged(null);
                return;
              }
              final num? parsed = num.tryParse(trimmed);
              widget.onChanged(parsed);
            },
          ),
        ],
      ],
    );
  }

  static String _trim(double value) => value == value.roundToDouble()
      ? value.round().toString()
      : value.toString();
}

class _StepButton extends StatelessWidget {
  const _StepButton({
    required this.buttonKey,
    required this.icon,
    required this.semanticsLabel,
    required this.onPressed,
  });

  final Key buttonKey;
  final IconData icon;
  final String semanticsLabel;
  final VoidCallback? onPressed;

  @override
  Widget build(BuildContext context) {
    final MayosThemeExtension c = MayosTheme.of(context);
    final bool enabled = onPressed != null;
    return Semantics(
      button: true,
      label: semanticsLabel,
      enabled: enabled,
      child: Material(
        color: enabled ? c.secondarySurface : c.surfaceSunken,
        borderRadius: BorderRadius.circular(14),
        child: InkWell(
          key: buttonKey,
          onTap: onPressed,
          borderRadius: BorderRadius.circular(14),
          child: SizedBox(
            height: 56,
            child: Icon(
              icon,
              color: enabled ? c.textPrimary : c.textDisabled,
            ),
          ),
        ),
      ),
    );
  }
}

/// A satisfying 1–5 (per the API range) weekly-frequency selector.
class FrequencySelector extends StatelessWidget {
  const FrequencySelector({
    super.key,
    required this.fieldName,
    required this.minimum,
    required this.maximum,
    required this.selected,
    required this.onSelected,
  });

  final String fieldName;
  final int minimum;
  final int maximum;
  final num? selected;
  final ValueChanged<int> onSelected;

  @override
  Widget build(BuildContext context) {
    final MayosThemeExtension c = MayosTheme.of(context);
    final int? value = selected?.round();
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: <Widget>[
        Wrap(
          spacing: MayosSpacing.xs,
          runSpacing: MayosSpacing.xs,
          children: <Widget>[
            for (int day = minimum; day <= maximum; day++)
              _FrequencyPill(
                value: day,
                selected: day == value,
                onTap: () => onSelected(day),
                fieldName: fieldName,
              ),
          ],
        ),
        const SizedBox(height: MayosSpacing.sm),
        Text(
          value == null
              ? 'Choose your weekly training days'
              : '$value ${value == 1 ? 'day' : 'days'} per week',
          style: MayosTypography.caption.copyWith(color: c.textMuted),
        ),
      ],
    );
  }
}

class _FrequencyPill extends StatelessWidget {
  const _FrequencyPill({
    required this.value,
    required this.selected,
    required this.onTap,
    required this.fieldName,
  });

  final int value;
  final bool selected;
  final VoidCallback onTap;
  final String fieldName;

  @override
  Widget build(BuildContext context) {
    final MayosThemeExtension c = MayosTheme.of(context);
    return Semantics(
      button: true,
      selected: selected,
      label: '$value ${value == 1 ? 'day' : 'days'} per week',
      excludeSemantics: true,
      child: AnimatedContainer(
        duration: MayosMotion.fast,
        curve: MayosMotion.standard,
        width: 56,
        decoration: BoxDecoration(
          color: selected ? c.selectedSurface : c.surface,
          borderRadius: BorderRadius.circular(14),
          border: Border.all(
            color: selected ? c.selectedBorder : c.border,
            width: selected ? 1.6 : 1,
          ),
        ),
        child: Material(
          type: MaterialType.transparency,
          child: InkWell(
            key: Key('${fieldName}_option_$value'),
            onTap: onTap,
            borderRadius: BorderRadius.circular(14),
            child: SizedBox(
              height: 64,
              child: Column(
                mainAxisAlignment: MainAxisAlignment.center,
                children: <Widget>[
                  Text(
                    '$value',
                    style: MayosTypography.numericSmall.copyWith(
                      fontSize: 20,
                      color: selected ? c.accent : c.textPrimary,
                    ),
                  ),
                  Text(
                    value == 1 ? 'day' : 'days',
                    style: MayosTypography.caption.copyWith(
                      color: selected ? c.accent : c.textMuted,
                    ),
                  ),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }
}

// ---------------------------------------------------------------------------
// Free-text interaction
// ---------------------------------------------------------------------------

/// A focused multiline input with tappable example answers. Tapping an example
/// fills the field; a 2-character minimum gates Continue.
class TextFieldEditor extends StatefulWidget {
  const TextFieldEditor({
    super.key,
    required this.fieldName,
    required this.controller,
    required this.hint,
    required this.examples,
    this.quickOptions = const <String>[],
    required this.onChanged,
  });

  final String fieldName;
  final TextEditingController controller;
  final String hint;
  final List<String> examples;

  /// Extra quick-fill options beyond the API examples (for example, "None").
  final List<String> quickOptions;
  final ValueChanged<String> onChanged;

  @override
  State<TextFieldEditor> createState() => _TextFieldEditorState();
}

class _TextFieldEditorState extends State<TextFieldEditor> {
  void _fill(String value) {
    widget.controller.text = value;
    widget.controller.selection = TextSelection.collapsed(offset: value.length);
    widget.onChanged(value);
    FocusScope.of(context).unfocus();
  }

  @override
  Widget build(BuildContext context) {
    final MayosThemeExtension c = MayosTheme.of(context);
    final List<String> chips = <String>[];
    for (final String chip in <String>[
      ...widget.quickOptions,
      ...widget.examples,
    ]) {
      if (!chips.contains(chip)) {
        chips.add(chip);
      }
    }
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: <Widget>[
        MayosTextField(
          fieldKey: Key('${widget.fieldName}_input'),
          controller: widget.controller,
          hint: widget.hint,
          maxLines: 4,
          keyboardType: TextInputType.multiline,
          onChanged: widget.onChanged,
        ),
        if (chips.isNotEmpty) ...<Widget>[
          const SizedBox(height: MayosSpacing.md),
          Text(
            'Tap an example to start',
            style: MayosTypography.caption.copyWith(color: c.textMuted),
          ),
          const SizedBox(height: MayosSpacing.xs),
          Wrap(
            spacing: MayosSpacing.xs,
            runSpacing: MayosSpacing.xs,
            children: <Widget>[
              for (int i = 0; i < chips.length; i++)
                _ExampleChip(
                  chipKey: Key('${widget.fieldName}_example_$i'),
                  label: chips[i],
                  onTap: () => _fill(chips[i]),
                ),
            ],
          ),
        ],
      ],
    );
  }
}

class _ExampleChip extends StatelessWidget {
  const _ExampleChip({
    required this.chipKey,
    required this.label,
    required this.onTap,
  });

  final Key chipKey;
  final String label;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final MayosThemeExtension c = MayosTheme.of(context);
    return Material(
      color: c.secondarySurface,
      borderRadius: BorderRadius.circular(12),
      child: InkWell(
        key: chipKey,
        onTap: onTap,
        borderRadius: BorderRadius.circular(12),
        child: Container(
          constraints: const BoxConstraints(minHeight: 48),
          padding: const EdgeInsets.symmetric(
              horizontal: MayosSpacing.sm, vertical: MayosSpacing.xs),
          decoration: BoxDecoration(
            borderRadius: BorderRadius.circular(12),
            border: Border.all(color: c.border),
          ),
          child: Text(
            label,
            style: MayosTypography.bodySecondary
                .copyWith(fontSize: 13, color: c.textSecondary),
          ),
        ),
      ),
    );
  }
}

// ---------------------------------------------------------------------------
// Review
// ---------------------------------------------------------------------------

/// A restrained group of answers on the review screen: one surface per section,
/// rows separated by dividers rather than one card per answer.
class ReviewSection extends StatelessWidget {
  const ReviewSection({
    super.key,
    required this.title,
    required this.fields,
    required this.onEdit,
  });

  final String title;
  final List<IntakeField> fields;
  final ValueChanged<IntakeField> onEdit;

  @override
  Widget build(BuildContext context) {
    final MayosThemeExtension c = MayosTheme.of(context);
    if (fields.isEmpty) {
      return const SizedBox.shrink();
    }
    return Padding(
      padding: const EdgeInsets.only(bottom: MayosSpacing.md),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: <Widget>[
          Padding(
            padding: const EdgeInsets.only(
                left: MayosSpacing.xxs, bottom: MayosSpacing.xs),
            child: Text(
              title.toUpperCase(),
              style: MayosTypography.caption.copyWith(
                color: c.textMuted,
                letterSpacing: 1.2,
              ),
            ),
          ),
          MayosCard(
            padding: EdgeInsets.zero,
            child: Column(
              children: <Widget>[
                for (int i = 0; i < fields.length; i++) ...<Widget>[
                  _ReviewRow(field: fields[i], onEdit: () => onEdit(fields[i])),
                  if (i < fields.length - 1)
                    Divider(height: 1, thickness: 1, color: c.border),
                ],
              ],
            ),
          ),
        ],
      ),
    );
  }
}

class _ReviewRow extends StatelessWidget {
  const _ReviewRow({required this.field, required this.onEdit});

  final IntakeField field;
  final VoidCallback onEdit;

  @override
  Widget build(BuildContext context) {
    final MayosThemeExtension c = MayosTheme.of(context);
    final String value = displayAnswer(field);
    final bool answered = field.answer != null;
    return InkWell(
      key: Key('review_edit_${field.name}'),
      onTap: onEdit,
      child: Padding(
        padding: const EdgeInsets.symmetric(
            horizontal: MayosSpacing.md, vertical: MayosSpacing.sm + 2),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: <Widget>[
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: <Widget>[
                  Text(
                    reviewLabel(field.name),
                    style: MayosTypography.caption.copyWith(color: c.textMuted),
                  ),
                  const SizedBox(height: MayosSpacing.xxs),
                  Text(
                    value,
                    style: MayosTypography.body.copyWith(
                      color: answered ? c.textPrimary : c.textMuted,
                    ),
                  ),
                ],
              ),
            ),
            const SizedBox(width: MayosSpacing.sm),
            Padding(
              padding: const EdgeInsets.only(top: MayosSpacing.xxs),
              child:
                  Icon(Icons.edit_outlined, size: 20, color: c.textSecondary),
            ),
          ],
        ),
      ),
    );
  }
}

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../../core/api_client.dart';
import '../../../core/display_language/catalog.dart';
import '../../../core/display_language/controller.dart';
import '../../../core/display_language/copy_context.dart';
import '../../../core/display_language/onboarding_copy.dart';
import '../../../core/connectivity.dart';
import '../../../core/connectivity_message.dart';
import '../../../core/models.dart';
import '../../../core/theme/mayos_spacing.dart';
import '../../../core/theme/mayos_theme.dart';
import '../../../core/theme/mayos_typography.dart';
import '../../../core/ui/mayos_button.dart';
import '../../../core/ui/mayos_card.dart';
import '../../../core/ui/mayos_logo.dart';
import '../../../core/ui/mayos_player_column.dart';
import '../../../core/ui/mayos_progress.dart';
import '../../../providers.dart';
import '../../../router.dart';
import 'coach_code_form.dart';
import 'onboarding_widgets.dart';

/// The focused, full-screen MAYOS onboarding flow (#51).
///
/// Replaces the former chat-like intake with one composition per named decision
/// from the structured intake API (#50): the hosted-processing disclosure
/// gates every answer, each step saves through [ApiClient.saveIntakeAnswer],
/// earlier answers can be edited until the player confirms, and the first
/// program is only created by an explicit action on the review screen.
class OnboardingScreen extends ConsumerStatefulWidget {
  const OnboardingScreen({super.key});

  @override
  ConsumerState<OnboardingScreen> createState() => _OnboardingScreenState();
}

class _CoachInviteRedeemDialog extends StatelessWidget {
  const _CoachInviteRedeemDialog();

  @override
  Widget build(BuildContext context) => AlertDialog(
        title: Text(displayCopyOf(context).enableCoaching),
        content: CoachCodeForm(
          description: displayCopyOf(context).enterCoachCodeLead,
          fieldKey: const Key('onboarding_coach_code'),
          submitButtonKey: const Key('onboarding_redeem_coach_code'),
          onRedeemed: () => Navigator.of(context).pop(true),
        ),
        actions: <Widget>[
          TextButton(
            onPressed: () => Navigator.of(context).pop(false),
            child: Text(displayCopyOf(context).cancel),
          ),
        ],
      );
}

enum _OnboardingPhase { loading, error, disclosure, answering }

class _OnboardingScreenState extends ConsumerState<OnboardingScreen> {
  OnboardingIntake? _intake;
  _OnboardingPhase _phase = _OnboardingPhase.loading;

  String? _currentField;
  bool _editingFromReview = false;
  final Map<String, Object?> _draft = <String, Object?>{};
  final Map<String, TextEditingController> _controllers =
      <String, TextEditingController>{};

  bool _saving = false;
  bool _disclosureSaving = false;
  bool _submitting = false;
  String? _error;
  String? _disclosureError;
  String? _stepError;
  String? _confirmError;

  ApiClient get _api => ref.read(apiClientProvider);

  List<IntakeField> get _fields => _intake?.fields ?? const <IntakeField>[];

  @override
  void initState() {
    super.initState();
    Future<void>.microtask(_load);
  }

  @override
  void dispose() {
    for (final TextEditingController controller in _controllers.values) {
      controller.dispose();
    }
    super.dispose();
  }

  // -- data -----------------------------------------------------------------

  Future<void> _load() async {
    setState(() {
      _phase = _OnboardingPhase.loading;
      _error = null;
    });
    try {
      final OnboardingIntake intake = await _api.onboardingIntake();
      if (!mounted) {
        return;
      }
      if (intake.isConfirmed) {
        _finishToHome();
        return;
      }
      setState(() {
        _intake = intake;
        if (!intake.disclosureAcknowledged) {
          _phase = _OnboardingPhase.disclosure;
        } else {
          _phase = _OnboardingPhase.answering;
          _editingFromReview = false;
          final String? first = _firstUnanswered(intake);
          _prepareField(first);
          _currentField = first;
        }
      });
    } on ApiException catch (error) {
      if (!mounted) {
        return;
      }
      setState(() {
        _phase = _OnboardingPhase.error;
        _error = mutationFailureMessage(
          error,
          connectionMessage: displayCopyOf(context).connectionFailure,
        );
      });
    }
  }

  /// The first required field with no saved answer, or null when they are all
  /// answered (the flow then opens on the review screen).
  String? _firstUnanswered(OnboardingIntake intake) {
    for (final IntakeField field in intake.fields) {
      if (field.isRequired && !field.answered) {
        return field.name;
      }
    }
    return null;
  }

  IntakeField? _fieldByName(String? name) {
    if (name == null) {
      return null;
    }
    for (final IntakeField field in _fields) {
      if (field.name == name) {
        return field;
      }
    }
    return null;
  }

  Object? _valueFor(IntakeField field) {
    if (_draft.containsKey(field.name)) {
      return _draft[field.name];
    }
    return field.answer;
  }

  /// Seeds a starting value for a numeric stepper and creates the controller
  /// for a text field the first time it is shown. Values already saved by the
  /// server always win over a starting value.
  void _prepareField(String? name) {
    final IntakeField? field = _fieldByName(name);
    if (field == null) {
      return;
    }
    if (!_draft.containsKey(field.name) && field.answer == null) {
      final Object? start = _startingValue(field);
      if (start != null) {
        _draft[field.name] = start;
      }
    }
    if (field.type == 'text') {
      _controllerFor(field);
    }
  }

  Object? _startingValue(IntakeField field) {
    final num? start = switch (field.name) {
      'age' => 30,
      'height_cm' => 175,
      'weight_kg' => 75,
      'training_age_years' => 2,
      'weekly_frequency' => 4,
      _ => null,
    };
    if (start == null) {
      return null;
    }
    final double min = field.minimum ?? start.toDouble();
    final double max = field.maximum ?? start.toDouble();
    double value = start.toDouble().clamp(min, max);
    if (field.type == 'int') {
      value = value.roundToDouble();
    }
    return value;
  }

  TextEditingController _controllerFor(IntakeField field) {
    return _controllers.putIfAbsent(field.name, () {
      final Object? answer = field.answer;
      return TextEditingController(text: answer is String ? answer : '');
    });
  }

  // -- navigation -----------------------------------------------------------

  void _showField(String? name) {
    setState(() {
      _prepareField(name);
      _currentField = name;
      _stepError = null;
    });
  }

  void _editField(String name) {
    setState(() {
      _editingFromReview = true;
      _prepareField(name);
      _currentField = name;
      _stepError = null;
    });
  }

  void _advance(IntakeField field) {
    if (_editingFromReview) {
      setState(() {
        _currentField = null;
        _editingFromReview = false;
        _stepError = null;
      });
      return;
    }
    final int index =
        _fields.indexWhere((IntakeField f) => f.name == field.name);
    final String? next = (index < 0 || index >= _fields.length - 1)
        ? null
        : _fields[index + 1].name;
    _showField(next);
  }

  void _goBack() {
    if (_editingFromReview) {
      setState(() {
        _currentField = null;
        _editingFromReview = false;
        _stepError = null;
      });
      return;
    }
    final int index =
        _fields.indexWhere((IntakeField f) => f.name == _currentField);
    if (index <= 0) {
      return;
    }
    _showField(_fields[index - 1].name);
  }

  // -- actions --------------------------------------------------------------

  Future<void> _acceptDisclosure() async {
    setState(() {
      _disclosureSaving = true;
      _disclosureError = null;
    });
    try {
      final OnboardingIntake intake = await _api.acknowledgeIntakeDisclosure();
      if (!mounted) {
        return;
      }
      setState(() {
        _intake = intake;
        _disclosureSaving = false;
        _phase = _OnboardingPhase.answering;
        _editingFromReview = false;
        final String? first = _firstUnanswered(intake);
        _prepareField(first);
        _currentField = first;
      });
    } on ApiException catch (error) {
      if (!mounted) {
        return;
      }
      setState(() {
        _disclosureSaving = false;
        _disclosureError = mutationFailureMessage(
          error,
          connectionMessage: displayCopyOf(context).connectionFailure,
        );
      });
    }
  }

  Future<void> _continueStep(IntakeField field, {bool skip = false}) async {
    if (skip) {
      _advance(field);
      return;
    }
    final Object? value = _valueFor(field);
    if (!isFieldAnswerValid(field, value)) {
      setState(() => _stepError = _localValidationMessage(field, value));
      return;
    }
    setState(() {
      _saving = true;
      _stepError = null;
    });
    try {
      final OnboardingIntake intake =
          await _api.saveIntakeAnswer(field.name, value);
      if (!mounted) {
        return;
      }
      setState(() {
        _intake = intake;
        _saving = false;
      });
      _advance(field);
    } on ApiException catch (error) {
      if (!mounted) {
        return;
      }
      // A disclosure refusal means the acknowledgment was lost: return to it.
      if (error.statusCode == 403) {
        setState(() {
          _saving = false;
          _phase = _OnboardingPhase.disclosure;
        });
        return;
      }
      // Offline/network: keep the answer on screen so it can be retried.
      setState(() {
        _saving = false;
        _stepError = mutationFailureMessage(
          error,
          connectionMessage: displayCopyOf(context).connectionFailure,
        );
      });
    }
  }

  Future<void> _confirm() async {
    setState(() {
      _submitting = true;
      _confirmError = null;
    });
    try {
      await _api.confirmIntake();
      if (!mounted) {
        return;
      }
      _finishToHome();
    } on ApiException catch (error) {
      if (!mounted) {
        return;
      }
      if (error.statusCode == 403) {
        setState(() {
          _submitting = false;
          _phase = _OnboardingPhase.disclosure;
        });
        return;
      }
      if (error.statusCode == 409 && error.errorCode == 'confirm_in_progress') {
        setState(() {
          _submitting = false;
          _confirmError = MayosCopy(ref.read(displayLanguageProvider))
              .programBeingGenerated;
        });
        return;
      }
      setState(() {
        _submitting = false;
        _confirmError = mutationFailureMessage(
          error,
          connectionMessage: displayCopyOf(context).connectionFailure,
        );
      });
    }
  }

  Future<void> _redeemCoachInvite() async {
    final bool? redeemed = await showDialog<bool>(
      context: context,
      builder: (BuildContext context) => const _CoachInviteRedeemDialog(),
    );
    if (redeemed == true && mounted) {
      context.go(coachPath);
    }
  }

  Widget _coachInviteEntry() => Align(
        alignment: AlignmentDirectional.centerStart,
        child: TextButton(
          key: const Key('onboarding_coach_invite_entry'),
          onPressed: _redeemCoachInvite,
          child: Text(displayCopyOf(context).enterCoachCode),
        ),
      );

  void _finishToHome() {
    ref.read(authControllerProvider.notifier).markOnboarded();
    if (mounted) {
      context.go(homePath);
    }
  }

  String _localValidationMessage(IntakeField field, Object? value) {
    if (field.type == 'int' || field.type == 'float') {
      final String min = field.minimum?.toString() ?? '';
      final String max = field.maximum?.toString() ?? '';
      return MayosCopy(ref.read(displayLanguageProvider))
          .enterNumberBetween(min, max);
    }
    if (field.type == 'enum') {
      return MayosCopy(ref.read(displayLanguageProvider))
          .chooseOptionToContinue;
    }
    return MayosCopy(ref.read(displayLanguageProvider))
        .writeAtLeastTwoCharacters;
  }

  // -- build ----------------------------------------------------------------

  @override
  Widget build(BuildContext context) {
    if (_submitting) {
      return const _OnboardingStatusLayout(child: _BuildingProgramContent());
    }
    switch (_phase) {
      case _OnboardingPhase.loading:
        return const _OnboardingStatusLayout(
          child: CircularProgressIndicator(),
        );
      case _OnboardingPhase.error:
        return _OnboardingStatusLayout(
          child: _LoadErrorContent(
            message: _error ?? displayCopyOf(context).genericError,
            onRetry: _load,
          ),
        );
      case _OnboardingPhase.disclosure:
        return _buildDisclosure();
      case _OnboardingPhase.answering:
        return _buildFlow();
    }
  }

  Widget _buildDisclosure() {
    return OnboardingScaffold(
      bottomBar: OnboardingActions(
        primary: MayosButton(
          key: const Key('onboarding_disclosure_continue'),
          label: displayCopyOf(context).understood,
          loading: _disclosureSaving,
          onPressed: _disclosureSaving ? null : _acceptDisclosure,
        ),
      ),
      child: OnboardingStepBody(
        children: <Widget>[
          OnboardingQuestion(question: displayCopyOf(context).beforeWeBegin),
          const SizedBox(height: MayosSpacing.lg),
          const _HostedProcessingDisclosure(),
          if (_disclosureError != null) ...<Widget>[
            const SizedBox(height: MayosSpacing.md),
            OnboardingInlineError(message: _disclosureError!),
          ],
          const SizedBox(height: MayosSpacing.md),
          _coachInviteEntry(),
        ],
      ),
    );
  }

  /// The answering/review flow shares one frame so the progress bar and bottom
  /// action stay put while the central content slides between decisions.
  Widget _buildFlow() {
    final IntakeField? field = _fieldByName(_currentField);
    final IntakeProgress progress = _intake?.progress ??
        const IntakeProgress(
            answeredRequired: 0, requiredTotal: 0, answered: 0, totalFields: 0);

    return OnboardingScaffold(
      onBack: _flowOnBack(field),
      answered: progress.answered,
      total: progress.totalFields,
      bottomBar: field == null ? _reviewBottomBar() : _stepBottomBar(field),
      child: AnimatedSwitcher(
        duration: MayosMotion.base,
        switchInCurve: MayosMotion.standard,
        switchOutCurve: MayosMotion.standard,
        transitionBuilder: _slideFade,
        layoutBuilder: (Widget? current, List<Widget> previous) => Stack(
          fit: StackFit.expand,
          alignment: Alignment.topCenter,
          children: <Widget>[
            ...previous,
            if (current != null) current,
          ],
        ),
        child: KeyedSubtree(
          key: ValueKey<String>(field?.name ?? 'review'),
          child: field == null ? _reviewContent(progress) : _stepContent(field),
        ),
      ),
    );
  }

  VoidCallback? _flowOnBack(IntakeField? field) {
    if (field == null) {
      if (_fields.isEmpty) {
        return null;
      }
      return () {
        setState(() {
          _editingFromReview = false;
          _prepareField(_fields.last.name);
          _currentField = _fields.last.name;
          _stepError = null;
        });
      };
    }
    final bool isFirst = _fields.isNotEmpty && _fields.first.name == field.name;
    if (isFirst && !_editingFromReview) {
      // Consistent chrome: the first question returns to the disclosure.
      return () => setState(() {
            _phase = _OnboardingPhase.disclosure;
            _stepError = null;
          });
    }
    return _goBack;
  }

  /// A slight horizontal progression with a fade, at the shared motion speed.
  Widget _slideFade(Widget child, Animation<double> animation) {
    final Animation<Offset> offset = Tween<Offset>(
      begin: const Offset(0.06, 0),
      end: Offset.zero,
    ).animate(
      CurvedAnimation(parent: animation, curve: MayosMotion.standard),
    );
    return FadeTransition(
      opacity: animation,
      child: SlideTransition(position: offset, child: child),
    );
  }

  Widget _stepBottomBar(IntakeField field) {
    final Object? value = _valueFor(field);
    final bool canContinue = _canContinue(field, value);
    final bool isLast = _fields.isNotEmpty && _fields.last.name == field.name;
    return OnboardingActions(
      primary: MayosButton(
        key: const Key('onboarding_continue'),
        label: (isLast && !_editingFromReview)
            ? displayCopyOf(context).review
            : displayCopyOf(context).continueAction,
        loading: _saving,
        onPressed:
            (canContinue && !_saving) ? () => _continueStep(field) : null,
      ),
      secondary: field.isRequired
          ? null
          : MayosButton(
              key: const Key('onboarding_skip'),
              label: displayCopyOf(context).skipForNow,
              variant: MayosButtonVariant.tertiary,
              onPressed:
                  _saving ? null : () => _continueStep(field, skip: true),
            ),
    );
  }

  Widget _stepContent(IntakeField field) {
    final Object? value = _valueFor(field);
    return OnboardingStepBody(
      children: <Widget>[
        OnboardingQuestion(
          question: OnboardingCopy(displayCopyOf(context).languageCode)
              .question(field.name, serverLabel: field.label),
          explanation: explanationFor(field),
          note: field.prefilled
              ? displayCopyOf(context).savedFromEarlierSetup
              : null,
        ),
        const SizedBox(height: MayosSpacing.xl),
        _buildInteraction(field, value),
        if (_stepError != null) ...<Widget>[
          const SizedBox(height: MayosSpacing.md),
          OnboardingInlineError(message: _stepError!),
        ],
      ],
    );
  }

  bool _canContinue(IntakeField field, Object? value) {
    if (field.isRequired) {
      return isFieldAnswerValid(field, value);
    }
    return value != null && isFieldAnswerValid(field, value);
  }

  Widget _buildInteraction(IntakeField field, Object? value) {
    switch (field.name) {
      case 'proportions':
        return ProportionSelector(
          field: field,
          selected: value is String ? value : null,
          onSelected: (String selected) =>
              setState(() => _draft[field.name] = selected),
        );
      case 'weekly_frequency':
        return FrequencySelector(
          fieldName: field.name,
          minimum: (field.minimum ?? 1).round(),
          maximum: (field.maximum ?? 5).round(),
          selected: value is num ? value : null,
          onSelected: (int selected) =>
              setState(() => _draft[field.name] = selected),
        );
    }
    if (field.type == 'enum') {
      return OnboardingChoiceList(
        fieldName: field.name,
        options: _enumOptions(field),
        selected: value is String ? value : null,
        onSelected: (String selected) =>
            setState(() => _draft[field.name] = selected),
      );
    }
    if (field.type == 'int' || field.type == 'float') {
      return NumericFieldEditor(
        fieldName: field.name,
        fieldLabel: field.label,
        minimum: field.minimum ?? 0,
        maximum: field.maximum ?? 100,
        integer: field.type == 'int',
        step: _stepFor(field),
        unit: OnboardingCopy(displayCopyOf(context).languageCode)
            .unitFor(field.name),
        value: value is num ? value : null,
        onChanged: (num? next) => setState(() {
          if (next == null) {
            _draft[field.name] = null;
          } else {
            _draft[field.name] = next;
          }
        }),
      );
    }
    return TextFieldEditor(
      fieldName: field.name,
      controller: _controllerFor(field),
      hint: field.hint ?? displayCopyOf(context).typeYourAnswer,
      examples: field.examples,
      quickOptions: field.name == 'injuries_or_limitations'
          ? <String>[displayCopyOf(context).none]
          : const <String>[],
      onChanged: (String text) => setState(() => _draft[field.name] = text),
    );
  }

  double _stepFor(IntakeField field) => switch (field.name) {
        'weight_kg' => 0.5,
        _ => 1,
      };

  List<OnboardingChoiceOption> _enumOptions(IntakeField field) {
    return <OnboardingChoiceOption>[
      for (final String value in field.allowedValues)
        OnboardingChoiceOption(
          value: value,
          label: onboardingOptionLabel(
            field,
            value,
            copy: OnboardingCopy(displayCopyOf(context).languageCode),
          ),
          subtitle: field.optionDescriptions[value],
          icon: _iconFor(field.name, value),
        ),
    ];
  }

  IconData? _iconFor(String fieldName, String value) {
    if (fieldName != 'gender') {
      return null;
    }
    return value == 'female' ? Icons.female : Icons.male;
  }

  Widget _reviewBottomBar() {
    final IntakeProgress progress = _intake?.progress ??
        const IntakeProgress(
            answeredRequired: 0, requiredTotal: 0, answered: 0, totalFields: 0);
    return OnboardingActions(
      primary: MayosButton(
        key: const Key('onboarding_confirm'),
        label: displayCopyOf(context).createMyProgram,
        loading: _submitting,
        onPressed: progress.isComplete ? _confirm : null,
      ),
    );
  }

  Widget _reviewContent(IntakeProgress progress) {
    final bool ready = progress.isComplete;
    return OnboardingStepBody(
      children: <Widget>[
        OnboardingQuestion(
          question: displayCopyOf(context).reviewSetup,
          explanation: displayCopyOf(context).reviewSetupLead,
        ),
        const SizedBox(height: MayosSpacing.xl),
        ReviewSection(
          title: displayCopyOf(context).aboutYou,
          fields: _reviewFields(const <String>[
            'gender',
            'proportions',
            'age',
            'height_cm',
            'weight_kg',
            'training_age_years',
          ]),
          onEdit: (IntakeField field) => _editField(field.name),
        ),
        ReviewSection(
          title: displayCopyOf(context).training,
          fields: _reviewFields(const <String>[
            'current_goal',
            'long_term_goal',
            'weekly_frequency',
            'equipment_access',
            'rep_preference',
          ]),
          onEdit: (IntakeField field) => _editField(field.name),
        ),
        ReviewSection(
          title: displayCopyOf(context).healthAndRecovery,
          fields: _reviewFields(const <String>[
            'injuries_or_limitations',
            'stress_and_sleep',
          ]),
          onEdit: (IntakeField field) => _editField(field.name),
        ),
        if (!ready) ...<Widget>[
          const SizedBox(height: MayosSpacing.xs),
          OnboardingInlineError(
              message: displayCopyOf(context).requiredAnswersMissing),
        ],
        if (_confirmError != null) ...<Widget>[
          const SizedBox(height: MayosSpacing.xs),
          OnboardingInlineError(message: _confirmError!),
        ],
      ],
    );
  }

  /// The review fields for a section, in the API's field order.
  List<IntakeField> _reviewFields(List<String> names) {
    final Set<String> wanted = names.toSet();
    return _fields
        .where((IntakeField field) => wanted.contains(field.name))
        .toList(growable: false);
  }
}

/// The hosted-processing disclosure (ADR 016/036), shown before any answer is
/// sent. Nothing is saved until the player acknowledges it.
class _HostedProcessingDisclosure extends StatelessWidget {
  const _HostedProcessingDisclosure();

  @override
  Widget build(BuildContext context) {
    final MayosThemeExtension c = MayosTheme.of(context);
    return MayosCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          Row(
            children: <Widget>[
              Container(
                width: 40,
                height: 40,
                decoration: BoxDecoration(
                  color: c.accentSubtle,
                  borderRadius: BorderRadius.circular(12),
                ),
                child: Icon(Icons.shield_outlined, size: 22, color: c.accent),
              ),
              const SizedBox(width: MayosSpacing.sm),
              Expanded(
                child: Text(
                  displayCopyOf(context).hostedAIProcessing,
                  style: MayosTypography.sectionHeading
                      .copyWith(color: c.textPrimary),
                ),
              ),
            ],
          ),
          const SizedBox(height: MayosSpacing.md),
          Text(
            displayCopyOf(context).onboardingHostedDisclosure,
            style:
                MayosTypography.bodySecondary.copyWith(color: c.textSecondary),
          ),
          const SizedBox(height: MayosSpacing.md),
          Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: <Widget>[
              Icon(Icons.lock_outline, size: 16, color: c.textMuted),
              const SizedBox(width: MayosSpacing.xs),
              Expanded(
                child: Text(
                  displayCopyOf(context).onboardingPrivacyNote,
                  style: MayosTypography.caption.copyWith(color: c.textMuted),
                ),
              ),
            ],
          ),
        ],
      ),
    );
  }
}

class _OnboardingStatusLayout extends StatelessWidget {
  const _OnboardingStatusLayout({required this.child});

  final Widget child;

  @override
  Widget build(BuildContext context) => Scaffold(
        body: SafeArea(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: <Widget>[
              const OfflineBannerSlot(),
              Expanded(
                child: MayosPlayerColumn(
                  child: Center(
                    child: Padding(
                      padding: const EdgeInsets.all(MayosSpacing.xl),
                      child: child,
                    ),
                  ),
                ),
              ),
            ],
          ),
        ),
      );
}

class _LoadErrorContent extends StatelessWidget {
  const _LoadErrorContent({required this.message, required this.onRetry});

  final String message;
  final VoidCallback onRetry;

  @override
  Widget build(BuildContext context) {
    final MayosThemeExtension c = MayosTheme.of(context);
    return Column(
      mainAxisSize: MainAxisSize.min,
      children: <Widget>[
        Icon(Icons.cloud_off, size: 40, color: c.textMuted),
        const SizedBox(height: MayosSpacing.md),
        Text(
          displayCopyOf(context).setupLoadFailed,
          textAlign: TextAlign.center,
          style: MayosTypography.pageHeading
              .copyWith(color: c.textPrimary, fontSize: 24),
        ),
        const SizedBox(height: MayosSpacing.xs),
        Text(
          message,
          textAlign: TextAlign.center,
          style: MayosTypography.bodySecondary.copyWith(color: c.textSecondary),
        ),
        const SizedBox(height: MayosSpacing.xl),
        MayosButton(
          label: displayCopyOf(context).retry,
          expand: false,
          onPressed: onRetry,
        ),
      ],
    );
  }
}

class _BuildingProgramContent extends StatelessWidget {
  const _BuildingProgramContent();

  @override
  Widget build(BuildContext context) {
    final MayosThemeExtension c = MayosTheme.of(context);
    return Column(
      mainAxisSize: MainAxisSize.min,
      children: <Widget>[
        const MayosBrandMark(size: 52),
        const SizedBox(height: MayosSpacing.xl),
        Text(
          displayCopyOf(context).buildingYourProgram,
          textAlign: TextAlign.center,
          style: MayosTypography.pageHeading.copyWith(color: c.textPrimary),
        ),
        const SizedBox(height: MayosSpacing.sm),
        Text(
          displayCopyOf(context).answersSavedBuilding,
          textAlign: TextAlign.center,
          style: MayosTypography.bodySecondary.copyWith(
            color: c.textSecondary,
          ),
        ),
        const SizedBox(height: MayosSpacing.xl),
        const SizedBox(
          width: 180,
          child: MayosProgressIndicator(value: null),
        ),
      ],
    );
  }
}

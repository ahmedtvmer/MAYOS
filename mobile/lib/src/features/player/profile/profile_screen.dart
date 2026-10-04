import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api_client.dart';
import '../../../core/app_failure.dart';
import '../../../core/connectivity_message.dart';
import '../../../core/display_language/controller.dart';
import '../../../core/display_language/copy_context.dart';
import '../../../core/display_language/profile_copy.dart';
import '../../../core/device_timezone.dart';
import '../../../core/models.dart';
import '../../../core/theme/mayos_spacing.dart';
import '../../../core/theme/mayos_theme.dart';
import '../../../core/theme/mayos_typography.dart';
import '../../../core/ui/mayos_button.dart';
import '../../../core/ui/mayos_section_header.dart';
import '../../../core/ui/mayos_text_field.dart';
import '../../../core/ui/first_strong_direction.dart';
import '../../../providers.dart';
import '../onboarding/onboarding_widgets.dart'
    show isFieldAnswerValid, optionLabel;

/// Mirrors the server's `MAX_PAUSE_DAYS` in `service/schedule.py`; the client
/// check is only a courtesy, the service stays authoritative.
const int maxPauseDays = 14;
const String _profileContractError =
    'The service needs an update before this profile can be edited. Please try again later.';
const AppFailureMessage _profileContractFailure = AppFailureMessage(
  AppFailureId.profileUpdateRequired,
  _profileContractError,
);

const Map<String, String> _profileFieldTypes = <String, String>{
  'current_goal': 'text',
  'injuries_or_limitations': 'text',
  'weight_kg': 'float',
  'weekly_frequency': 'int',
  'equipment_access': 'enum',
  'rep_preference': 'enum',
};

/// Player Training profile editor. The intake contract supplies the facts the
/// service considers for a rebuild and the service remains authoritative. When
/// an assigned coach owns the active program, it stays unchanged and the app
/// shows that a coach request is needed.
///
/// Below the profile card, the player separately owns an expected training
/// schedule (weekdays + timezone) and prospective pauses. Setting either never
/// touches the program (#30).
class ProfileScreen extends ConsumerStatefulWidget {
  const ProfileScreen({super.key});

  @override
  ConsumerState<ProfileScreen> createState() => _ProfileScreenState();
}

class _ProfileScreenState extends ConsumerState<ProfileScreen> {
  int _weeklyFrequency = 4;
  String _repPreference = 'balanced';
  String _equipmentAccess = equipmentAccessCommercialGym;
  final TextEditingController _currentGoalController = TextEditingController();
  final TextEditingController _injuriesOrLimitationsController =
      TextEditingController();
  final TextEditingController _weightController =
      TextEditingController(text: '75');
  PlayerProfile? _savedProfile;
  OnboardingIntake? _intake;

  bool _loading = true;
  bool _saving = false;
  FailureMessage? _loadError;
  String? _notice;
  FailureMessage? _noticeFailure;
  bool _noticeIsError = false;
  Account? _account;

  final TextEditingController _timezone = TextEditingController();
  final Set<int> _weekdays = <int>{};
  TrainingSchedule _schedule = const TrainingSchedule();
  List<ScheduledPause> _pauses = const <ScheduledPause>[];
  bool _savingSchedule = false;
  String? _scheduleNotice;
  FailureMessage? _scheduleFailure;
  bool _scheduleNoticeIsError = false;

  DateTime _pauseStart = _today();
  DateTime _pauseEnd = _today();
  bool _schedulingPause = false;
  String? _pauseNotice;
  FailureMessage? _pauseFailure;
  bool _pauseNoticeIsError = false;

  ProfileCopy get _copy => ProfileCopy(ref.read(displayLanguageProvider));

  FailureMessage _mutationFailure(ApiException error) =>
      mutationFailureMessage(error);

  static DateTime _today() {
    final DateTime now = DateTime.now();
    return DateTime(now.year, now.month, now.day);
  }

  static String _formatDate(DateTime date) =>
      '${date.year.toString().padLeft(4, '0')}-'
      '${date.month.toString().padLeft(2, '0')}-'
      '${date.day.toString().padLeft(2, '0')}';

  @override
  void initState() {
    super.initState();
    _injuriesOrLimitationsController.text = _copy.none;
    _load();
  }

  @override
  void dispose() {
    _timezone.dispose();
    _currentGoalController.dispose();
    _injuriesOrLimitationsController.dispose();
    _weightController.dispose();
    super.dispose();
  }

  void _validateProfileIntake(OnboardingIntake intake, int savedFrequency) {
    for (final MapEntry<String, String> entry in _profileFieldTypes.entries) {
      final IntakeField? field = intake.field(entry.key);
      if (field == null ||
          field.type != entry.value ||
          intake.fields.where((IntakeField f) => f.name == entry.key).length !=
              1 ||
          (field.type == 'enum' && !_hasValidChoices(field))) {
        throw const ApiException(
          _profileContractError,
          failureMessage: _profileContractFailure,
        );
      }
    }
    final IntakeField frequency = intake.field('weekly_frequency')!;
    if (!_hasValidFrequencyRange(frequency, savedFrequency)) {
      throw const ApiException(
        _profileContractError,
        failureMessage: _profileContractFailure,
      );
    }
  }

  bool _hasValidChoices(IntakeField field) =>
      field.allowedValues.isNotEmpty &&
      field.allowedValues.every((String value) => value.trim().isNotEmpty) &&
      field.allowedValues.toSet().length == field.allowedValues.length;

  bool _hasValidFrequencyRange(IntakeField field, int savedFrequency) {
    final double? minimum = field.minimum;
    final double? maximum = field.maximum;
    return minimum != null &&
        maximum != null &&
        minimum.isFinite &&
        maximum.isFinite &&
        minimum == minimum.roundToDouble() &&
        maximum == maximum.roundToDouble() &&
        minimum >= 1 &&
        minimum <= maximum &&
        savedFrequency >= minimum &&
        savedFrequency <= maximum;
  }

  Future<void> _load() async {
    setState(() {
      _loading = true;
      _loadError = null;
    });
    try {
      final ApiClient api = ref.read(apiClientProvider);
      final List<Object> results = await Future.wait<Object>(<Future<Object>>[
        api.profile(),
        api.trainingSchedule(),
        api.trainingPauses(),
        api.currentAccount(),
        api.onboardingIntake(invalidDataMessage: _profileContractError),
      ]);
      if (!mounted) return;
      final PlayerProfile profile = results[0] as PlayerProfile;
      final TrainingSchedule schedule = results[1] as TrainingSchedule;
      final List<ScheduledPause> pauses = results[2] as List<ScheduledPause>;
      final Account account = results[3] as Account;
      final OnboardingIntake intake = results[4] as OnboardingIntake;
      _validateProfileIntake(intake, profile.weeklyFrequency);
      final List<String> equipmentOptions =
          intake.field('equipment_access')!.allowedValues;
      final List<String> repOptions =
          intake.field('rep_preference')!.allowedValues;
      final String timezone = schedule.current != null
          ? schedule.current!.timezone
          : await ref.read(deviceTimezoneProvider);
      if (!mounted) return;
      setState(() {
        _weeklyFrequency = profile.weeklyFrequency;
        _savedProfile = profile;
        _intake = intake;
        _equipmentAccess = equipmentOptions.contains(profile.equipmentAccess)
            ? profile.equipmentAccess
            : equipmentOptions.first;
        _currentGoalController.text = profile.currentGoal;
        _injuriesOrLimitationsController.text = profile.injuriesOrLimitations;
        _weightController.text = profile.weightKg.toString();
        _repPreference = repOptions.contains(profile.repPreference)
            ? profile.repPreference
            : repOptions.first;
        _schedule = schedule;
        _pauses = pauses;
        _account = account;
        _weekdays
          ..clear()
          ..addAll(_schedule.current?.weekdays ?? const <int>[]);
        _timezone.text = timezone;
        _loading = false;
      });
    } on ApiException catch (error) {
      if (!mounted) return;
      setState(() {
        _loading = false;
        _loadError = apiFailureMessage(error);
      });
    }
  }

  Future<void> _save() async {
    final PlayerProfile? saved = _savedProfile;
    final OnboardingIntake? intake = _intake;
    if (saved == null || intake == null) return;
    final double? parsedWeight = double.tryParse(_weightController.text.trim());
    final bool weightChanged = parsedWeight == null
        ? _weightController.text.trim() != saved.weightKg.toString()
        : parsedWeight != saved.weightKg;
    final String currentGoal = _currentGoalController.text.trim();
    final String injuries = _injuriesOrLimitationsController.text.trim();
    final Map<String, Object?> changedValues = <String, Object?>{
      if (_weeklyFrequency != saved.weeklyFrequency)
        'weekly_frequency': _weeklyFrequency,
      if (_repPreference != saved.repPreference)
        'rep_preference': _repPreference,
      if (_equipmentAccess != saved.equipmentAccess)
        'equipment_access': _equipmentAccess,
      if (currentGoal != saved.currentGoal) 'current_goal': currentGoal,
      if (injuries != saved.injuriesOrLimitations)
        'injuries_or_limitations': injuries,
      if (weightChanged) 'weight_kg': parsedWeight ?? _weightController.text,
    };
    for (final MapEntry<String, Object?> entry in changedValues.entries) {
      final String contractName = entry.key;
      final IntakeField? field = intake.field(contractName);
      if (field == null || !isFieldAnswerValid(field, entry.value)) {
        setState(() {
          _notice = _validationMessage(field);
          _noticeFailure = null;
          _noticeIsError = true;
        });
        return;
      }
    }
    final bool rebuildRequested = intake.profileRebuildFields.any(
      (String field) => changedValues.containsKey(field),
    );
    if (rebuildRequested && saved.playerControlsProgram) {
      final bool? confirmed = await showDialog<bool>(
        context: context,
        builder: (BuildContext context) => AlertDialog(
          title: Text(_copy.confirmProgramRebuild),
          content: Text(_copy.rebuildsProgram),
          actions: <Widget>[
            TextButton(
              onPressed: () => Navigator.of(context).pop(false),
              child: Text(_copy.cancel),
            ),
            FilledButton(
              key: const Key('profile_rebuild_confirm_button'),
              onPressed: () => Navigator.of(context).pop(true),
              child: Text(_copy.continueAction),
            ),
          ],
        ),
      );
      if (confirmed != true || !mounted) return;
    }
    setState(() {
      _saving = true;
      _notice = null;
      _noticeFailure = null;
      _noticeIsError = false;
    });
    try {
      final ProfileUpdateResult result =
          await ref.read(apiClientProvider).updateProfile(
                weeklyFrequency: changedValues['weekly_frequency'] as int?,
                repPreference: changedValues['rep_preference'] as String?,
                currentGoal: changedValues['current_goal'] as String?,
                injuriesOrLimitations:
                    changedValues['injuries_or_limitations'] as String?,
                weightKg: changedValues.containsKey('weight_kg')
                    ? parsedWeight
                    : null,
                equipmentAccess: changedValues['equipment_access'] as String?,
              );
      if (!mounted) return;
      if (result.programRebuilt) unawaited(_refreshProgramCache());
      setState(() {
        _saving = false;
        _savedProfile = result.profile ??
            PlayerProfile(
              weeklyFrequency: _weeklyFrequency,
              repPreference: _repPreference,
              equipmentAccess: _equipmentAccess,
              currentGoal: currentGoal,
              injuriesOrLimitations: injuries,
              weightKg: parsedWeight ?? saved.weightKg,
              playerControlsProgram: saved.playerControlsProgram,
            );
        _notice = result.programBlocked
            ? result.programMessage
            : result.programRebuilt
                ? _copy.programRebuilt
                : _copy.profileSaved;
      });
    } on ApiException catch (error) {
      if (!mounted) return;
      setState(() {
        _saving = false;
        _noticeFailure = _mutationFailure(error);
        _noticeIsError = true;
      });
    }
  }

  String _validationMessage(IntakeField? field) {
    if (field == null) return _copy.checkProfileAndRetry;
    if (field.name == 'weight_kg' &&
        field.minimum != null &&
        field.maximum != null) {
      return _copy.weightRange(
        field.minimum!.toStringAsFixed(0),
        field.maximum!.toStringAsFixed(0),
      );
    }
    if (field.type == 'enum') {
      return _copy.chooseAllowed(
        _copy.profileFieldName(field.name, optionLabel('', field.name)),
      );
    }
    return field.hint ??
        _copy.checkFieldAndRetry(
          _copy.profileFieldName(
              field.name, optionLabel('', field.name).toLowerCase()),
        );
  }

  Future<void> _refreshProgramCache() async {
    final String? accountId = _account?.accountId;
    if (accountId == null) return;
    final ApiClient api = ref.read(apiClientProvider);
    final cache = ref.read(workoutCacheStoreProvider);
    try {
      final TrainingProgram? program = await api.activeProgram();
      if (program != null) {
        await cache.writeProgram(accountId, program);
      }
    } on Object {
      // The online program read remains authoritative if the cache write fails.
    }
  }

  Future<void> _saveSchedule() async {
    final String timezone = _timezone.text.trim();
    if (timezone.isEmpty || (!timezone.contains('/') && timezone != 'UTC')) {
      setState(() {
        _scheduleNotice = _copy.timezoneExample;
        _scheduleFailure = null;
        _scheduleNoticeIsError = true;
      });
      return;
    }
    setState(() {
      _savingSchedule = true;
      _scheduleNotice = null;
      _scheduleFailure = null;
      _scheduleNoticeIsError = false;
    });
    try {
      final List<int> weekdays = _weekdays.toList()..sort();
      await ref.read(apiClientProvider).setTrainingSchedule(
            weekdays: weekdays,
            timezone: timezone,
          );
      final TrainingSchedule refreshed =
          await ref.read(apiClientProvider).trainingSchedule();
      if (!mounted) return;
      setState(() {
        _savingSchedule = false;
        _scheduleNotice = _copy.scheduleSaved;
        _schedule = refreshed;
      });
    } on ApiException catch (error) {
      if (!mounted) return;
      setState(() {
        _savingSchedule = false;
        _scheduleFailure = _mutationFailure(error);
        _scheduleNoticeIsError = true;
      });
    }
  }

  Future<void> _pickPauseDate({required bool start}) async {
    final DateTime today = _today();
    final DateTime? picked = await showDatePicker(
      context: context,
      initialDate: start ? _pauseStart : _pauseEnd,
      firstDate: DateTime(today.year - 1),
      lastDate: DateTime(today.year + 1, today.month, today.day),
    );
    if (picked == null || !mounted) return;
    setState(() {
      if (start) {
        _pauseStart = picked;
        if (_pauseEnd.isBefore(_pauseStart)) {
          _pauseEnd = _pauseStart;
        }
      } else {
        _pauseEnd = picked;
      }
    });
  }

  Future<void> _schedulePause() async {
    final DateTime today = _today();
    final DateTime start =
        DateTime(_pauseStart.year, _pauseStart.month, _pauseStart.day);
    final DateTime end =
        DateTime(_pauseEnd.year, _pauseEnd.month, _pauseEnd.day);
    String? validation;
    if (start.isBefore(today)) {
      validation = _copy.pauseMustStartToday;
    } else if (end.isBefore(start)) {
      validation = _copy.pauseMustEndAfterStart;
    } else if (end.difference(start).inDays + 1 > maxPauseDays) {
      validation = _copy.pauseMaximumDays(maxPauseDays);
    }
    if (validation != null) {
      setState(() {
        _pauseNotice = validation;
        _pauseFailure = null;
        _pauseNoticeIsError = true;
      });
      return;
    }
    setState(() {
      _schedulingPause = true;
      _pauseNotice = null;
      _pauseFailure = null;
      _pauseNoticeIsError = false;
    });
    try {
      final TrainingPauseCreateResult result =
          await ref.read(apiClientProvider).createTrainingPause(
                startsOn: _formatDate(start),
                endsOn: _formatDate(end),
              );
      if (!mounted) return;
      setState(() {
        _schedulingPause = false;
        _pauseNotice = result.noticeSent
            ? _copy.pauseScheduledCoachNotified
            : _copy.pauseScheduled;
        _pauses = <ScheduledPause>[result.pause, ..._pauses];
      });
    } on ApiException catch (error) {
      if (!mounted) return;
      setState(() {
        _schedulingPause = false;
        _pauseFailure = _mutationFailure(error);
        _pauseNoticeIsError = true;
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    final ProfileCopy copy = ProfileCopy(ref.watch(displayLanguageProvider));
    if (_loading) {
      return const Center(child: CircularProgressIndicator());
    }
    final MayosThemeExtension c = MayosTheme.of(context);
    if (_loadError != null) {
      return Center(
        child: Padding(
          padding: const EdgeInsets.all(MayosSpacing.xl),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: <Widget>[
              Text(displayCopyOf(context).failureMessage(_loadError!),
                  textAlign: TextAlign.center),
              const SizedBox(height: MayosSpacing.md),
              MayosButton(
                label: copy.retry,
                variant: MayosButtonVariant.secondary,
                expand: false,
                onPressed: _load,
              ),
            ],
          ),
        ),
      );
    }
    return ListView(
      padding: MayosSpacing.screen,
      children: <Widget>[
        MayosSectionHeader(
          title: copy.trainingProfile,
          subtitle: copy.profileLead,
        ),
        const SizedBox(height: MayosSpacing.md),
        MayosTextField(
          fieldKey: const Key('current_goal_field'),
          controller: _currentGoalController,
          label: copy.currentGoal,
          enabled: !_saving,
          textCapitalization: TextCapitalization.sentences,
        ),
        const SizedBox(height: MayosSpacing.sm),
        MayosTextField(
          fieldKey: const Key('injuries_or_limitations_field'),
          controller: _injuriesOrLimitationsController,
          label: copy.injuriesLimitations,
          enabled: !_saving,
          textCapitalization: TextCapitalization.sentences,
        ),
        const SizedBox(height: MayosSpacing.sm),
        Directionality(
          textDirection: TextDirection.ltr,
          child: MayosTextField(
            fieldKey: const Key('weight_kg_field'),
            controller: _weightController,
            label: copy.weightKg,
            enabled: !_saving,
            keyboardType: const TextInputType.numberWithOptions(decimal: true),
          ),
        ),
        const SizedBox(height: MayosSpacing.sm),
        DropdownButtonFormField<int>(
          initialValue: _weeklyFrequency,
          isExpanded: true,
          decoration: InputDecoration(
            labelText: copy.trainingDaysPerWeek,
            border: OutlineInputBorder(),
          ),
          items: <DropdownMenuItem<int>>[
            for (int days =
                    _intake!.field('weekly_frequency')!.minimum!.toInt();
                days <= _intake!.field('weekly_frequency')!.maximum!.toInt();
                days++)
              DropdownMenuItem<int>(
                value: days,
                child: Text('$days', textDirection: TextDirection.ltr),
              ),
          ],
          onChanged: _saving
              ? null
              : (int? value) =>
                  setState(() => _weeklyFrequency = value ?? _weeklyFrequency),
        ),
        const SizedBox(height: MayosSpacing.sm),
        DropdownButtonFormField<String>(
          initialValue: _repPreference,
          isExpanded: true,
          decoration: InputDecoration(
            labelText: copy.repPreference,
            border: OutlineInputBorder(),
          ),
          items: <DropdownMenuItem<String>>[
            for (final String preference
                in _intake!.field('rep_preference')!.allowedValues)
              DropdownMenuItem<String>(
                  value: preference,
                  child: Text(copy.repPreferenceValue(preference),
                      overflow: TextOverflow.ellipsis)),
          ],
          onChanged: _saving
              ? null
              : (String? value) =>
                  setState(() => _repPreference = value ?? _repPreference),
        ),
        const SizedBox(height: MayosSpacing.sm),
        DropdownButtonFormField<String>(
          key: const Key('equipment_access_dropdown'),
          initialValue: _equipmentAccess,
          isExpanded: true,
          decoration: InputDecoration(
            labelText: copy.equipmentAccess,
            border: OutlineInputBorder(),
          ),
          items: <DropdownMenuItem<String>>[
            for (final String access
                in _intake!.field('equipment_access')!.allowedValues)
              DropdownMenuItem<String>(
                  value: access, child: Text(copy.equipmentValue(access))),
          ],
          onChanged: _saving
              ? null
              : (String? selectedAccess) => setState(() {
                    _equipmentAccess = selectedAccess ?? _equipmentAccess;
                  }),
        ),
        if (_notice != null || _noticeFailure != null) ...<Widget>[
          const SizedBox(height: MayosSpacing.sm),
          FirstStrongDirection(
            text: _noticeFailure == null
                ? _notice!
                : displayCopyOf(context).failureMessage(_noticeFailure!),
            child: Text(
              _noticeFailure == null
                  ? _notice!
                  : displayCopyOf(context).failureMessage(_noticeFailure!),
              style: _noticeIsError
                  ? MayosTypography.bodySecondary.copyWith(color: c.danger)
                  : MayosTypography.body,
            ),
          ),
        ],
        const SizedBox(height: MayosSpacing.lg),
        MayosButton(
          label: copy.saveProfile,
          loading: _saving,
          onPressed: _saving ? null : _save,
        ),
        const SizedBox(height: MayosSpacing.xxl),
        const Divider(),
        const SizedBox(height: MayosSpacing.sm),
        MayosSectionHeader(
          title: copy.trainingSchedule,
          subtitle: copy.scheduleLead,
        ),
        const SizedBox(height: MayosSpacing.md),
        Wrap(
          spacing: MayosSpacing.xs,
          runSpacing: MayosSpacing.xs,
          children: <Widget>[
            for (int day = 1; day <= 7; day++)
              FilterChip(
                key: Key('weekday_chip_$day'),
                label: Text(copy.weekday(day)),
                selected: _weekdays.contains(day),
                onSelected: _savingSchedule
                    ? null
                    : (bool selected) => setState(() {
                          if (selected) {
                            _weekdays.add(day);
                          } else {
                            _weekdays.remove(day);
                          }
                        }),
              ),
          ],
        ),
        const SizedBox(height: MayosSpacing.sm),
        Directionality(
          textDirection: TextDirection.ltr,
          child: MayosTextField(
            fieldKey: const Key('timezone_field'),
            controller: _timezone,
            enabled: !_savingSchedule,
            label: copy.timezone,
          ),
        ),
        if (_scheduleNotice != null || _scheduleFailure != null) ...<Widget>[
          const SizedBox(height: MayosSpacing.sm),
          FirstStrongDirection(
            text: _scheduleFailure == null
                ? _scheduleNotice!
                : displayCopyOf(context).failureMessage(_scheduleFailure!),
            child: Text(
              _scheduleFailure == null
                  ? _scheduleNotice!
                  : displayCopyOf(context).failureMessage(_scheduleFailure!),
              style: _scheduleNoticeIsError
                  ? MayosTypography.bodySecondary.copyWith(color: c.danger)
                  : MayosTypography.body,
            ),
          ),
        ],
        const SizedBox(height: MayosSpacing.sm),
        MayosButton(
          key: const Key('save_schedule_button'),
          label: copy.saveSchedule,
          loading: _savingSchedule,
          onPressed: _savingSchedule ? null : _saveSchedule,
        ),
        const SizedBox(height: MayosSpacing.xl),
        MayosSectionHeader(title: copy.trainingPause),
        Row(
          children: <Widget>[
            Expanded(
              child: MayosButton(
                key: const Key('pause_start_button'),
                label: copy.pauseStart(_formatDate(_pauseStart)),
                variant: MayosButtonVariant.secondary,
                onPressed:
                    _schedulingPause ? null : () => _pickPauseDate(start: true),
              ),
            ),
            const SizedBox(width: MayosSpacing.xs),
            Expanded(
              child: MayosButton(
                key: const Key('pause_end_button'),
                label: copy.pauseEnd(_formatDate(_pauseEnd)),
                variant: MayosButtonVariant.secondary,
                onPressed: _schedulingPause
                    ? null
                    : () => _pickPauseDate(start: false),
              ),
            ),
          ],
        ),
        if (_pauseNotice != null || _pauseFailure != null) ...<Widget>[
          const SizedBox(height: MayosSpacing.sm),
          FirstStrongDirection(
            text: _pauseFailure == null
                ? _pauseNotice!
                : displayCopyOf(context).failureMessage(_pauseFailure!),
            child: Text(
              _pauseFailure == null
                  ? _pauseNotice!
                  : displayCopyOf(context).failureMessage(_pauseFailure!),
              style: _pauseNoticeIsError
                  ? MayosTypography.bodySecondary.copyWith(color: c.danger)
                  : MayosTypography.body,
            ),
          ),
        ],
        const SizedBox(height: MayosSpacing.sm),
        MayosButton(
          key: const Key('schedule_pause_button'),
          label: copy.schedulePause,
          loading: _schedulingPause,
          onPressed: _schedulingPause ? null : _schedulePause,
        ),
        const SizedBox(height: MayosSpacing.sm),
        if (_pauses.isEmpty)
          Text(copy.noScheduledPauses,
              style: MayosTypography.bodySecondary
                  .copyWith(color: c.textSecondary))
        else
          for (final ScheduledPause pause in _pauses)
            Text(
              copy.pauseRange(pause.startsOn, pause.endsOn),
              style: MayosTypography.body.copyWith(color: c.textPrimary),
            ),
        const SizedBox(height: MayosSpacing.xxl),
      ],
    );
  }
}

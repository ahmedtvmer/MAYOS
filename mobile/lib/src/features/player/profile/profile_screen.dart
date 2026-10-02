import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api_client.dart';
import '../../../core/connectivity_message.dart';
import '../../../core/display_language/catalog.dart';
import '../../../core/display_language/controller.dart';
import '../../../core/device_timezone.dart';
import '../../../core/models.dart';
import '../../../core/theme/mayos_spacing.dart';
import '../../../core/theme/mayos_theme.dart';
import '../../../core/theme/mayos_typography.dart';
import '../../../core/ui/mayos_button.dart';
import '../../../core/ui/mayos_card.dart';
import '../../../core/ui/mayos_icon_chip.dart';
import '../../../core/ui/mayos_section_header.dart';
import '../../../core/ui/mayos_text_field.dart';
import '../../../providers.dart';
import '../auth/auth_controller.dart';
import '../auth/auth_widgets.dart'
    show
        AuthPasswordField,
        NewPasswordValidation,
        newPasswordValidationMessage,
        validateNewPassword;
import '../auth/google_auth_gateway.dart';
import '../auth/google_sign_in_button.dart';
import '../onboarding/onboarding_widgets.dart'
    show isFieldAnswerValid, optionLabel;

/// Mirrors the server's `MAX_PAUSE_DAYS` in `service/schedule.py`; the client
/// check is only a courtesy, the service stays authoritative.
const int maxPauseDays = 14;
const String _profileContractError =
    'The service needs an update before this profile can be edited. Please try again later.';

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
      TextEditingController(text: 'None');
  final TextEditingController _weightController =
      TextEditingController(text: '75');
  PlayerProfile? _savedProfile;
  OnboardingIntake? _intake;

  bool _loading = true;
  bool _saving = false;
  String? _loadError;
  String? _notice;
  bool _noticeIsError = false;

  final TextEditingController _timezone = TextEditingController();
  final TextEditingController _deletePassword = TextEditingController();

  final TextEditingController _currentPassword = TextEditingController();
  final TextEditingController _newPassword = TextEditingController();
  final TextEditingController _newPasswordConfirm = TextEditingController();
  final Set<int> _weekdays = <int>{};
  TrainingSchedule _schedule = const TrainingSchedule();
  List<ScheduledPause> _pauses = const <ScheduledPause>[];
  bool _savingSchedule = false;
  String? _scheduleNotice;
  bool _scheduleNoticeIsError = false;

  /// `GET /auth/me`: the sign-in methods the section renders (#116).
  Account? _account;

  /// One busy flag for every sign-in-method action, so connect, disconnect,
  /// and the password dialogs can never run over each other.
  bool _methodBusy = false;
  String? _methodNotice;
  bool _methodNoticeIsError = false;

  DateTime _pauseStart = _today();
  DateTime _pauseEnd = _today();
  bool _schedulingPause = false;
  String? _pauseNotice;
  bool _pauseNoticeIsError = false;

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
    _load();
  }

  @override
  void dispose() {
    _timezone.dispose();
    _currentGoalController.dispose();
    _injuriesOrLimitationsController.dispose();
    _weightController.dispose();
    _deletePassword.dispose();
    _currentPassword.dispose();
    _newPassword.dispose();
    _newPasswordConfirm.dispose();
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
        throw const ApiException(_profileContractError);
      }
    }
    final IntakeField frequency = intake.field('weekly_frequency')!;
    if (!_hasValidFrequencyRange(frequency, savedFrequency)) {
      throw const ApiException(_profileContractError);
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
        _loadError = error.message;
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
          title: const Text('Confirm program rebuild'),
          content: const Text('This rebuilds your program'),
          actions: <Widget>[
            TextButton(
              onPressed: () => Navigator.of(context).pop(false),
              child: const Text('Cancel'),
            ),
            FilledButton(
              key: const Key('profile_rebuild_confirm_button'),
              onPressed: () => Navigator.of(context).pop(true),
              child: const Text('Continue'),
            ),
          ],
        ),
      );
      if (confirmed != true || !mounted) return;
    }
    setState(() {
      _saving = true;
      _notice = null;
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
                ? 'Program rebuilt.'
                : 'Profile saved.';
      });
    } on ApiException catch (error) {
      if (!mounted) return;
      setState(() {
        _saving = false;
        _notice = mutationFailureMessage(error);
        _noticeIsError = true;
      });
    }
  }

  String _validationMessage(IntakeField? field) {
    if (field == null) return 'Check your profile details and try again.';
    if (field.name == 'weight_kg' &&
        field.minimum != null &&
        field.maximum != null) {
      return 'Weight must be between ${field.minimum!.toStringAsFixed(0)} and '
          '${field.maximum!.toStringAsFixed(0)} kg.';
    }
    if (field.type == 'enum') {
      return 'Choose an allowed ${optionLabel('', field.name)}.';
    }
    return field.hint ??
        'Check your ${optionLabel('', field.name).toLowerCase()} and try again.';
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
        _scheduleNotice = 'Enter an IANA timezone, e.g. Europe/London or UTC.';
        _scheduleNoticeIsError = true;
      });
      return;
    }
    setState(() {
      _savingSchedule = true;
      _scheduleNotice = null;
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
        _scheduleNotice = 'Training schedule saved.';
        _schedule = refreshed;
      });
    } on ApiException catch (error) {
      if (!mounted) return;
      setState(() {
        _savingSchedule = false;
        _scheduleNotice = mutationFailureMessage(error);
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
      validation = 'A pause must start today or later.';
    } else if (end.isBefore(start)) {
      validation = 'A pause must end on or after it starts.';
    } else if (end.difference(start).inDays + 1 > maxPauseDays) {
      validation = 'A pause can last at most $maxPauseDays days.';
    }
    if (validation != null) {
      setState(() {
        _pauseNotice = validation;
        _pauseNoticeIsError = true;
      });
      return;
    }
    setState(() {
      _schedulingPause = true;
      _pauseNotice = null;
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
            ? 'Pause scheduled; your coach was notified.'
            : 'Pause scheduled.';
        _pauses = <ScheduledPause>[result.pause, ..._pauses];
      });
    } on ApiException catch (error) {
      if (!mounted) return;
      setState(() {
        _schedulingPause = false;
        _pauseNotice = mutationFailureMessage(error);
        _pauseNoticeIsError = true;
      });
    }
  }

  /// Re-reads `GET /auth/me` after a sign-in-method change, so the section
  /// always shows what the service now reports (#116).
  Future<void> _refreshSignInMethods() async {
    try {
      final Account account =
          await ref.read(apiClientProvider).currentAccount();
      if (!mounted) return;
      setState(() => _account = account);
    } on ApiException catch (error) {
      if (!mounted) return;
      setState(() {
        _methodNotice = mutationFailureMessage(error);
        _methodNoticeIsError = true;
      });
    }
  }

  void _setMethodNotice(String message, {required bool error}) {
    setState(() {
      _methodNotice = message;
      _methodNoticeIsError = error;
    });
  }

  /// "Connect Google": one SDK attempt, then `POST /auth/google/link`. Both
  /// service conflicts (#114) are shown verbatim, in the section.
  Future<void> _connectGoogle() => _runConnectGoogle(
        () => ref.read(authControllerProvider.notifier).connectGoogle(),
      );

  Future<void> _connectGoogleOutcome(GoogleAuthOutcome outcome) =>
      _runConnectGoogle(
        () => ref
            .read(authControllerProvider.notifier)
            .connectGoogleOutcome(outcome),
      );

  Future<void> _runConnectGoogle(
      Future<ConnectGoogleResult> Function() connect) async {
    if (_methodBusy) return;
    setState(() {
      _methodBusy = true;
      _methodNotice = null;
      _methodNoticeIsError = false;
    });
    try {
      final ConnectGoogleResult result = await connect();
      if (!mounted) return;
      switch (result) {
        case GoogleConnectDone():
          _setMethodNotice('Google account connected.', error: false);
          await _refreshSignInMethods();
        case GoogleConnectDismissed():
          break;
        case GoogleConnectRefused(:final message):
          _setMethodNotice(message, error: true);
      }
    } finally {
      if (mounted) {
        setState(() => _methodBusy = false);
      }
    }
  }

  /// Disconnecting is confirmation-gated and only offered while the account
  /// still has a password (#114), so nobody can lock themselves out.
  Future<void> _confirmDisconnectGoogle() async {
    if (_methodBusy) return;
    final bool? confirmed = await showDialog<bool>(
      context: context,
      builder: (BuildContext dialogContext) => AlertDialog(
        title: const Text('Disconnect Google?'),
        content: const Text(
          'You will no longer be able to sign in with Google. Your password '
          'stays as the other way to sign in.',
        ),
        actions: <Widget>[
          MayosButton(
            label: 'Cancel',
            variant: MayosButtonVariant.tertiary,
            expand: false,
            onPressed: () => Navigator.of(dialogContext).pop(false),
          ),
          MayosButton(
            key: const Key('disconnect_google_confirm_button'),
            label: 'Disconnect',
            destructive: true,
            expand: false,
            onPressed: () => Navigator.of(dialogContext).pop(true),
          ),
        ],
      ),
    );
    if (confirmed != true || !mounted) return;
    setState(() {
      _methodBusy = true;
      _methodNotice = null;
      _methodNoticeIsError = false;
    });
    try {
      await ref.read(authControllerProvider.notifier).disconnectGoogle();
      if (!mounted) return;
      _setMethodNotice('Google disconnected.', error: false);
      await _refreshSignInMethods();
    } on ApiException catch (error) {
      if (!mounted) return;
      _setMethodNotice(mutationFailureMessage(error), error: true);
    } finally {
      if (mounted) {
        setState(() => _methodBusy = false);
      }
    }
  }

  /// The first password for a Google-only account (`POST /auth/set-password`),
  /// worded by the app's shared password rule (#114/#116).
  Future<void> _promptSetPassword() => _promptPasswordDialog(
        title: 'Set a password',
        intro: 'Choose a password so you can sign in without Google. '
            'Once it is set you can disconnect Google.',
        askCurrent: false,
        confirmLabel: 'Set password',
        currentKey: null,
        passwordKey: const Key('set_password_field'),
        confirmFieldKey: const Key('set_password_confirm_field'),
        submitKey: const Key('set_password_confirm_button'),
        successNotice: 'Password set. You can now disconnect Google.',
        onSubmit: (String current, String password) => ref
            .read(authControllerProvider.notifier)
            .setInitialPassword(password),
      );

  /// Replacing an existing password (`POST /auth/change-password`). The
  /// service revokes every session, so success ends this one with an
  /// explanation on the sign-in screen (ADR 006): there is no [successNotice]
  /// and nothing to re-read.
  Future<void> _promptChangePassword() => _promptPasswordDialog(
        title: 'Change password',
        intro: 'Changing your password signs you out of every device.',
        askCurrent: true,
        confirmLabel: 'Change password',
        currentKey: const Key('change_password_current_field'),
        passwordKey: const Key('change_password_new_field'),
        confirmFieldKey: const Key('change_password_confirm_field'),
        submitKey: const Key('change_password_confirm_button'),
        successNotice: null,
        onSubmit: (String current, String password) => ref
            .read(authControllerProvider.notifier)
            .changePassword(currentPassword: current, newPassword: password),
      );

  /// The one password dialog behind both moves above: a Google-only account
  /// sets its first password, an account with one replaces it. Only the
  /// wording, the optional "current password" field, and [onSubmit] differ.
  ///
  /// The fields live at screen level like [_deletePassword]: the dialog route
  /// is still animating out when `showDialog` resolves, so disposing a
  /// controller there would break the rebuilds of that exit animation.
  Future<void> _promptPasswordDialog({
    required String title,
    required String intro,
    required bool askCurrent,
    required String confirmLabel,
    required Key? currentKey,
    required Key passwordKey,
    required Key confirmFieldKey,
    required Key submitKey,
    required String? successNotice,
    required Future<void> Function(String current, String password) onSubmit,
  }) async {
    if (_methodBusy) return;
    _currentPassword.clear();
    _newPassword.clear();
    _newPasswordConfirm.clear();
    bool busy = false;
    bool done = false;
    String? error;
    await showDialog<void>(
      context: context,
      builder: (BuildContext dialogContext) => StatefulBuilder(
        builder: (BuildContext context, StateSetter setDialogState) =>
            AlertDialog(
          title: Text(title),
          content: SingleChildScrollView(
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: <Widget>[
                Text(intro),
                const SizedBox(height: MayosSpacing.md),
                if (askCurrent) ...<Widget>[
                  AuthPasswordField(
                    controller: _currentPassword,
                    fieldKey: currentKey,
                    label: 'Current password',
                  ),
                  const SizedBox(height: MayosSpacing.sm),
                ],
                AuthPasswordField(
                  controller: _newPassword,
                  fieldKey: passwordKey,
                  label: 'New password',
                ),
                const SizedBox(height: MayosSpacing.sm),
                AuthPasswordField(
                  controller: _newPasswordConfirm,
                  fieldKey: confirmFieldKey,
                  label: 'Confirm new password',
                ),
                if (error != null) ...<Widget>[
                  const SizedBox(height: MayosSpacing.sm),
                  Text(
                    error!,
                    style: MayosTypography.bodySecondary
                        .copyWith(color: MayosTheme.of(context).danger),
                  ),
                ],
              ],
            ),
          ),
          actions: <Widget>[
            MayosButton(
              label: 'Cancel',
              variant: MayosButtonVariant.tertiary,
              expand: false,
              onPressed: busy ? null : () => Navigator.of(dialogContext).pop(),
            ),
            MayosButton(
              key: submitKey,
              label: confirmLabel,
              expand: false,
              loading: busy,
              onPressed: busy
                  ? null
                  : () async {
                      if (askCurrent && _currentPassword.text.isEmpty) {
                        setDialogState(
                            () => error = 'Enter your current password.');
                        return;
                      }
                      final NewPasswordValidation? invalid =
                          validateNewPassword(
                              _newPassword.text, _newPasswordConfirm.text);
                      if (invalid != null) {
                        final MayosCopy copy =
                            MayosCopy(ref.read(displayLanguageProvider));
                        setDialogState(() => error =
                            newPasswordValidationMessage(invalid, copy));
                        return;
                      }
                      setDialogState(() {
                        busy = true;
                        error = null;
                      });
                      try {
                        await onSubmit(
                            _currentPassword.text, _newPassword.text);
                        done = true;
                        if (dialogContext.mounted) {
                          Navigator.of(dialogContext).pop();
                        }
                      } on ApiException catch (failure) {
                        setDialogState(() {
                          busy = false;
                          error = mutationFailureMessage(failure);
                        });
                      }
                    },
            ),
          ],
        ),
      ),
    );
    if (!done || successNotice == null || !mounted) return;
    setState(() => _methodBusy = true);
    _setMethodNotice(successNotice, error: false);
    await _refreshSignInMethods();
    if (mounted) {
      setState(() => _methodBusy = false);
    }
  }

  /// Proof-confirmed, irreversible account deletion (ADR 015/039).
  ///
  /// The player sees exactly what is removed, including unsynced drafts on this
  /// device. An account with a password confirms with that password; a
  /// Google-only account has no password to type, so it confirms by re-running
  /// Google sign-in for a fresh ID token (#114/#116). A wrong proof, a
  /// dismissed Google sheet, or an offline attempt changes nothing.
  Future<void> _confirmDeleteAccount() async {
    _deletePassword.clear();
    final bool googleOnly = !(_account?.hasPassword ?? true);
    final GoogleAuthGateway google = ref.read(googleAuthGatewayProvider);
    final bool webGoogle =
        googleOnly && google.buttonStyle == GoogleSignInButtonStyle.webRendered;
    bool busy = false;
    String? error;
    await showDialog<void>(
      context: context,
      builder: (BuildContext dialogContext) => StatefulBuilder(
        builder: (BuildContext context, StateSetter setDialogState) =>
            AlertDialog(
          title: const Text('Delete account?'),
          content: SingleChildScrollView(
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: <Widget>[
                const Text(
                  'This permanently deletes your account and its active data: '
                  'training history, program, coaching assignment, recovery '
                  'email, and any unsynced drafts on this device. '
                  'This cannot be undone.',
                ),
                const SizedBox(height: MayosSpacing.md),
                if (googleOnly)
                  const Text(
                    'There is no password on this account, so confirm by '
                    'signing in with Google: you will be asked to prove the '
                    'Google account connected to this MAYOS account.',
                  )
                else ...<Widget>[
                  MayosTextField(
                    fieldKey: const Key('delete_account_password_field'),
                    controller: _deletePassword,
                    obscureText: true,
                    enabled: !busy,
                    label: 'Password',
                  ),
                ],
                if (webGoogle) ...<Widget>[
                  const SizedBox(height: MayosSpacing.md),
                  GoogleWebSignInButton(
                    key: const Key('delete_account_google_web_button'),
                    loading: busy,
                    fixedWidth: (MediaQuery.sizeOf(dialogContext).width -
                            2 * (MayosSpacing.xxxl + MayosSpacing.xl))
                        .clamp(0.0, MayosLayout.googleButtonMaxWidth),
                    onOutcome: (GoogleAuthOutcome outcome) =>
                        _handleGoogleDelete(
                      delete: () => ref
                          .read(authControllerProvider.notifier)
                          .deleteAccountWithGoogleOutcome(outcome),
                      isBusy: () => busy,
                      dialogContext: dialogContext,
                      updateDialog: (bool nextBusy, String? nextError) =>
                          setDialogState(() {
                        busy = nextBusy;
                        error = nextError;
                      }),
                    ),
                  ),
                ],
                if (error != null) ...<Widget>[
                  const SizedBox(height: MayosSpacing.sm),
                  Text(
                    error!,
                    style: MayosTypography.bodySecondary
                        .copyWith(color: MayosTheme.of(context).danger),
                  ),
                ],
              ],
            ),
          ),
          actions: <Widget>[
            MayosButton(
              label: 'Cancel',
              variant: MayosButtonVariant.tertiary,
              expand: false,
              onPressed: busy ? null : () => Navigator.of(dialogContext).pop(),
            ),
            if (!webGoogle)
              MayosButton(
                key: const Key('delete_account_confirm_button'),
                label: 'Delete account',
                destructive: true,
                expand: false,
                loading: busy,
                onPressed: busy
                    ? null
                    : () async {
                        if (googleOnly) {
                          await _handleGoogleDelete(
                            delete: () => ref
                                .read(authControllerProvider.notifier)
                                .deleteAccountWithGoogle(),
                            isBusy: () => busy,
                            dialogContext: dialogContext,
                            updateDialog: (bool nextBusy, String? nextError) {
                              setDialogState(() {
                                busy = nextBusy;
                                error = nextError;
                              });
                            },
                          );
                          return;
                        }
                        setDialogState(() {
                          busy = true;
                          error = null;
                        });
                        try {
                          await ref
                              .read(authControllerProvider.notifier)
                              .deleteAccount(_deletePassword.text);
                          if (dialogContext.mounted) {
                            Navigator.of(dialogContext).pop();
                          }
                        } on ApiException catch (failure) {
                          setDialogState(() {
                            busy = false;
                            error = mutationFailureMessage(failure);
                          });
                        }
                      },
              ),
          ],
        ),
      ),
    );
  }

  Future<void> _handleGoogleDelete({
    required Future<DeleteWithGoogleResult> Function() delete,
    required bool Function() isBusy,
    required BuildContext dialogContext,
    required void Function(bool busy, String? error) updateDialog,
  }) async {
    if (isBusy()) return;
    updateDialog(true, null);
    final DeleteWithGoogleResult result = await delete();
    if (result case DeleteWithGoogleRefused(:final message)) {
      updateDialog(false, message);
      return;
    }
    if (result is DeleteWithGoogleDismissed) {
      updateDialog(false, kGoogleDeleteCancelledMessage);
      return;
    }
    if (dialogContext.mounted) {
      Navigator.of(dialogContext).pop();
    }
  }

  /// The "Sign-in methods" card, driven entirely by `GET /auth/me` (#116):
  /// Password (set or change) and Google (connect or disconnect), where
  /// disconnecting is only offered while a password exists.
  Widget _buildSignInMethods(MayosThemeExtension c) {
    final Account account = _account!;
    final GoogleAuthGateway google = ref.watch(googleAuthGatewayProvider);
    final bool hasPassword = account.hasPassword;
    final bool googleLinked = account.hasGoogleLink;
    return MayosCard(
      padding: const EdgeInsets.symmetric(
          horizontal: MayosSpacing.sm, vertical: MayosSpacing.xxs),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: <Widget>[
          _SignInMethodRow(
            leading: MayosIconChip(
              child: Icon(
                Icons.lock_outline,
                size: MayosIconSizes.medium,
                color: c.accent,
              ),
            ),
            title: 'Password',
            status: hasPassword ? 'Password set' : 'No password yet',
            action: MayosButton(
              key: Key(hasPassword
                  ? 'change_password_button'
                  : 'set_password_button'),
              label: hasPassword ? 'Change password' : 'Set password',
              variant: MayosButtonVariant.secondary,
              onPressed: _methodBusy
                  ? null
                  : hasPassword
                      ? _promptChangePassword
                      : _promptSetPassword,
            ),
          ),
          const SizedBox(height: MayosSpacing.xxs),
          const Divider(height: 1),
          const SizedBox(height: MayosSpacing.xxs),
          _SignInMethodRow(
            leading: const MayosIconChip(
                child: GoogleGLogo(size: MayosIconSizes.medium)),
            title: 'Google',
            status: googleLinked ? 'Connected' : 'Not connected',
            hint: googleLinked && !hasPassword ? 'Set a password first' : null,
            action: googleLinked
                ? MayosButton(
                    key: const Key('disconnect_google_button'),
                    label: 'Disconnect Google',
                    variant: MayosButtonVariant.secondary,
                    onPressed: _methodBusy || !hasPassword
                        ? null
                        : _confirmDisconnectGoogle,
                  )
                : google.buttonStyle == GoogleSignInButtonStyle.hidden
                    ? const SizedBox.shrink()
                    : google.buttonStyle == GoogleSignInButtonStyle.webRendered
                        ? GoogleWebSignInButton(
                            key: const Key('connect_google_web_button'),
                            loading: _methodBusy,
                            onOutcome: _connectGoogleOutcome,
                          )
                        : MayosButton(
                            key: const Key('connect_google_button'),
                            label: 'Connect Google',
                            variant: MayosButtonVariant.secondary,
                            loading: _methodBusy,
                            onPressed: _methodBusy ? null : _connectGoogle,
                          ),
          ),
        ],
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
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
              Text(_loadError!, textAlign: TextAlign.center),
              const SizedBox(height: MayosSpacing.md),
              MayosButton(
                label: 'Retry',
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
        const MayosSectionHeader(
          title: 'Sign-in methods',
          padding: EdgeInsets.only(bottom: MayosSpacing.xxs),
        ),
        const SizedBox(height: MayosSpacing.xxs),
        if (_account != null) _buildSignInMethods(c),
        if (_methodNotice != null) ...<Widget>[
          const SizedBox(height: MayosSpacing.sm),
          Text(
            _methodNotice!,
            style: _methodNoticeIsError
                ? MayosTypography.bodySecondary.copyWith(color: c.danger)
                : MayosTypography.body,
          ),
        ],
        const SizedBox(height: MayosSpacing.lg),
        const MayosSectionHeader(
          title: 'Training profile',
          subtitle:
              'Update the profile facts used to personalize your training.',
        ),
        const SizedBox(height: MayosSpacing.md),
        MayosTextField(
          fieldKey: const Key('current_goal_field'),
          controller: _currentGoalController,
          label: 'Current goal',
          enabled: !_saving,
          textCapitalization: TextCapitalization.sentences,
        ),
        const SizedBox(height: MayosSpacing.sm),
        MayosTextField(
          fieldKey: const Key('injuries_or_limitations_field'),
          controller: _injuriesOrLimitationsController,
          label: 'Injuries or limitations',
          enabled: !_saving,
          textCapitalization: TextCapitalization.sentences,
        ),
        const SizedBox(height: MayosSpacing.sm),
        MayosTextField(
          fieldKey: const Key('weight_kg_field'),
          controller: _weightController,
          label: 'Weight (kg)',
          enabled: !_saving,
          keyboardType: const TextInputType.numberWithOptions(decimal: true),
        ),
        const SizedBox(height: MayosSpacing.sm),
        DropdownButtonFormField<int>(
          initialValue: _weeklyFrequency,
          isExpanded: true,
          decoration: const InputDecoration(
            labelText: 'Training days per week',
            border: OutlineInputBorder(),
          ),
          items: <DropdownMenuItem<int>>[
            for (int days =
                    _intake!.field('weekly_frequency')!.minimum!.toInt();
                days <= _intake!.field('weekly_frequency')!.maximum!.toInt();
                days++)
              DropdownMenuItem<int>(value: days, child: Text('$days')),
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
          decoration: const InputDecoration(
            labelText: 'Rep preference',
            border: OutlineInputBorder(),
          ),
          items: <DropdownMenuItem<String>>[
            for (final String preference
                in _intake!.field('rep_preference')!.allowedValues)
              DropdownMenuItem<String>(
                  value: preference,
                  child: Text(optionLabel('rep_preference', preference),
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
          decoration: const InputDecoration(
            labelText: 'Equipment access',
            border: OutlineInputBorder(),
          ),
          items: <DropdownMenuItem<String>>[
            for (final String access
                in _intake!.field('equipment_access')!.allowedValues)
              DropdownMenuItem<String>(value: access, child: Text(access)),
          ],
          onChanged: _saving
              ? null
              : (String? selectedAccess) => setState(() {
                    _equipmentAccess = selectedAccess ?? _equipmentAccess;
                  }),
        ),
        if (_notice != null) ...<Widget>[
          const SizedBox(height: MayosSpacing.sm),
          Text(
            _notice!,
            style: _noticeIsError
                ? MayosTypography.bodySecondary.copyWith(color: c.danger)
                : MayosTypography.body,
          ),
        ],
        const SizedBox(height: MayosSpacing.lg),
        MayosButton(
          label: 'Save profile',
          loading: _saving,
          onPressed: _saving ? null : _save,
        ),
        const SizedBox(height: MayosSpacing.xxl),
        const Divider(),
        const SizedBox(height: MayosSpacing.sm),
        const MayosSectionHeader(
          title: 'Training schedule',
          subtitle:
              'Expected weekdays and timezone, separate from your program.',
        ),
        const SizedBox(height: MayosSpacing.md),
        Wrap(
          spacing: MayosSpacing.xs,
          runSpacing: MayosSpacing.xs,
          children: <Widget>[
            for (int day = 1; day <= 7; day++)
              FilterChip(
                key: Key('weekday_chip_$day'),
                label: Text(weekdayLabels[day - 1]),
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
        MayosTextField(
          fieldKey: const Key('timezone_field'),
          controller: _timezone,
          enabled: !_savingSchedule,
          label: 'Timezone',
        ),
        if (_scheduleNotice != null) ...<Widget>[
          const SizedBox(height: MayosSpacing.sm),
          Text(
            _scheduleNotice!,
            style: _scheduleNoticeIsError
                ? MayosTypography.bodySecondary.copyWith(color: c.danger)
                : MayosTypography.body,
          ),
        ],
        const SizedBox(height: MayosSpacing.sm),
        MayosButton(
          key: const Key('save_schedule_button'),
          label: 'Save schedule',
          loading: _savingSchedule,
          onPressed: _savingSchedule ? null : _saveSchedule,
        ),
        const SizedBox(height: MayosSpacing.xl),
        const MayosSectionHeader(title: 'Training pause'),
        Row(
          children: <Widget>[
            Expanded(
              child: MayosButton(
                key: const Key('pause_start_button'),
                label: 'Start: ${_formatDate(_pauseStart)}',
                variant: MayosButtonVariant.secondary,
                onPressed:
                    _schedulingPause ? null : () => _pickPauseDate(start: true),
              ),
            ),
            const SizedBox(width: MayosSpacing.xs),
            Expanded(
              child: MayosButton(
                key: const Key('pause_end_button'),
                label: 'End: ${_formatDate(_pauseEnd)}',
                variant: MayosButtonVariant.secondary,
                onPressed: _schedulingPause
                    ? null
                    : () => _pickPauseDate(start: false),
              ),
            ),
          ],
        ),
        if (_pauseNotice != null) ...<Widget>[
          const SizedBox(height: MayosSpacing.sm),
          Text(
            _pauseNotice!,
            style: _pauseNoticeIsError
                ? MayosTypography.bodySecondary.copyWith(color: c.danger)
                : MayosTypography.body,
          ),
        ],
        const SizedBox(height: MayosSpacing.sm),
        MayosButton(
          key: const Key('schedule_pause_button'),
          label: 'Schedule pause',
          loading: _schedulingPause,
          onPressed: _schedulingPause ? null : _schedulePause,
        ),
        const SizedBox(height: MayosSpacing.sm),
        if (_pauses.isEmpty)
          Text('No scheduled pauses.',
              style: MayosTypography.bodySecondary
                  .copyWith(color: c.textSecondary))
        else
          for (final ScheduledPause pause in _pauses)
            Text(
              'Pause: ${pause.startsOn} → ${pause.endsOn}',
              style: MayosTypography.body.copyWith(color: c.textPrimary),
            ),
        const SizedBox(height: MayosSpacing.xl),
        const Divider(),
        const SizedBox(height: MayosSpacing.sm),
        const MayosSectionHeader(
          title: 'Danger zone',
          subtitle: 'Deleting your account permanently removes it and its '
              'active data, including unsynced drafts on this device. It '
              'cannot be undone.',
        ),
        const SizedBox(height: MayosSpacing.sm),
        MayosButton(
          key: const Key('delete_account_button'),
          label: 'Delete account',
          icon: Icons.delete_forever_outlined,
          variant: MayosButtonVariant.secondary,
          destructive: true,
          expand: false,
          onPressed: _confirmDeleteAccount,
        ),
      ],
    );
  }
}

/// One row of the "Sign-in methods" card: an icon chip beside the method's
/// name and live state (plus an optional hint), then its full-width action —
/// stacked so nothing is squeezed at 360dp (#116).
class _SignInMethodRow extends StatelessWidget {
  const _SignInMethodRow({
    required this.leading,
    required this.title,
    required this.status,
    required this.action,
    this.hint,
  });

  final Widget leading;
  final String title;
  final String status;
  final String? hint;
  final Widget action;

  @override
  Widget build(BuildContext context) {
    final MayosThemeExtension c = MayosTheme.of(context);
    final TextTheme text = Theme.of(context).textTheme;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: <Widget>[
        Row(
          crossAxisAlignment: CrossAxisAlignment.center,
          children: <Widget>[
            leading,
            const SizedBox(width: MayosSpacing.sm),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                mainAxisSize: MainAxisSize.min,
                children: <Widget>[
                  Text(
                    title,
                    style: text.titleSmall?.copyWith(color: c.textPrimary),
                  ),
                  const SizedBox(height: 2),
                  Text(
                    status,
                    style: text.bodySmall?.copyWith(color: c.textMuted),
                  ),
                  if (hint != null) ...<Widget>[
                    const SizedBox(height: 2),
                    Text(
                      hint!,
                      style: text.bodySmall?.copyWith(color: c.warning),
                    ),
                  ],
                ],
              ),
            ),
          ],
        ),
        const SizedBox(height: MayosSpacing.xs),
        action,
      ],
    );
  }
}

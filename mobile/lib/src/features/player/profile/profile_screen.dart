import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api_client.dart';
import '../../../core/connectivity_message.dart';
import '../../../core/device_timezone.dart';
import '../../../core/models.dart';
import '../../../core/theme/mayos_spacing.dart';
import '../../../core/theme/mayos_theme.dart';
import '../../../core/theme/mayos_typography.dart';
import '../../../core/ui/mayos_button.dart';
import '../../../core/ui/mayos_section_header.dart';
import '../../../core/ui/mayos_text_field.dart';
import '../../../providers.dart';
import '../onboarding/onboarding_widgets.dart' show optionLabel;

/// Mirrors the server's `MAX_PAUSE_DAYS` in `service/schedule.py`; the client
/// check is only a courtesy, the service stays authoritative.
const int maxPauseDays = 14;

/// Player training-profile editor. Saving can trigger a program rebuild, which
/// is a player write path: when the assigned coach owns the active program the
/// service leaves it unchanged and explains that a coach request is needed.
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
  /// The intake's allowed `rep_preference` values (`service/intake.py`).
  static const List<String> _repPreferences = <String>[
    'low',
    'balanced',
    'high',
  ];

  int _weeklyFrequency = 4;
  String _repPreference = 'balanced';

  bool _loading = true;
  bool _saving = false;
  String? _loadError;
  String? _notice;
  bool _noticeIsError = false;

  final TextEditingController _timezone = TextEditingController();
  final TextEditingController _deletePassword = TextEditingController();
  final Set<int> _weekdays = <int>{};
  TrainingSchedule _schedule = const TrainingSchedule();
  List<ScheduledPause> _pauses = const <ScheduledPause>[];
  bool _savingSchedule = false;
  String? _scheduleNotice;
  bool _scheduleNoticeIsError = false;

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
    _deletePassword.dispose();
    super.dispose();
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
      ]);
      if (!mounted) return;
      final PlayerProfile profile = results[0] as PlayerProfile;
      final TrainingSchedule schedule = results[1] as TrainingSchedule;
      final List<ScheduledPause> pauses = results[2] as List<ScheduledPause>;
      final String timezone = schedule.current != null
          ? schedule.current!.timezone
          : await ref.read(deviceTimezoneProvider);
      if (!mounted) return;
      setState(() {
        _weeklyFrequency = profile.weeklyFrequency;
        // A value this screen once offered by mistake (`strength`,
        // `hypertrophy`) is shown as the generator reads it: balanced.
        _repPreference = _repPreferences.contains(profile.repPreference)
            ? profile.repPreference
            : 'balanced';
        _schedule = schedule;
        _pauses = pauses;
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
    setState(() {
      _saving = true;
      _notice = null;
      _noticeIsError = false;
    });
    try {
      final ProfileUpdateResult result =
          await ref.read(apiClientProvider).updateProfile(
                weeklyFrequency: _weeklyFrequency,
                repPreference: _repPreference,
              );
      if (!mounted) return;
      setState(() {
        _saving = false;
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

  /// Password-confirmed, irreversible account deletion (ADR 015/039).
  ///
  /// The player sees exactly what is removed, including unsynced drafts on this
  /// device, and must confirm with their password. A wrong password or an
  /// offline attempt changes nothing.
  Future<void> _confirmDeleteAccount() async {
    _deletePassword.clear();
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
                MayosTextField(
                  fieldKey: const Key('delete_account_password_field'),
                  controller: _deletePassword,
                  obscureText: true,
                  enabled: !busy,
                  label: 'Password',
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
              key: const Key('delete_account_confirm_button'),
              label: 'Delete account',
              destructive: true,
              expand: false,
              loading: busy,
              onPressed: busy
                  ? null
                  : () async {
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
          title: 'Training profile',
          subtitle: 'Saving changes can rebuild your program.',
        ),
        const SizedBox(height: MayosSpacing.md),
        DropdownButtonFormField<int>(
          initialValue: _weeklyFrequency,
          isExpanded: true,
          decoration: const InputDecoration(
            labelText: 'Training days per week',
            border: OutlineInputBorder(),
          ),
          items: <DropdownMenuItem<int>>[
            for (int days = 1; days <= 5; days++)
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
            for (final String preference in _repPreferences)
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
        const SizedBox(height: MayosSpacing.xxl),
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

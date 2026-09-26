import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api_client.dart';
import '../../../core/models.dart';
import '../../../providers.dart';

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
  static const List<String> _repPreferences = <String>[
    'balanced',
    'strength',
    'hypertrophy',
  ];

  int _weeklyFrequency = 4;
  String _repPreference = 'balanced';

  bool _loading = true;
  bool _saving = false;
  String? _loadError;
  String? _notice;
  bool _noticeIsError = false;

  final TextEditingController _timezone = TextEditingController();
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
      setState(() {
        _weeklyFrequency = profile.weeklyFrequency;
        _repPreference = profile.repPreference;
        _schedule = schedule;
        _pauses = pauses;
        _weekdays
          ..clear()
          ..addAll(_schedule.current?.weekdays ?? const <int>[]);
        _timezone.text = _schedule.current?.timezone ?? 'UTC';
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
        _notice = error.message;
        _noticeIsError = true;
      });
    }
  }

  Future<void> _saveSchedule() async {
    setState(() {
      _savingSchedule = true;
      _scheduleNotice = null;
      _scheduleNoticeIsError = false;
    });
    try {
      final List<int> weekdays = _weekdays.toList()..sort();
      await ref.read(apiClientProvider).setTrainingSchedule(
            weekdays: weekdays,
            timezone: _timezone.text.trim(),
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
        _scheduleNotice = error.message;
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
    final DateTime start = DateTime(
        _pauseStart.year, _pauseStart.month, _pauseStart.day);
    final DateTime end =
        DateTime(_pauseEnd.year, _pauseEnd.month, _pauseEnd.day);
    String? validation;
    if (start.isBefore(today)) {
      validation = 'A pause must start today or later.';
    } else if (end.isBefore(start)) {
      validation = 'A pause must end on or after it starts.';
    } else if (end.difference(start).inDays + 1 > 14) {
      validation = 'A pause can last at most 14 days.';
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
        _pauseNotice = error.message;
        _pauseNoticeIsError = true;
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    if (_loading) {
      return const Center(child: CircularProgressIndicator());
    }
    if (_loadError != null) {
      return Center(
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: <Widget>[
              Text(_loadError!, textAlign: TextAlign.center),
              const SizedBox(height: 16),
              FilledButton(onPressed: _load, child: const Text('Retry')),
            ],
          ),
        ),
      );
    }
    final ThemeData theme = Theme.of(context);
    return ListView(
      padding: const EdgeInsets.all(16),
      children: <Widget>[
        Text('Training profile', style: theme.textTheme.titleLarge),
        const SizedBox(height: 4),
        Text(
          'Saving changes can rebuild your program.',
          style: theme.textTheme.bodySmall,
        ),
        const SizedBox(height: 16),
        DropdownButtonFormField<int>(
          initialValue: _weeklyFrequency,
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
              : (int? value) => setState(
                  () => _weeklyFrequency = value ?? _weeklyFrequency),
        ),
        const SizedBox(height: 12),
        DropdownButtonFormField<String>(
          initialValue: _repPreference,
          decoration: const InputDecoration(
            labelText: 'Rep preference',
            border: OutlineInputBorder(),
          ),
          items: <DropdownMenuItem<String>>[
            for (final String preference in _repPreferences)
              DropdownMenuItem<String>(
                  value: preference, child: Text(preference)),
          ],
          onChanged: _saving
              ? null
              : (String? value) => setState(
                  () => _repPreference = value ?? _repPreference),
        ),
        if (_notice != null) ...<Widget>[
          const SizedBox(height: 12),
          Text(
            _notice!,
            style: _noticeIsError
                ? TextStyle(color: theme.colorScheme.error)
                : theme.textTheme.bodyMedium,
          ),
        ],
        const SizedBox(height: 20),
        FilledButton(
          onPressed: _saving ? null : _save,
          child: _saving
              ? const SizedBox(
                  height: 20,
                  width: 20,
                  child: CircularProgressIndicator(strokeWidth: 2),
                )
              : const Text('Save profile'),
        ),
        const SizedBox(height: 32),
        const Divider(),
        const SizedBox(height: 8),
        Text('Training schedule', style: theme.textTheme.titleLarge),
        const SizedBox(height: 4),
        Text(
          'Expected weekdays and timezone, separate from your program.',
          style: theme.textTheme.bodySmall,
        ),
        const SizedBox(height: 16),
        Wrap(
          spacing: 8,
          runSpacing: 8,
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
        const SizedBox(height: 12),
        TextField(
          key: const Key('timezone_field'),
          controller: _timezone,
          enabled: !_savingSchedule,
          decoration: const InputDecoration(
            labelText: 'Timezone',
            border: OutlineInputBorder(),
          ),
        ),
        if (_scheduleNotice != null) ...<Widget>[
          const SizedBox(height: 12),
          Text(
            _scheduleNotice!,
            style: _scheduleNoticeIsError
                ? TextStyle(color: theme.colorScheme.error)
                : theme.textTheme.bodyMedium,
          ),
        ],
        const SizedBox(height: 12),
        FilledButton(
          key: const Key('save_schedule_button'),
          onPressed: _savingSchedule ? null : _saveSchedule,
          child: _savingSchedule
              ? const SizedBox(
                  height: 20,
                  width: 20,
                  child: CircularProgressIndicator(strokeWidth: 2),
                )
              : const Text('Save schedule'),
        ),
        const SizedBox(height: 24),
        Text('Training pause', style: theme.textTheme.titleMedium),
        const SizedBox(height: 8),
        Row(
          children: <Widget>[
            Expanded(
              child: OutlinedButton(
                key: const Key('pause_start_button'),
                onPressed:
                    _schedulingPause ? null : () => _pickPauseDate(start: true),
                child: Text('Start: ${_formatDate(_pauseStart)}'),
              ),
            ),
            const SizedBox(width: 8),
            Expanded(
              child: OutlinedButton(
                key: const Key('pause_end_button'),
                onPressed:
                    _schedulingPause ? null : () => _pickPauseDate(start: false),
                child: Text('End: ${_formatDate(_pauseEnd)}'),
              ),
            ),
          ],
        ),
        if (_pauseNotice != null) ...<Widget>[
          const SizedBox(height: 12),
          Text(
            _pauseNotice!,
            style: _pauseNoticeIsError
                ? TextStyle(color: theme.colorScheme.error)
                : theme.textTheme.bodyMedium,
          ),
        ],
        const SizedBox(height: 12),
        FilledButton(
          key: const Key('schedule_pause_button'),
          onPressed: _schedulingPause ? null : _schedulePause,
          child: _schedulingPause
              ? const SizedBox(
                  height: 20,
                  width: 20,
                  child: CircularProgressIndicator(strokeWidth: 2),
                )
              : const Text('Schedule pause'),
        ),
        const SizedBox(height: 12),
        if (_pauses.isEmpty)
          const Text('No scheduled pauses.')
        else
          for (final ScheduledPause pause in _pauses)
            Text('Pause: ${pause.startsOn} → ${pause.endsOn}'),
      ],
    );
  }
}

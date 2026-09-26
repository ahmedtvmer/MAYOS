import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api_client.dart';
import '../../../core/models.dart';
import '../../../providers.dart';

/// Player training-profile editor. Saving can trigger a program rebuild, which
/// is a player write path: when the assigned coach owns the active program the
/// service leaves it unchanged and explains that a coach request is needed.
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

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    setState(() {
      _loading = true;
      _loadError = null;
    });
    try {
      final PlayerProfile profile =
          await ref.read(apiClientProvider).profile();
      if (!mounted) return;
      setState(() {
        _weeklyFrequency = profile.weeklyFrequency;
        _repPreference = profile.repPreference;
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
    return ListView(
      padding: const EdgeInsets.all(16),
      children: <Widget>[
        Text('Training profile',
            style: Theme.of(context).textTheme.titleLarge),
        const SizedBox(height: 4),
        Text(
          'Saving changes can rebuild your program.',
          style: Theme.of(context).textTheme.bodySmall,
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
                ? TextStyle(color: Theme.of(context).colorScheme.error)
                : Theme.of(context).textTheme.bodyMedium,
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
      ],
    );
  }
}

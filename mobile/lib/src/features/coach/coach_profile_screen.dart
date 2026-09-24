import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api_client.dart';
import '../../core/models.dart';
import '../../providers.dart';

/// Coach profile editor (#23): display name, bio, specialization, capacity.
///
/// Only reachable when the account holds the coach capability; the roster and
/// assignment surfaces arrive in later tickets (#24–#26) and are not stubbed here.
class CoachProfileScreen extends ConsumerStatefulWidget {
  const CoachProfileScreen({super.key});

  @override
  ConsumerState<CoachProfileScreen> createState() => _CoachProfileScreenState();
}

class _CoachProfileScreenState extends ConsumerState<CoachProfileScreen> {
  static const int _maxDisplayName = 60;
  static const int _maxBio = 1000;
  static const int _maxSpecialization = 200;
  static const int _minCapacity = 1;
  static const int _maxCapacity = 200;

  final GlobalKey<FormState> _formKey = GlobalKey<FormState>();
  final TextEditingController _displayName = TextEditingController();
  final TextEditingController _bio = TextEditingController();
  final TextEditingController _specialization = TextEditingController();
  final TextEditingController _capacity = TextEditingController();

  bool _loading = true;
  bool _saving = false;
  String? _loadError;
  String? _saveError;

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void dispose() {
    _displayName.dispose();
    _bio.dispose();
    _specialization.dispose();
    _capacity.dispose();
    super.dispose();
  }

  Future<void> _load() async {
    setState(() {
      _loading = true;
      _loadError = null;
    });
    try {
      final CoachProfile profile =
          await ref.read(apiClientProvider).coachProfile();
      if (!mounted) return;
      _displayName.text = profile.displayName;
      _bio.text = profile.bio;
      _specialization.text = profile.specialization;
      _capacity.text = profile.capacity.toString();
      setState(() => _loading = false);
    } on ApiException catch (error) {
      if (!mounted) return;
      setState(() {
        _loading = false;
        _loadError = error.message;
      });
    }
  }

  Future<void> _save() async {
    setState(() => _saveError = null);
    if (!_formKey.currentState!.validate()) {
      return;
    }
    setState(() => _saving = true);
    try {
      await ref.read(apiClientProvider).updateCoachProfile(
            displayName: _displayName.text.trim(),
            bio: _bio.text,
            specialization: _specialization.text,
            capacity: int.parse(_capacity.text.trim()),
          );
      if (!mounted) return;
      setState(() => _saving = false);
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Coach profile saved.')),
      );
    } on ApiException catch (error) {
      if (!mounted) return;
      setState(() {
        _saving = false;
        _saveError = error.message;
      });
    }
  }

  String? _validateDisplayName(String? value) {
    final String trimmed = (value ?? '').trim();
    if (trimmed.isEmpty) {
      return 'Enter a display name.';
    }
    if (trimmed.length > _maxDisplayName) {
      return 'Display name must be at most $_maxDisplayName characters.';
    }
    return null;
  }

  String? _validateCapacity(String? value) {
    final int? parsed = int.tryParse((value ?? '').trim());
    if (parsed == null) {
      return 'Enter a whole number.';
    }
    if (parsed < _minCapacity || parsed > _maxCapacity) {
      return 'Capacity must be between $_minCapacity and $_maxCapacity.';
    }
    return null;
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
    return Form(
      key: _formKey,
      child: ListView(
        padding: const EdgeInsets.all(16),
        children: <Widget>[
          Text(
            'Coach profile',
            style: Theme.of(context).textTheme.titleLarge,
          ),
          const SizedBox(height: 4),
          Text(
            'These details describe you as a coach.',
            style: Theme.of(context).textTheme.bodySmall,
          ),
          const SizedBox(height: 16),
          TextFormField(
            controller: _displayName,
            maxLength: _maxDisplayName,
            decoration: const InputDecoration(
              labelText: 'Display name',
              border: OutlineInputBorder(),
            ),
            validator: _validateDisplayName,
          ),
          const SizedBox(height: 12),
          TextFormField(
            controller: _specialization,
            maxLength: _maxSpecialization,
            decoration: const InputDecoration(
              labelText: 'Specialization',
              hintText: 'e.g. Powerlifting, Hypertrophy',
              border: OutlineInputBorder(),
            ),
          ),
          const SizedBox(height: 12),
          TextFormField(
            controller: _bio,
            maxLength: _maxBio,
            maxLines: 4,
            decoration: const InputDecoration(
              labelText: 'Bio',
              border: OutlineInputBorder(),
            ),
          ),
          const SizedBox(height: 12),
          TextFormField(
            controller: _capacity,
            keyboardType: TextInputType.number,
            decoration: const InputDecoration(
              labelText: 'Roster capacity',
              helperText: 'Between $_minCapacity and $_maxCapacity players.',
              border: OutlineInputBorder(),
            ),
            validator: _validateCapacity,
          ),
          if (_saveError != null) ...<Widget>[
            const SizedBox(height: 12),
            Text(
              _saveError!,
              style: TextStyle(color: Theme.of(context).colorScheme.error),
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
      ),
    );
  }
}

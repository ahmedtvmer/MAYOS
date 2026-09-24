import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/api_client.dart';
import '../../providers.dart';
import '../../router.dart';

/// Redemption entry for an owner-issued coach invitation.
///
/// The code is account-bound and single-use; a successful redemption refreshes
/// the registry capabilities, which unlocks the coach route.
class CoachInviteScreen extends ConsumerStatefulWidget {
  const CoachInviteScreen({super.key});

  @override
  ConsumerState<CoachInviteScreen> createState() => _CoachInviteScreenState();
}

class _CoachInviteScreenState extends ConsumerState<CoachInviteScreen> {
  final TextEditingController _token = TextEditingController();
  bool _submitting = false;
  String? _error;

  @override
  void dispose() {
    _token.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    final String token = _token.text.trim();
    if (token.length < 10) {
      setState(() => _error = 'Enter the invite code you received.');
      return;
    }
    setState(() {
      _submitting = true;
      _error = null;
    });
    try {
      await ref.read(authControllerProvider.notifier).redeemCoachInvite(token);
      if (!mounted) return;
      setState(() => _submitting = false);
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Coach capability enabled.')),
      );
      context.go(coachPath);
    } on ApiException catch (error) {
      if (!mounted) return;
      setState(() {
        _submitting = false;
        _error = error.message;
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Coach invite')),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: <Widget>[
          Text(
            'Enter your invite code',
            style: Theme.of(context).textTheme.titleLarge,
          ),
          const SizedBox(height: 8),
          const Text(
            'This owner-issued code enables the coach capability on your own account. '
            'It is single-use and expires. Entering it does not assign you to a coach.',
          ),
          const SizedBox(height: 16),
          TextField(
            controller: _token,
            autocorrect: false,
            enableSuggestions: false,
            decoration: const InputDecoration(
              labelText: 'Invite code',
              border: OutlineInputBorder(),
            ),
          ),
          if (_error != null) ...<Widget>[
            const SizedBox(height: 12),
            Text(
              _error!,
              style: TextStyle(color: Theme.of(context).colorScheme.error),
            ),
          ],
          const SizedBox(height: 20),
          FilledButton(
            onPressed: _submitting ? null : _submit,
            child: _submitting
                ? const SizedBox(
                    height: 20,
                    width: 20,
                    child: CircularProgressIndicator(strokeWidth: 2),
                  )
                : const Text('Enable coaching'),
          ),
        ],
      ),
    );
  }
}

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api_client.dart';
import '../../../providers.dart';

/// ADR 007 gate: a recovery email is mandatory before dashboard or onboarding.
class RecoveryEmailScreen extends ConsumerStatefulWidget {
  const RecoveryEmailScreen({super.key});

  @override
  ConsumerState<RecoveryEmailScreen> createState() =>
      _RecoveryEmailScreenState();
}

class _RecoveryEmailScreenState extends ConsumerState<RecoveryEmailScreen> {
  final TextEditingController _email = TextEditingController();
  bool _busy = false;
  String? _error;

  @override
  void dispose() {
    _email.dispose();
    super.dispose();
  }

  Future<void> _save() async {
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      await ref
          .read(authControllerProvider.notifier)
          .setRecoveryEmail(_email.text.trim());
      // On success the router releases the gate; this screen is disposed.
    } on ApiException catch (error) {
      if (mounted) {
        setState(() {
          _error = error.message;
          _busy = false;
        });
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Recovery email')),
      body: SafeArea(
        child: SingleChildScrollView(
          padding: const EdgeInsets.all(24),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: <Widget>[
              const Text(
                'Add a recovery email so you can reset your password if you lose it. '
                'It is kept separately from your training data.',
              ),
              const SizedBox(height: 16),
              TextField(
                controller: _email,
                keyboardType: TextInputType.emailAddress,
                onSubmitted: (_) => _busy ? null : _save(),
                decoration: const InputDecoration(labelText: 'Email'),
              ),
              const SizedBox(height: 16),
              if (_error != null)
                Padding(
                  padding: const EdgeInsets.only(bottom: 12),
                  child: Text(
                    _error!,
                    style:
                        TextStyle(color: Theme.of(context).colorScheme.error),
                  ),
                ),
              FilledButton(
                onPressed: _busy ? null : _save,
                child: _busy
                    ? const SizedBox(
                        height: 20,
                        width: 20,
                        child: CircularProgressIndicator(strokeWidth: 2),
                      )
                    : const Text('Save email'),
              ),
              TextButton(
                onPressed: _busy
                    ? null
                    : () => ref.read(authControllerProvider.notifier).logout(),
                child: const Text('Log out'),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

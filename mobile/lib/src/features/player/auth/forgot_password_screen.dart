import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../../core/api_client.dart';
import '../../../core/connectivity_message.dart';
import '../../../providers.dart';
import '../../../router.dart';

/// Logged-out entry point: submit an email and always see the same confirmation
/// (anti-enumeration), whether or not the email is linked (ADR 007/037).
class ForgotPasswordScreen extends ConsumerStatefulWidget {
  const ForgotPasswordScreen({super.key});

  @override
  ConsumerState<ForgotPasswordScreen> createState() =>
      _ForgotPasswordScreenState();
}

class _ForgotPasswordScreenState extends ConsumerState<ForgotPasswordScreen> {
  final TextEditingController _email = TextEditingController();
  bool _busy = false;
  String? _error;
  String? _confirmation;

  @override
  void dispose() {
    _email.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    setState(() {
      _busy = true;
      _error = null;
      _confirmation = null;
    });
    try {
      final String message = await ref
          .read(authControllerProvider.notifier)
          .requestPasswordReset(_email.text.trim());
      if (mounted) {
        setState(() => _confirmation = message);
      }
    } on ApiException catch (error) {
      if (mounted) {
        setState(() => _error = mutationFailureMessage(error));
      }
    } finally {
      if (mounted) {
        setState(() => _busy = false);
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Forgot password')),
      body: SafeArea(
        child: SingleChildScrollView(
          padding: const EdgeInsets.all(24),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: <Widget>[
              const Text(
                'Enter your recovery email and we will send a reset link. '
                'Open it on this device to choose a new password.',
              ),
              const SizedBox(height: 16),
              TextField(
                controller: _email,
                keyboardType: TextInputType.emailAddress,
                onSubmitted: (_) => _busy ? null : _submit(),
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
              if (_confirmation != null)
                Padding(
                  padding: const EdgeInsets.only(bottom: 12),
                  child: Text(_confirmation!),
                ),
              FilledButton(
                onPressed: _busy ? null : _submit,
                child: _busy
                    ? const SizedBox(
                        height: 20,
                        width: 20,
                        child: CircularProgressIndicator(strokeWidth: 2),
                      )
                    : const Text('Send reset link'),
              ),
              TextButton(
                onPressed: _busy ? null : () => context.go(loginPath),
                child: const Text('Back to log in'),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api_client.dart';
import '../../../core/models.dart';
import '../../../providers.dart';

class OnboardingScreen extends ConsumerStatefulWidget {
  const OnboardingScreen({super.key});

  @override
  ConsumerState<OnboardingScreen> createState() => _OnboardingScreenState();
}

class _OnboardingScreenState extends ConsumerState<OnboardingScreen> {
  final TextEditingController _input = TextEditingController();
  final List<String> _messages = <String>[];
  bool _consented = false;
  bool _loading = false;
  bool _busy = false;
  bool _isComplete = false;
  OnboardingCompletion? _completion;
  String? _error;

  @override
  void dispose() {
    _input.dispose();
    super.dispose();
  }

  /// ADR 016: host processing is disclosed before any onboarding text is sent.
  void _acceptDisclosure() {
    setState(() => _consented = true);
    _start();
  }

  Future<void> _start() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final OnboardingState state =
          await ref.read(apiClientProvider).startOnboarding();
      if (mounted) {
        setState(() {
          _messages
            ..clear()
            ..addAll(state.messages);
          _isComplete = state.isComplete;
          _loading = false;
        });
      }
    } on ApiException catch (error) {
      if (mounted) {
        setState(() {
          _error = error.message;
          _loading = false;
        });
      }
    }
  }

  Future<void> _send() async {
    final String text = _input.text.trim();
    if (text.isEmpty) {
      return;
    }
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      final OnboardingState state =
          await ref.read(apiClientProvider).submitOnboardingStep(content: text);
      if (mounted) {
        setState(() {
          _messages
            ..add('You: $text')
            ..addAll(state.messages);
          _isComplete = state.isComplete;
          _busy = false;
          _input.clear();
        });
      }
    } on ApiException catch (error) {
      if (mounted) {
        setState(() {
          _error = error.message;
          _busy = false;
        });
      }
    }
  }

  Future<void> _complete() async {
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      final OnboardingCompletion completion =
          await ref.read(apiClientProvider).completeOnboarding();
      if (mounted) {
        setState(() {
          _completion = completion;
          _busy = false;
        });
      }
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
    if (!_consented) {
      return _DisclosureView(onContinue: _acceptDisclosure);
    }
    if (_loading) {
      return const Scaffold(body: Center(child: CircularProgressIndicator()));
    }

    final OnboardingCompletion? completion = _completion;
    if (completion != null) {
      return Scaffold(
        appBar: AppBar(title: const Text('Your program is ready')),
        body: Center(
          child: Padding(
            padding: const EdgeInsets.all(24),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: <Widget>[
                Text(
                  completion.programName,
                  style: Theme.of(context).textTheme.headlineSmall,
                  textAlign: TextAlign.center,
                ),
                const SizedBox(height: 8),
                Text('${completion.weeklyFrequency} training days per week'),
                const SizedBox(height: 24),
                FilledButton(
                  onPressed: () =>
                      ref.read(authControllerProvider.notifier).markOnboarded(),
                  child: const Text('Continue'),
                ),
              ],
            ),
          ),
        ),
      );
    }

    return Scaffold(
      appBar: AppBar(title: const Text('Set up your training')),
      body: SafeArea(
        child: Column(
          children: <Widget>[
            Expanded(
              child: ListView.builder(
                padding: const EdgeInsets.all(16),
                itemCount: _messages.length,
                itemBuilder: (BuildContext context, int index) {
                  final bool isUser = _messages[index].startsWith('You: ');
                  return Align(
                    alignment:
                        isUser ? Alignment.centerRight : Alignment.centerLeft,
                    child: Container(
                      margin: const EdgeInsets.symmetric(vertical: 4),
                      padding: const EdgeInsets.all(12),
                      constraints: const BoxConstraints(maxWidth: 300),
                      decoration: BoxDecoration(
                        color: isUser
                            ? Theme.of(context).colorScheme.primaryContainer
                            : Theme.of(context)
                                .colorScheme
                                .surfaceContainerHighest,
                        borderRadius: BorderRadius.circular(12),
                      ),
                      child: Text(_messages[index]),
                    ),
                  );
                },
              ),
            ),
            if (_error != null)
              Padding(
                padding: const EdgeInsets.symmetric(horizontal: 16),
                child: Text(
                  _error!,
                  style: TextStyle(color: Theme.of(context).colorScheme.error),
                ),
              ),
            Padding(
              padding: const EdgeInsets.all(16),
              child: _isComplete
                  ? FilledButton(
                      onPressed: _busy ? null : _complete,
                      child: const Text('Build my program'),
                    )
                  : Row(
                      children: <Widget>[
                        Expanded(
                          child: TextField(
                            controller: _input,
                            onSubmitted: (_) => _busy ? null : _send(),
                            decoration: const InputDecoration(
                              hintText: 'Type your answer',
                            ),
                          ),
                        ),
                        const SizedBox(width: 8),
                        IconButton.filled(
                          onPressed: _busy ? null : _send,
                          icon: const Icon(Icons.send),
                        ),
                      ],
                    ),
            ),
          ],
        ),
      ),
    );
  }
}

/// ADR 016 disclosure shown before any onboarding text reaches the service.
class _DisclosureView extends StatelessWidget {
  const _DisclosureView({required this.onContinue});

  final VoidCallback onContinue;

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Before you start')),
      body: SafeArea(
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: <Widget>[
              Text('Hosted AI processing',
                  style: Theme.of(context).textTheme.titleLarge),
              const SizedBox(height: 12),
              const Text(
                'Onboarding is powered by a hosted AI provider. The answers you type and '
                'the training context needed to respond are sent for processing. '
                'Free text you write may contain personal information, so avoid sharing '
                'anything you do not want processed.',
              ),
              const Spacer(),
              FilledButton(
                onPressed: onContinue,
                child: const Text('Continue'),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

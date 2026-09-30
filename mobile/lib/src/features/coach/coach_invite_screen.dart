import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/api_client.dart';
import '../../core/theme/mayos_spacing.dart';
import '../../core/theme/mayos_theme.dart';
import '../../core/ui/mayos_button.dart';
import '../../core/ui/mayos_scaffold.dart';
import '../../core/ui/mayos_text_field.dart';
import '../../providers.dart';
import '../../router.dart';

/// Redemption entry for a MAYOS Coach invite.
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
      setState(() => _error = 'Enter your MAYOS coach code.');
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
    final MayosThemeExtension c = MayosTheme.of(context);
    return MayosScaffold(
      title: 'Become a coach',
      showBack: true,
      body: ListView(
        padding: MayosSpacing.screen,
        children: <Widget>[
          Text(
            'Enter your MAYOS coach code',
            style: Theme.of(context).textTheme.titleLarge,
          ),
          const SizedBox(height: MayosSpacing.xs),
          Text(
            'This code comes from MAYOS and enables Coach mode on your own account. '
            'It is single-use and expires. Entering it does not assign you to a coach.',
            style: Theme.of(context)
                .textTheme
                .bodyMedium
                ?.copyWith(color: c.textSecondary),
          ),
          const SizedBox(height: MayosSpacing.md),
          MayosTextField(
            controller: _token,
            autocorrect: false,
            enableSuggestions: false,
            label: 'MAYOS coach code',
          ),
          if (_error != null) ...<Widget>[
            const SizedBox(height: MayosSpacing.sm),
            Text(
              _error!,
              style: Theme.of(context)
                  .textTheme
                  .bodySmall
                  ?.copyWith(color: c.danger),
            ),
          ],
          const SizedBox(height: MayosSpacing.lg),
          MayosButton(
            label: 'Enable coaching',
            loading: _submitting,
            onPressed: _submitting ? null : _submit,
          ),
        ],
      ),
    );
  }
}

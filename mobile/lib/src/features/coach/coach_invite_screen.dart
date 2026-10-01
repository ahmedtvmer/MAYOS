import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';

import '../../core/theme/mayos_spacing.dart';
import '../../core/ui/mayos_scaffold.dart';
import '../player/onboarding/coach_code_form.dart';
import '../../router.dart';

/// Redemption entry for a MAYOS Coach invite.
///
/// The code is account-bound and single-use; a successful redemption refreshes
/// the registry capabilities, which unlocks Coach mode.
class CoachInviteScreen extends StatelessWidget {
  const CoachInviteScreen({super.key});

  @override
  Widget build(BuildContext context) => MayosScaffold(
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
            CoachCodeForm(
              description:
                  'This code comes from MAYOS and enables Coach mode on your own account. '
                  'It is single-use and expires. Entering it does not assign you to a coach.',
              fieldKey: const Key('settings_coach_code'),
              onRedeemed: () {
                ScaffoldMessenger.of(context).showSnackBar(
                  const SnackBar(content: Text('Coach capability enabled.')),
                );
                context.go(coachPath);
              },
            ),
          ],
        ),
      );
}

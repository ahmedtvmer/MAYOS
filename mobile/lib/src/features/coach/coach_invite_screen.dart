import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';

import '../../core/display_language/feature_copy_context.dart';
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
        title: coachCopyOf(context).becomeCoach,
        showBack: true,
        body: ListView(
          padding: MayosSpacing.screen,
          children: <Widget>[
            Text(
              coachCopyOf(context).enterCoachCode,
              style: Theme.of(context).textTheme.titleLarge,
            ),
            const SizedBox(height: MayosSpacing.xs),
            CoachCodeForm(
              description: coachCopyOf(context).coachCodeLead,
              fieldKey: const Key('settings_coach_code'),
              onRedeemed: () {
                ScaffoldMessenger.of(context).showSnackBar(
                  SnackBar(content: Text(coachCopyOf(context).coachEnabled)),
                );
                context.go(coachPath);
              },
            ),
          ],
        ),
      );
}

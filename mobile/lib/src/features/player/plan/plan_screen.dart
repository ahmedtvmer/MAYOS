import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/display_language/copy_context.dart';
import '../../../core/models.dart';
import '../../../core/theme/mayos_spacing.dart';
import '../../../core/theme/mayos_theme.dart';
import '../../../core/theme/mayos_typography.dart';
import '../../../core/ui/mayos_card.dart';
import '../../../core/ui/mayos_section_header.dart';
import '../../../providers.dart';

/// Shows the account's independent Lifter and Coach plan states served by the
/// API. Both Android and the shared web client render this same screen.
class PlanScreen extends ConsumerWidget {
  const PlanScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final Account? account = ref.watch(authControllerProvider).session?.account;
    if (account == null) {
      return const SizedBox.shrink();
    }
    final copy = displayCopyOf(context);
    final AccountPlans plans = account.plans;
    final List<Widget> cards = <Widget>[
      if (plans.lifter != null)
        _PlanCard(
          capability: copy.playerPlanLabel,
          plan: plans.lifter!,
          benefits: <String>[
            copy.automaticTrainingProgram,
            copy.weeklyVolumeAndRecords,
            copy.coachingAssignmentBenefit,
          ],
        ),
      if (plans.coach != null)
        _PlanCard(
          capability: copy.coachPlanLabel,
          plan: plans.coach!,
          benefits: <String>[
            copy.coachProfileAndInvites,
            copy.activeRosterWithStatus,
            copy.canEndAssignments,
          ],
        ),
    ];
    final MayosThemeExtension c = MayosTheme.of(context);
    if (cards.isEmpty) {
      return Center(
        child: Padding(
          padding: const EdgeInsets.all(MayosSpacing.xl),
          child: Text(
            copy.noPlanAvailable,
            textAlign: TextAlign.center,
            style: MayosTypography.body.copyWith(color: c.textSecondary),
          ),
        ),
      );
    }
    return ListView(
      padding: MayosSpacing.screen,
      children: <Widget>[
        Text(
          copy.independentPlans,
          style: MayosTypography.bodySecondary.copyWith(color: c.textSecondary),
        ),
        const SizedBox(height: MayosSpacing.md),
        for (final Widget card in cards) ...<Widget>[
          card,
          const SizedBox(height: MayosSpacing.md),
        ],
      ],
    );
  }
}

class _PlanCard extends StatelessWidget {
  const _PlanCard({
    required this.capability,
    required this.plan,
    required this.benefits,
  });

  final String capability;
  final PlanState plan;
  final List<String> benefits;

  @override
  Widget build(BuildContext context) {
    final MayosThemeExtension c = MayosTheme.of(context);
    return MayosCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          MayosSectionHeader(
            title: '$capability ${plan.label}',
            subtitle:
                plan.isFree ? displayCopyOf(context).ongoingPlanNotTrial : null,
            padding: EdgeInsets.zero,
          ),
          const SizedBox(height: MayosSpacing.sm),
          Text(
            displayCopyOf(context).includedFeatures,
            style: MayosTypography.label.copyWith(color: c.textSecondary),
          ),
          const SizedBox(height: MayosSpacing.xs),
          for (final String benefit in benefits)
            Padding(
              padding: const EdgeInsets.symmetric(vertical: MayosSpacing.xxs),
              child: Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: <Widget>[
                  Icon(Icons.check_circle_outline, size: 20, color: c.accent),
                  const SizedBox(width: MayosSpacing.xs),
                  Expanded(
                    child: Text(
                      benefit,
                      style:
                          MayosTypography.body.copyWith(color: c.textPrimary),
                    ),
                  ),
                ],
              ),
            ),
        ],
      ),
    );
  }
}

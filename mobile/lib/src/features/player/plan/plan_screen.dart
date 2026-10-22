import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/display_language/copy_context.dart';
import '../../../core/display_language/catalog.dart';
import '../../../core/models.dart';
import '../../../core/theme/myos_spacing.dart';
import '../../../core/theme/myos_theme.dart';
import '../../../core/theme/myos_typography.dart';
import '../../../core/ui/myos_card.dart';
import '../../../core/ui/myos_section_header.dart';
import '../../../providers.dart';

enum PlanCapability { lifter, coach }

/// Shows the account's independent Lifter and Coach plan states served by the
/// API. Both Android and the shared web client render this same screen.
class PlanScreen extends ConsumerWidget {
  const PlanScreen({super.key, required this.capability});

  final PlanCapability capability;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final Account? account = ref.watch(authControllerProvider).session?.account;
    if (account == null) {
      return const SizedBox.shrink();
    }
    final copy = displayCopyOf(context);
    final AccountPlans plans = account.plans;
    final MyosThemeExtension c = MyosTheme.of(context);
    final List<Widget> cards = <Widget>[
      if (capability == PlanCapability.lifter && plans.lifter != null)
        _PlanCard(
          capability: copy.playerPlanLabel,
          plan: plans.lifter!,
          allowance: copy.lifterDailyAllowance(
            account.lifterAiAllowance?.requestLimit,
          ),
          resourceDisclosure: account.lifterAiAllowance?.mode == 'launch'
              ? copy.aiResourceSafeguardDisclosure
              : null,
          allowanceState: account.lifterAiAllowance?.mode == 'launch'
              ? (account.lifterAiAllowance!.requestsRemaining == 0
                  ? copy.lifterAllowanceExhausted(
                      account.lifterAiAllowance!.resetAt,
                    )
                  : copy.lifterAllowanceSummary(
                      account.lifterAiAllowance!.requestsRemaining ?? 0,
                      account.lifterAiAllowance!.resetAt,
                    ))
              : null,
          benefits: <String>[
            copy.automaticTrainingProgram,
            copy.weeklyVolumeAndRecords,
            copy.coachingAssignmentBenefit,
          ],
        ),
      if (capability == PlanCapability.coach && plans.coach != null)
        _PlanCard(
          capability: copy.coachPlanLabel,
          plan: plans.coach!,
          allowance: account.coachAiAllowance == null
              ? null
              : copy.coachDailyAllowance(
                  account.coachAiAllowance!.requestLimit,
                ),
          resourceDisclosure: account.coachAiAllowance?.mode == 'launch'
              ? copy.aiResourceSafeguardDisclosure
              : null,
          allowanceState: account.coachAiAllowance?.mode == 'launch'
              ? _coachAllowanceState(copy, account.coachAiAllowance!)
              : null,
          benefits: <String>[
            copy.coachProfileAndInvites,
            copy.activeRosterWithStatus,
            copy.canEndAssignments,
          ],
        ),
    ];
    if (cards.isEmpty) {
      return Center(
        child: Padding(
          padding: const EdgeInsets.all(MyosSpacing.xl),
          child: Text(
            copy.noPlanAvailable,
            textAlign: TextAlign.center,
            style: MyosTypography.of(context).body.copyWith(color: c.textSecondary),
          ),
        ),
      );
    }
    return ListView(
      padding: MyosSpacing.screen,
      children: <Widget>[
        for (final Widget card in cards) ...<Widget>[
          card,
          const SizedBox(height: MyosSpacing.md),
        ],
      ],
    );
  }

  String _coachAllowanceState(MyosCopy copy, AiAllowance allowance) {
    final int remaining = allowance.requestsRemaining ?? 0;
    return switch (allowance.status) {
      'warning' => copy.coachAllowanceWarning(remaining, allowance.resetAt),
      'resource_cutoff' => copy.coachAllowanceCutoff(remaining, allowance.resetAt),
      'requests_exhausted'
          when allowance.resourceUsed >= allowance.resourceLimit =>
        copy.coachAllowanceCutoff(remaining, allowance.resetAt),
      'requests_exhausted' => copy.coachAllowanceExhausted(allowance.resetAt),
      _ => copy.coachAllowanceSummary(remaining, allowance.resetAt),
    };
  }
}

class _PlanCard extends StatelessWidget {
  const _PlanCard({
    required this.capability,
    required this.plan,
    required this.benefits,
    this.allowance,
    this.resourceDisclosure,
    this.allowanceState,
  });

  final String capability;
  final PlanState plan;
  final List<String> benefits;
  final String? allowance;
  final String? resourceDisclosure;
  final String? allowanceState;

  @override
  Widget build(BuildContext context) {
    final MyosThemeExtension c = MyosTheme.of(context);
    return MyosCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          MyosSectionHeader(
            title: '$capability ${plan.label}',
            subtitle:
                plan.isFree ? displayCopyOf(context).ongoingPlanNotTrial : null,
            padding: EdgeInsets.zero,
          ),
          const SizedBox(height: MyosSpacing.sm),
          Text(
            displayCopyOf(context).includedFeatures,
            style: MyosTypography.of(context).label.copyWith(color: c.textSecondary),
          ),
          const SizedBox(height: MyosSpacing.xs),
          for (final String benefit in benefits)
            Padding(
              padding: const EdgeInsets.symmetric(vertical: MyosSpacing.xxs),
              child: Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: <Widget>[
                  Icon(Icons.check_circle_outline, size: 20, color: c.accent),
                  const SizedBox(width: MyosSpacing.xs),
                  Expanded(
                    child: Text(
                      benefit,
                      style:
                          MyosTypography.of(context).body.copyWith(color: c.textPrimary),
                    ),
                  ),
                ],
              ),
            ),
          if (allowance != null) ...<Widget>[
            const SizedBox(height: MyosSpacing.sm),
            Text(
              allowance!,
              style: MyosTypography.of(context).body.copyWith(color: c.textPrimary),
            ),
            if (resourceDisclosure != null) ...<Widget>[
              const SizedBox(height: MyosSpacing.xs),
              Text(
                resourceDisclosure!,
                style: MyosTypography.of(context).caption.copyWith(color: c.textSecondary),
              ),
            ],
            if (allowanceState != null) ...<Widget>[
              const SizedBox(height: MyosSpacing.xs),
              Text(
                allowanceState!,
                style: MyosTypography.of(context).caption.copyWith(color: c.textSecondary),
              ),
            ],
          ],
        ],
      ),
    );
  }
}

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/models.dart';
import '../../../core/theme/mayos_spacing.dart';
import '../../../core/theme/mayos_theme.dart';
import '../../../core/theme/mayos_typography.dart';
import '../../../core/ui/mayos_card.dart';
import '../../../core/ui/mayos_section_header.dart';
import '../../../providers.dart';

/// Truthful, currently-implemented core benefits per capability. Deliberately
/// excludes not-yet-working features (workout logging, complete history,
/// alerts, coach publishing) and any paid/Pro claim, so the display never
/// over-promises what the app can do today.
const List<String> _lifterFreeBenefits = <String>[
  'Automatic training program',
  'Weekly volume and personal-record dashboard',
  'Coaching assignment with your coach',
];

const List<String> _coachFreeBenefits = <String>[
  'Coach profile and player invites',
  'Active roster with assignment status',
  'End or revoke assignments at any time',
];

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
    final AccountPlans plans = account.plans;
    final List<Widget> cards = <Widget>[
      if (plans.lifter != null)
        _PlanCard(
          capability: 'Lifter',
          plan: plans.lifter!,
          benefits: _lifterFreeBenefits,
        ),
      if (plans.coach != null)
        _PlanCard(
          capability: 'Coach',
          plan: plans.coach!,
          benefits: _coachFreeBenefits,
        ),
    ];
    final MayosThemeExtension c = MayosTheme.of(context);
    if (cards.isEmpty) {
      return Center(
        child: Padding(
          padding: const EdgeInsets.all(MayosSpacing.xl),
          child: Text(
            'No plan is available for this account.',
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
          'Lifter and Coach plans are independent.',
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
            subtitle: plan.isFree ? 'Ongoing plan — not a trial.' : null,
            padding: EdgeInsets.zero,
          ),
          const SizedBox(height: MayosSpacing.sm),
          Text(
            "What's included",
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

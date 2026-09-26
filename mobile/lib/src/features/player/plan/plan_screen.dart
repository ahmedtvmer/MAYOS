import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/models.dart';
import '../../../providers.dart';

/// Truthful, currently-implemented core benefits per capability. Deliberately
/// excludes not-yet-working features (workout logging, complete history,
/// alerts, coach publishing) and any paid/Pro claim, so the display never
/// over-promises what the app can do today.
const List<String> lifterFreeBenefits = <String>[
  'Automatic training program',
  'Weekly volume and personal-record dashboard',
  'Coaching assignment with your coach',
];

const List<String> coachFreeBenefits = <String>[
  'Coach profile and player invite codes',
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
          benefits: lifterFreeBenefits,
        ),
      if (plans.coach != null)
        _PlanCard(
          capability: 'Coach',
          plan: plans.coach!,
          benefits: coachFreeBenefits,
        ),
    ];
    if (cards.isEmpty) {
      return const Center(child: Text('No plan is available for this account.'));
    }
    return ListView(
      padding: const EdgeInsets.all(16),
      children: <Widget>[
        Center(
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 640),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: <Widget>[
                Text(
                  'Lifter and Coach plans are independent.',
                  style: Theme.of(context).textTheme.bodyMedium,
                ),
                const SizedBox(height: 16),
                for (final Widget card in cards) ...<Widget>[
                  card,
                  const SizedBox(height: 16),
                ],
              ],
            ),
          ),
        ),
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
    final TextTheme textTheme = Theme.of(context).textTheme;
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: <Widget>[
            Text('$capability ${plan.label}', style: textTheme.titleLarge),
            if (plan.isFree) ...<Widget>[
              const SizedBox(height: 4),
              Text(
                'Ongoing plan — not a trial.',
                style: textTheme.bodySmall,
              ),
            ],
            const SizedBox(height: 12),
            Text("What's included", style: textTheme.titleSmall),
            const SizedBox(height: 8),
            for (final String benefit in benefits)
              Padding(
                padding: const EdgeInsets.symmetric(vertical: 4),
                child: Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: <Widget>[
                    const Icon(Icons.check_circle_outline, size: 20),
                    const SizedBox(width: 8),
                    Expanded(child: Text(benefit)),
                  ],
                ),
              ),
          ],
        ),
      ),
    );
  }
}

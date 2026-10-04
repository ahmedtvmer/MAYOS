import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../providers.dart';

/// Shows Coach Pro content only when `/auth/me` grants the signed-in account Pro.
class CoachProGate extends ConsumerWidget {
  const CoachProGate({super.key, required this.child});

  final Widget child;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final bool hasCoachPro =
        ref.watch(authControllerProvider).session?.account.hasCoachPro ?? false;
    return hasCoachPro ? child : const SizedBox.shrink();
  }
}

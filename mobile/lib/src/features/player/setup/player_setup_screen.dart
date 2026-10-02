import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../../core/app_mode.dart';
import '../../../core/display_language/catalog.dart';
import '../../../core/display_language/controller.dart';
import '../../../core/theme/mayos_spacing.dart';
import '../../../core/theme/mayos_theme.dart';
import '../../../core/theme/mayos_typography.dart';
import '../../../core/ui/mayos_app_header.dart';
import '../../../core/ui/mayos_button.dart';
import '../../../core/ui/mayos_scaffold.dart';
import '../../../router.dart';
import '../../shared/mode_switch.dart';

/// Player mode for a coach who has not completed the player intake (#119).
///
/// Player onboarding is deferred for coaches: they reach Coach mode without
/// it, and this screen is what Player mode shows until they start the intake
/// or go back to Coach mode.
class PlayerSetupScreen extends ConsumerWidget {
  const PlayerSetupScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final MayosThemeExtension c = MayosTheme.of(context);
    final MayosCopy copy = MayosCopy(ref.watch(displayLanguageProvider));
    return MayosScaffold(
      header: const MayosAppHeader(
        actions: <Widget>[ModeAvatarButton()],
      ),
      body: Padding(
        padding: MayosSpacing.screen,
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: <Widget>[
            Icon(Icons.fitness_center, size: 40, color: c.accent),
            const SizedBox(height: MayosSpacing.md),
            Text(
              copy.setupOwnTraining,
              textAlign: TextAlign.center,
              style: MayosTypography.pageHeading.copyWith(color: c.textPrimary),
            ),
            const SizedBox(height: MayosSpacing.sm),
            Text(
              copy.setupLead,
              textAlign: TextAlign.center,
              style: MayosTypography.bodySecondary
                  .copyWith(color: c.textSecondary),
            ),
            const SizedBox(height: MayosSpacing.xl),
            MayosButton(
              label: copy.startIntake,
              onPressed: () => context.go(onboardingPath),
            ),
            const SizedBox(height: MayosSpacing.sm),
            MayosButton(
              label: copy.backToCoachMode,
              variant: MayosButtonVariant.tertiary,
              onPressed: () => switchToMode(context, ref, AppMode.coach),
            ),
          ],
        ),
      ),
    );
  }
}

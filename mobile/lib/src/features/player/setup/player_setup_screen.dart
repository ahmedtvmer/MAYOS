import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../../core/app_mode.dart';
import '../../../core/display_language/catalog.dart';
import '../../../core/display_language/controller.dart';
import '../../../core/theme/myos_spacing.dart';
import '../../../core/theme/myos_theme.dart';
import '../../../core/theme/myos_typography.dart';
import '../../../core/ui/myos_app_header.dart';
import '../../../core/ui/myos_button.dart';
import '../../../core/ui/myos_scaffold.dart';
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
    final MyosThemeExtension c = MyosTheme.of(context);
    final MyosCopy copy = MyosCopy(ref.watch(displayLanguageProvider));
    return MyosScaffold(
      header: const MyosAppHeader(
        actions: <Widget>[ModeAvatarButton()],
      ),
      body: Padding(
        padding: MyosSpacing.screen,
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: <Widget>[
            Icon(Icons.fitness_center, size: 40, color: c.accent),
            const SizedBox(height: MyosSpacing.md),
            Text(
              copy.setupOwnTraining,
              textAlign: TextAlign.center,
              style: MyosTypography.of(context).pageHeading.copyWith(color: c.textPrimary),
            ),
            const SizedBox(height: MyosSpacing.sm),
            Text(
              copy.setupLead,
              textAlign: TextAlign.center,
              style: MyosTypography.of(context).bodySecondary
                  .copyWith(color: c.textSecondary),
            ),
            const SizedBox(height: MyosSpacing.xl),
            MyosButton(
              label: copy.startIntake,
              onPressed: () => context.go(onboardingPath),
            ),
            const SizedBox(height: MyosSpacing.sm),
            MyosButton(
              label: copy.backToCoachMode,
              variant: MyosButtonVariant.tertiary,
              onPressed: () => switchToMode(context, ref, AppMode.coach),
            ),
          ],
        ),
      ),
    );
  }
}

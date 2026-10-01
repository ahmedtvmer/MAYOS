import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/config.dart';
import '../../core/models.dart';
import '../../core/privacy_policy.dart';
import '../../core/theme/mayos_spacing.dart';
import '../../core/theme/mayos_theme.dart';
import '../../core/ui/mayos_card.dart';
import '../../core/ui/mayos_scaffold.dart';
import '../../core/ui/mayos_section_header.dart';
import '../../core/ui/mayos_segmented_control.dart';
import '../../core/ui/mayos_settings_tile.dart';
import '../../providers.dart';
import '../../router.dart';
import 'credits_dialog.dart';
import 'logout_confirmation.dart';

/// Settings: appearance, account, coaching, and device entry points.
///
/// Opened from the shell header (never a bottom-bar destination). This is the
/// single home for actions that previously crowded the Home header, so nothing
/// stops being reachable when the bottom bar is reduced to Home + Program.
class SettingsScreen extends ConsumerWidget {
  const SettingsScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final MayosThemeExtension c = MayosTheme.of(context);
    final ThemeMode mode = ref.watch(themeModeControllerProvider);
    final AccountSession? session = ref.watch(authControllerProvider).session;
    final bool isCoach = session?.account.isCoach ?? false;
    final bool hasPlayerProfile =
        session?.account.capabilities.player ?? false;
    final bool offlineDrafts = ref.watch(offlineWorkoutDraftsEnabledProvider);

    return MayosScaffold(
      title: 'Settings',
      showBack: true,
      body: ListView(
        padding: MayosSpacing.screen,
        children: <Widget>[
          const MayosSectionHeader(
            title: 'Appearance',
            subtitle: 'Choose how MAYOS looks. System follows your device.',
          ),
          MayosSegmentedControl<ThemeMode>(
            selected: mode,
            onChanged: (ThemeMode value) =>
                ref.read(themeModeControllerProvider.notifier).setMode(value),
            segments: const <MayosSegment<ThemeMode>>[
              MayosSegment<ThemeMode>(
                value: ThemeMode.system,
                label: 'System',
                icon: Icons.brightness_auto_outlined,
              ),
              MayosSegment<ThemeMode>(
                value: ThemeMode.light,
                label: 'Light',
                icon: Icons.light_mode_outlined,
              ),
              MayosSegment<ThemeMode>(
                value: ThemeMode.dark,
                label: 'Dark',
                icon: Icons.dark_mode_outlined,
              ),
            ],
          ),
          const SizedBox(height: MayosSpacing.xl),
          if (hasPlayerProfile) ...<Widget>[
            const MayosSectionHeader(title: 'Personalization · التخصيص'),
            MayosCard(
              padding: const EdgeInsets.symmetric(
                  horizontal: MayosSpacing.xs, vertical: MayosSpacing.xxs),
              child: MayosSettingsTile(
                key: const Key('personalization_entry'),
                icon: Icons.forum_outlined,
                title: 'Assistant style · أسلوب المساعد',
                onTap: () => context.push(personalizationPath),
              ),
            ),
            const SizedBox(height: MayosSpacing.xl),
          ],
          const MayosSectionHeader(title: 'Account'),
          MayosCard(
            padding: const EdgeInsets.symmetric(
                horizontal: MayosSpacing.xs, vertical: MayosSpacing.xxs),
            child: Column(
              children: <Widget>[
                MayosSettingsTile(
                  icon: Icons.person_outline,
                  title: 'Profile',
                  subtitle: 'Training preferences, schedule, and account',
                  onTap: () => context.push(profilePath),
                ),
                Divider(height: 1, color: c.border),
                MayosSettingsTile(
                  icon: Icons.card_membership_outlined,
                  title: 'Plan',
                  subtitle: 'Lifter and Coach plan states',
                  onTap: () => context.push(planPath),
                ),
              ],
            ),
          ),
          const SizedBox(height: MayosSpacing.xl),
          const MayosSectionHeader(title: 'Coaching'),
          MayosCard(
            padding: const EdgeInsets.symmetric(
                horizontal: MayosSpacing.xs, vertical: MayosSpacing.xxs),
            child: Column(
              children: <Widget>[
                MayosSettingsTile(
                  icon: Icons.badge_outlined,
                  title: 'Coaching assignment',
                  subtitle: 'Your coach and check-ins',
                  onTap: () => context.push(assignmentPath),
                ),
                if (!isCoach) ...<Widget>[
                  Divider(height: 1, color: c.border),
                  MayosSettingsTile(
                    icon: Icons.workspace_premium_outlined,
                    title: 'Enable coaching',
                    subtitle: 'Redeem an owner-issued coach code',
                    onTap: () => context.push(coachInvitePath),
                  ),
                ],
              ],
            ),
          ),
          const SizedBox(height: MayosSpacing.xl),
          const MayosSectionHeader(title: 'Training'),
          MayosCard(
            padding: const EdgeInsets.symmetric(
                horizontal: MayosSpacing.xs, vertical: MayosSpacing.xxs),
            child: Column(
              children: <Widget>[
                MayosSettingsTile(
                  icon: Icons.forum_outlined,
                  title: 'Assistant',
                  subtitle: 'Chat about your training',
                  onTap: () => context.push(chatPath),
                ),
                if (offlineDrafts) ...<Widget>[
                  Divider(height: 1, color: c.border),
                  MayosSettingsTile(
                    icon: Icons.cloud_upload_outlined,
                    title: 'Workout drafts',
                    subtitle: 'Saved on this device, syncing when online',
                    onTap: () => context.push(workoutsPath),
                  ),
                ],
              ],
            ),
          ),
          const SizedBox(height: MayosSpacing.xl),
          const MayosSectionHeader(title: 'About'),
          MayosCard(
            padding: const EdgeInsets.symmetric(
                horizontal: MayosSpacing.xs, vertical: MayosSpacing.xxs),
            child: Column(
              children: <Widget>[
                MayosSettingsTile(
                  icon: Icons.privacy_tip_outlined,
                  title: 'Privacy policy',
                  subtitle: 'What MAYOS collects, who can see it, and deletion',
                  onTap: () => openPrivacyPolicy(context, ref),
                ),
                Divider(height: 1, color: c.border),
                MayosSettingsTile(
                  icon: Icons.image_outlined,
                  title: 'Credits',
                  subtitle: gymVisualCreditShort,
                  onTap: () => showMediaCredits(context, ref),
                ),
              ],
            ),
          ),
          const SizedBox(height: MayosSpacing.xl),
          MayosCard(
            padding: const EdgeInsets.symmetric(
                horizontal: MayosSpacing.xs, vertical: MayosSpacing.xxs),
            child: MayosSettingsTile(
              icon: Icons.logout,
              title: 'Log out',
              destructive: true,
              onTap: () => confirmLogout(context, ref),
            ),
          ),
          const SizedBox(height: MayosSpacing.xxl),
        ],
      ),
    );
  }
}

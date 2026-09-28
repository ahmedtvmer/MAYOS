import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

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
import '../player/workout/draft_sync_service.dart';

enum _LogoutChoice { keep, discard }

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
                Divider(height: 1, color: c.border),
                if (isCoach) ...<Widget>[
                  MayosSettingsTile(
                    icon: Icons.groups_outlined,
                    title: 'Coach profile',
                    subtitle: 'How players see you',
                    onTap: () => context.push(coachPath),
                  ),
                  Divider(height: 1, color: c.border),
                  MayosSettingsTile(
                    icon: Icons.handshake_outlined,
                    title: 'Roster & invites',
                    subtitle: 'Assignments and player invite codes',
                    onTap: () => context.push(coachAssignmentsPath),
                  ),
                  Divider(height: 1, color: c.border),
                  MayosSettingsTile(
                    icon: Icons.notification_important_outlined,
                    title: 'Alert center',
                    subtitle: 'Players needing attention',
                    onTap: () => context.push(coachAlertsPath),
                  ),
                ] else
                  MayosSettingsTile(
                    icon: Icons.workspace_premium_outlined,
                    title: 'Redeem coach invite',
                    subtitle: 'Connect to a coach',
                    onTap: () => context.push(coachInvitePath),
                  ),
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
            child: MayosSettingsTile(
              icon: Icons.privacy_tip_outlined,
              title: 'Privacy policy',
              subtitle: 'What MAYOS collects, who can see it, and deletion',
              onTap: () => openPrivacyPolicy(context, ref),
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
              onTap: () => _confirmLogout(context, ref),
            ),
          ),
          const SizedBox(height: MayosSpacing.xxl),
        ],
      ),
    );
  }

  /// Logout must never silently destroy unsynced drafts: warn, and let the
  /// player explicitly keep or discard them (ADR 020/033).
  Future<void> _confirmLogout(BuildContext context, WidgetRef ref) async {
    final String? accountId =
        ref.read(authControllerProvider).session?.account.accountId;
    final DraftSyncService sync = ref.read(draftSyncServiceProvider);
    final int unsynced =
        accountId == null ? 0 : await sync.unsyncedCountFor(accountId);
    if (!context.mounted) return;

    if (unsynced > 0) {
      final _LogoutChoice? choice = await showDialog<_LogoutChoice>(
        context: context,
        builder: (BuildContext context) => AlertDialog(
          title: const Text('Unsynced workouts'),
          content: Text(
            'You have $unsynced unsynced workout '
            '${unsynced == 1 ? 'draft' : 'drafts'}. '
            'They stay on this device until they sync; logging out will not delete them.',
          ),
          actions: <Widget>[
            TextButton(
              onPressed: () => Navigator.of(context).pop(),
              child: const Text('Cancel'),
            ),
            TextButton(
              onPressed: () => Navigator.of(context).pop(_LogoutChoice.discard),
              child: const Text('Discard drafts and log out'),
            ),
            FilledButton(
              onPressed: () => Navigator.of(context).pop(_LogoutChoice.keep),
              child: const Text('Keep drafts and log out'),
            ),
          ],
        ),
      );
      if (choice == null) {
        return;
      }
      if (choice == _LogoutChoice.discard && accountId != null) {
        await sync.discardAllForAccount(accountId);
      }
    }
    await ref.read(authControllerProvider.notifier).logout();
  }
}

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/api_client.dart';
import '../../core/app_mode.dart';
import '../../core/config.dart';
import '../../core/display_language/assignment_copy.dart';
import '../../core/display_language/catalog.dart';
import '../../core/display_language/controller.dart';
import '../../core/display_language/settings_copy.dart';
import '../../core/display_language/choices.dart';
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
import 'account_security_section.dart';
import 'credits_dialog.dart';
import 'logout_confirmation.dart';

/// Settings: appearance, account, coaching, and device entry points.
///
/// Opened from the shell header (never a bottom-bar destination). This is the
/// single home for actions that previously crowded the Home header, so nothing
/// stops being reachable when the bottom bar is reduced to Home + Program.
class SettingsScreen extends ConsumerStatefulWidget {
  const SettingsScreen({super.key});

  @override
  ConsumerState<SettingsScreen> createState() => _SettingsScreenState();
}

class _SettingsScreenState extends ConsumerState<SettingsScreen> {
  int _selectorRevision = 0;
  bool _savingLanguage = false;
  bool _savingAnalytics = false;

  Future<void> _openRecoveryEmail() async {
    await context.push(recoveryEmailSettingsPath);
    if (mounted) ref.invalidate(recoveryEmailDetailsProvider);
  }

  @override
  Widget build(BuildContext context) {
    final MayosThemeExtension c = MayosTheme.of(context);
    final ThemeMode mode = ref.watch(themeModeControllerProvider);
    final AccountSession? session = ref.watch(authControllerProvider).session;
    final bool isCoach = session?.account.isCoach ?? false;
    final bool hasPlayerProfile = session?.account.capabilities.player ?? false;
    final bool coachMode = isCoach &&
        ref.watch(appModeControllerProvider).mode == AppMode.coach;
    final bool offlineDrafts = ref.watch(offlineWorkoutDraftsEnabledProvider);
    final String language = ref.watch(displayLanguageProvider);
    final AsyncValue<RecoveryEmailDetails> recoveryEmail =
        ref.watch(recoveryEmailDetailsProvider);
    final MayosCopy copy = MayosCopy(language);
    final SettingsCopy ui = SettingsCopy(language);
    final AssignmentCopy assignmentCopy = AssignmentCopy(language);

    return MayosScaffold(
      title: copy.settings,
      showBack: true,
      body: ListView(
        key: const Key('settings_section_list'),
        padding: MayosSpacing.screen,
        children: <Widget>[
          MayosSectionHeader(
            title: ui.appearance,
            subtitle: ui.appearanceLead,
          ),
          MayosSegmentedControl<ThemeMode>(
            selected: mode,
            onChanged: (ThemeMode value) =>
                ref.read(themeModeControllerProvider.notifier).setMode(value),
            segments: <MayosSegment<ThemeMode>>[
              MayosSegment<ThemeMode>(
                value: ThemeMode.system,
                label: ui.system,
                icon: Icons.brightness_auto_outlined,
              ),
              MayosSegment<ThemeMode>(
                value: ThemeMode.light,
                label: ui.light,
                icon: Icons.light_mode_outlined,
              ),
              MayosSegment<ThemeMode>(
                value: ThemeMode.dark,
                label: ui.dark,
                icon: Icons.dark_mode_outlined,
              ),
            ],
          ),
          const SizedBox(height: MayosSpacing.xl),
          if (coachMode) ...<Widget>[
            MayosCard(
              padding: const EdgeInsets.symmetric(
                  horizontal: MayosSpacing.xs, vertical: MayosSpacing.xxs),
              child: MayosSettingsTile(
                icon: Icons.badge_outlined,
                title: ui.coachProfile,
                subtitle: ui.editCoachProfile,
                onTap: () => context.go(coachProfilePath),
              ),
            ),
            const SizedBox(height: MayosSpacing.xl),
            MayosCard(
              padding: const EdgeInsets.symmetric(
                  horizontal: MayosSpacing.xs, vertical: MayosSpacing.xxs),
              child: MayosSettingsTile(
                icon: Icons.card_membership_outlined,
                title: ui.coachPlan,
                onTap: () => context.push(coachPlanPath),
              ),
            ),
            const SizedBox(height: MayosSpacing.xl),
          ] else ...<Widget>[
            if (hasPlayerProfile) ...<Widget>[
              MayosCard(
                padding: const EdgeInsets.symmetric(
                    horizontal: MayosSpacing.xs, vertical: MayosSpacing.xxs),
                child: MayosSettingsTile(
                  icon: Icons.person_outline,
                  title: ui.trainingProfile,
                  onTap: () => context.push(profilePath),
                ),
              ),
              const SizedBox(height: MayosSpacing.xl),
              MayosCard(
                padding: const EdgeInsets.symmetric(
                    horizontal: MayosSpacing.xs, vertical: MayosSpacing.xxs),
                child: MayosSettingsTile(
                  icon: Icons.card_membership_outlined,
                  title: ui.lifterPlan,
                  onTap: () => context.push(lifterPlanPath),
                ),
              ),
              const SizedBox(height: MayosSpacing.xl),
            ],
            MayosCard(
              padding: const EdgeInsets.symmetric(
                  horizontal: MayosSpacing.xs, vertical: MayosSpacing.xxs),
              child: Column(
                children: <Widget>[
                  MayosSettingsTile(
                    icon: Icons.badge_outlined,
                    title: assignmentCopy.myCoach,
                    onTap: () => context.push(assignmentPath),
                  ),
                  if (!isCoach) ...<Widget>[
                    Divider(height: 1, color: c.border),
                    MayosSettingsTile(
                      icon: Icons.workspace_premium_outlined,
                      title: ui.enableCoaching,
                      subtitle: ui.enableCoachingSubtitle,
                      onTap: () => context.push(coachInvitePath),
                    ),
                  ],
                ],
              ),
            ),
            const SizedBox(height: MayosSpacing.xl),
            if (hasPlayerProfile) ...<Widget>[
              MayosSectionHeader(title: ui.personalization),
              MayosCard(
                padding: const EdgeInsets.symmetric(
                    horizontal: MayosSpacing.xs, vertical: MayosSpacing.xxs),
                child: MayosSettingsTile(
                  key: const Key('personalization_entry'),
                  icon: Icons.forum_outlined,
                  title: ui.assistantStyle,
                  onTap: () => context.push(personalizationPath),
                ),
              ),
              const SizedBox(height: MayosSpacing.xl),
              MayosSectionHeader(title: ui.training),
              MayosCard(
                padding: const EdgeInsets.symmetric(
                    horizontal: MayosSpacing.xs, vertical: MayosSpacing.xxs),
                child: Column(
                  children: <Widget>[
                    MayosSettingsTile(
                      icon: Icons.forum_outlined,
                      title: ui.assistant,
                      subtitle: ui.assistantSubtitle,
                      onTap: () => context.push(chatPath),
                    ),
                    if (offlineDrafts) ...<Widget>[
                      Divider(height: 1, color: c.border),
                      MayosSettingsTile(
                        icon: Icons.cloud_upload_outlined,
                        title: ui.workoutDrafts,
                        subtitle: ui.workoutDraftsSubtitle,
                        onTap: () => context.push(workoutsPath),
                      ),
                    ],
                  ],
                ),
              ),
              const SizedBox(height: MayosSpacing.xl),
            ],
          ],
          if (coachMode) ...<Widget>[
            MayosSectionHeader(title: ui.notifications),
            MayosCard(
              padding: const EdgeInsets.symmetric(
                  horizontal: MayosSpacing.xs, vertical: MayosSpacing.xxs),
              child: MayosSettingsTile(
                icon: Icons.notifications_outlined,
                title: ui.notificationSettings,
                subtitle: ui.coachNotificationsSubtitle,
                onTap: () => context.go(coachAlertsPath),
              ),
            ),
            const SizedBox(height: MayosSpacing.xl),
          ],
          MayosSectionHeader(title: ui.account),
          MayosCard(
            padding: const EdgeInsets.symmetric(
                horizontal: MayosSpacing.xs, vertical: MayosSpacing.xxs),
            child: Column(
              children: <Widget>[
                MayosSettingsTile(
                  icon: Icons.person_outline,
                  title: ui.username,
                  subtitle: session?.account.traineeId,
                  trailing: const SizedBox(width: MayosIconSizes.medium),
                  onTap: null,
                ),
                Divider(height: 1, color: c.border),
                MayosSettingsTile(
                  key: const Key('recovery_email_settings_entry'),
                  icon: Icons.email_outlined,
                  title: ui.recoveryEmail,
                  subtitle: _recoveryEmailSubtitle(ui, recoveryEmail),
                  subtitleTextDirection: recoveryEmail.valueOrNull?.email != null
                      ? TextDirection.ltr
                      : null,
                  trailing: Text(
                    ui.change,
                    style: Theme.of(context)
                        .textTheme
                        .labelLarge
                        ?.copyWith(color: c.accent),
                  ),
                  onTap: _openRecoveryEmail,
                ),
              ],
            ),
          ),
          const SizedBox(height: MayosSpacing.lg),
          if (session != null)
            AccountSecuritySection(
              account: session.account,
              title: ui.linkedSignIn,
              subtitle: ui.linkedSignInSubtitle,
            ),
          const SizedBox(height: MayosSpacing.lg),
          MayosSectionHeader(title: copy.displayLanguage),
          InputDecorator(
            decoration: InputDecoration(
              border: const OutlineInputBorder(),
            ),
            child: Row(
              children: <Widget>[
                Expanded(
                  child: DropdownButtonHideUnderline(
                    child: DropdownButton<String>(
                      key: ValueKey<String>(
                          'account_display_language_$language-$_selectorRevision'),
                      value: language,
                      isExpanded: true,
                      items: displayLanguageMenuItems(copy),
                      onChanged: session == null || _savingLanguage
                          ? null
                          : (value) {
                              if (value != null && value != language) {
                                _saveDisplayLanguage(
                                  value,
                                  confirmedLanguage: language,
                                  accountId: session.account.accountId,
                                );
                              }
                            },
                    ),
                  ),
                ),
                if (_savingLanguage)
                  const Padding(
                    padding: EdgeInsetsDirectional.only(start: MayosSpacing.sm),
                    child: SizedBox(
                      width: MayosIconSizes.medium,
                      height: MayosIconSizes.medium,
                      child: CircularProgressIndicator(strokeWidth: 2),
                    ),
                  ),
              ],
            ),
          ),
          const SizedBox(height: MayosSpacing.xl),
          MayosSectionHeader(title: ui.about),
          MayosCard(
            padding: const EdgeInsets.symmetric(
                horizontal: MayosSpacing.xs, vertical: MayosSpacing.xxs),
            child: Column(
              children: <Widget>[
                MayosSettingsTile(
                  icon: Icons.privacy_tip_outlined,
                  title: ui.privacyPolicy,
                  subtitle: ui.privacySubtitle,
                  onTap: () => openPrivacyPolicy(context, ref),
                ),
                Divider(height: 1, color: c.border),
                MayosSettingsTile(
                  icon: Icons.image_outlined,
                  title: ui.credits,
                  subtitle: gymVisualCreditShort,
                  onTap: () => showMediaCredits(context, ref),
                ),
              ],
            ),
          ),
          const SizedBox(height: MayosSpacing.lg),
          MayosSectionHeader(title: ui.productAnalytics),
          MayosCard(
            padding: const EdgeInsets.symmetric(horizontal: MayosSpacing.xs),
            child: SwitchListTile(
              key: const Key('analytics_preference_switch'),
              contentPadding: EdgeInsets.zero,
              value: session?.account.analyticsAllowed ?? true,
              onChanged: session == null || _savingAnalytics
                  ? null
                  : (bool value) => _saveAnalyticsPreference(
                      value,
                      accountId: session.account.accountId,
                    ),
              title: Text(ui.allowAnalytics),
              subtitle: Text(ui.analyticsDescription),
            ),
          ),
          const SizedBox(height: MayosSpacing.xl),
          MayosCard(
            padding: const EdgeInsets.symmetric(
                horizontal: MayosSpacing.xs, vertical: MayosSpacing.xxs),
            child: MayosSettingsTile(
              icon: Icons.logout,
              title: ui.logOut,
              destructive: true,
              onTap: () => confirmLogout(context, ref),
            ),
          ),
          const SizedBox(height: MayosSpacing.xl),
          const SizedBox(height: MayosSpacing.xxl),
        ],
      ),
    );
  }

  String _recoveryEmailSubtitle(
    SettingsCopy ui,
    AsyncValue<RecoveryEmailDetails> recoveryEmail,
  ) => recoveryEmail.when(
        loading: () => ui.recoveryEmailLoading,
        error: (Object error, StackTrace stack) => ui.recoveryEmailLoadFailed,
        data: (RecoveryEmailDetails details) {
          final String? email = details.email;
          if (email == null || email.isEmpty) return ui.recoveryEmailNotSet;
          final String verification = details.verified
              ? ui.recoveryEmailVerified
              : ui.recoveryEmailNotVerified;
          final String? pending = details.pendingEmail;
          if (pending != null) {
            return '$email · $verification\n${ui.recoveryEmailPendingChange}: $pending';
          }
          return '$email · $verification';
        },
      );

  Future<void> _saveDisplayLanguage(
    String value, {
    required String confirmedLanguage,
    required String accountId,
  }) async {
    setState(() => _savingLanguage = true);
    final authRepository = ref.read(authRepositoryProvider);
    final authController = ref.read(authControllerProvider.notifier);
    final displayLanguageController =
        ref.read(displayLanguageProvider.notifier);
    final ScaffoldMessengerState messenger = ScaffoldMessenger.of(context);
    messenger.hideCurrentSnackBar();
    try {
      await authRepository.updateDisplayLanguage(value);
      final bool stillCurrent =
          authController.confirmDisplayLanguage(accountId, value);
      if (!stillCurrent) {
        // The server accepted the initiating Account's preference, but a
        // logout or account switch means it must not become the active choice.
        displayLanguageController.cacheAccountChoice(accountId, value);
      }
      if (!mounted) return;
      if (stillCurrent) {
        messenger.hideCurrentSnackBar();
        messenger.showSnackBar(
          SnackBar(content: Text(MayosCopy(value).languageSaved)),
        );
      }
    } on ApiException {
      if (!mounted) return;
      final bool stillCurrent = authController.ownsAccount(accountId);
      if (stillCurrent) setState(() => _selectorRevision++);
      if (stillCurrent) {
        messenger.hideCurrentSnackBar();
        messenger.showSnackBar(
          SnackBar(
            content: Text(MayosCopy(confirmedLanguage).languageSaveFailed),
          ),
        );
      }
    } finally {
      if (mounted) setState(() => _savingLanguage = false);
    }
  }

  Future<void> _saveAnalyticsPreference(
    bool value, {
    required String accountId,
  }) async {
    setState(() => _savingAnalytics = true);
    final authController = ref.read(authControllerProvider.notifier);
    final SettingsCopy ui = SettingsCopy(ref.read(displayLanguageProvider));
    final ScaffoldMessengerState messenger = ScaffoldMessenger.of(context);
    messenger.hideCurrentSnackBar();
    try {
      await authController.updateAnalyticsAllowed(accountId, value);
    } on ApiException {
      if (!mounted) return;
      if (authController.ownsAccount(accountId)) {
        messenger.hideCurrentSnackBar();
        messenger.showSnackBar(SnackBar(content: Text(ui.analyticsSaveFailed)));
      }
    } finally {
      if (mounted) setState(() => _savingAnalytics = false);
    }
  }
}

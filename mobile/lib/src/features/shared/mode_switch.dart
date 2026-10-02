import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/app_mode.dart';
import '../../core/display_language/catalog.dart';
import '../../core/display_language/controller.dart';
import '../../core/models.dart';
import '../../core/theme/mayos_spacing.dart';
import '../../core/theme/mayos_theme.dart';
import '../../core/theme/mayos_typography.dart';
import '../../providers.dart';
import '../../router.dart';
import '../settings/logout_confirmation.dart';

/// The header avatar for a coach account: a small **C**/**P** badge shows the
/// current mode at a glance, and tapping opens the mode sheet (#119).
///
/// Non-coach accounts never render it, so they see no badge and no mode rows.
class ModeAvatarButton extends ConsumerWidget {
  const ModeAvatarButton({super.key});

  static const Key badgeKey = Key('mayos.mode.badge');

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final AccountSession? session = ref.watch(authControllerProvider).session;
    if (session == null || !session.account.isCoach) {
      return const SizedBox.shrink();
    }
    final MayosThemeExtension c = MayosTheme.of(context);
    final bool coachMode =
        ref.watch(appModeControllerProvider).mode == AppMode.coach;
    final String username = session.account.traineeId;
    final String initials = username
        .substring(0, username.length < 2 ? username.length : 2)
        .toUpperCase();
    return Padding(
      padding: const EdgeInsetsDirectional.only(end: MayosSpacing.xs),
      child: Semantics(
        button: true,
        label: MayosCopy(ref.watch(displayLanguageProvider))
            .accountMode(coachMode),
        excludeSemantics: true,
        child: InkWell(
          customBorder: const CircleBorder(),
          onTap: () => showModeSheet(context, ref),
          child: SizedBox(
            width: 48,
            height: 48,
            child: Stack(
              alignment: Alignment.center,
              children: <Widget>[
                CircleAvatar(
                  radius: 17,
                  backgroundColor: c.accentSubtle,
                  child: Text(
                    initials,
                    style: MayosTypography.avatarInitials
                        .copyWith(color: c.accent),
                  ),
                ),
                PositionedDirectional(
                  end: 4,
                  bottom: 6,
                  child: Container(
                    key: badgeKey,
                    padding:
                        const EdgeInsets.symmetric(horizontal: 4, vertical: 1),
                    decoration: BoxDecoration(
                      color: coachMode ? c.accent : c.success,
                      borderRadius: MayosRadii.pillRadius,
                      border: Border.all(color: c.canvas, width: 1.5),
                    ),
                    child: Text(
                      coachMode ? 'C' : 'P',
                      style: MayosTypography.modeBadge.copyWith(
                          color: coachMode ? c.onAccent : c.onSuccess),
                    ),
                  ),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

/// Switches the signed-in account to [mode], persists that choice, and
/// navigates to the mode's landing.
///
/// The one path for mode changes: the mode sheet and the player setup screen
/// both go through it, so neither can drift on persistence or capability (#119).
void switchToMode(BuildContext context, WidgetRef ref, AppMode mode) {
  final AccountSession? session = ref.read(authControllerProvider).session;
  if (session == null) {
    return;
  }
  final String currentPath = GoRouterState.of(context).uri.path;
  if (ref.read(appModeControllerProvider).mode == AppMode.coach &&
      currentPath.startsWith('$coachPath/')) {
    ref.read(coachLocationMemoryProvider.notifier).state = CoachLocationMemory(
      accountId: session.account.accountId,
      location: currentPath,
    );
  }
  final CoachLocationMemory? remembered = ref.read(coachLocationMemoryProvider);
  ref.read(appModeControllerProvider.notifier).setMode(
        mode,
        accountId: session.account.accountId,
        isCoach: session.account.isCoach,
      );
  context.go(
    mode == AppMode.coach
        ? remembered?.accountId == session.account.accountId
            ? remembered!.location
            : coachRosterPath
        : (session.onboarded ? homePath : playerSetupPath),
  );
}

/// The account sheet: switch between Player mode and Coach mode, then
/// Settings and Log out. Only coach accounts reach it (#119).
Future<void> showModeSheet(BuildContext context, WidgetRef ref) {
  final MayosCopy copy = MayosCopy(ref.read(displayLanguageProvider));
  final AccountSession? session = ref.read(authControllerProvider).session;
  if (session == null) {
    return Future<void>.value();
  }
  final AppMode current = ref.read(appModeControllerProvider).mode;
  final bool onboarded = session.onboarded;
  final String username = session.account.traineeId;

  return showModalBottomSheet<void>(
    context: context,
    showDragHandle: true,
    isScrollControlled: true,
    builder: (BuildContext sheetContext) {
      final MayosThemeExtension c = MayosTheme.of(sheetContext);
      Widget modeRow(
        AppMode mode,
        IconData icon,
        String title,
        String subtitle,
      ) {
        final bool selected = current == mode;
        return ListTile(
          minTileHeight: 64,
          leading: Icon(icon, color: selected ? c.accent : c.textSecondary),
          title: Text(title, style: MayosTypography.body),
          subtitle: Text(subtitle, style: MayosTypography.caption),
          trailing: selected ? Icon(Icons.check_circle, color: c.accent) : null,
          onTap: () {
            Navigator.of(sheetContext).pop();
            if (selected) {
              return;
            }
            switchToMode(context, ref, mode);
          },
        );
      }

      // The sheet stays usable on a 360dp screen at 1.5x text (#119).
      final Widget content = Column(
        mainAxisSize: MainAxisSize.min,
        children: <Widget>[
          Padding(
            padding: const EdgeInsetsDirectional.fromSTEB(
                MayosSpacing.lg, 0, MayosSpacing.lg, MayosSpacing.sm),
            child: Row(
              children: <Widget>[
                Expanded(
                  child: Text(username, style: MayosTypography.sectionHeading),
                ),
                Text(copy.switchMode, style: MayosTypography.caption),
              ],
            ),
          ),
          modeRow(
            AppMode.player,
            Icons.fitness_center,
            copy.playerMode,
            onboarded ? copy.ownTraining : copy.setupOwnTraining,
          ),
          modeRow(
            AppMode.coach,
            Icons.groups_outlined,
            copy.coachMode,
            copy.rosterAlertsProfile,
          ),
          const Divider(),
          ListTile(
            leading: const Icon(Icons.settings_outlined),
            title: Text(copy.settings),
            onTap: () {
              Navigator.of(sheetContext).pop();
              context.push(settingsPath);
            },
          ),
          ListTile(
            leading: const Icon(Icons.logout),
            title: Text(copy.logOut),
            onTap: () {
              Navigator.of(sheetContext).pop();
              confirmLogout(context, ref);
            },
          ),
        ],
      );
      return SafeArea(
        child: ConstrainedBox(
          constraints: BoxConstraints(
            maxHeight: MediaQuery.sizeOf(sheetContext).height * 0.9,
          ),
          child: SingleChildScrollView(child: content),
        ),
      );
    },
  );
}

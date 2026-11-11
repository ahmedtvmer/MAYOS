import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../../core/ui/mayos_app_header.dart';
import '../../../core/api_client.dart';
import '../../../core/app_mode.dart';
import '../../../core/app_failure.dart';
import '../../../core/connectivity_message.dart';
import '../../../core/display_language/assignment_copy.dart';
import '../../../core/display_language/catalog.dart';
import '../../../core/display_language/controller.dart';
import '../../../core/display_language/copy_context.dart';
import '../../../core/models.dart';
import '../../../core/ui/mayos_bottom_navigation.dart';
import '../../../core/ui/mayos_button.dart';
import '../../../core/ui/mayos_scaffold.dart';
import '../../../providers.dart';
import '../../../router.dart';
import '../../shared/mode_switch.dart';
import '../../shared/install_prompt.dart';
import '../auth/auth_controller.dart';
import '../dashboard/dashboard_tab.dart';
import '../program/program_tab.dart';
import '../nutrition/nutrition_tab.dart';
import '../progress/progress_tab.dart';
import '../workout/active_workout_controller.dart';
import '../workout/active_workout_prompt.dart';
import '../tour/feature_list.dart';
import '../tour/tour_controller.dart';
import '../tour/tour_targets.dart';
import '../tour/whats_new_screen.dart';

/// The player navigation shell.
///
/// Bottom navigation is Home, Program, Nutrition, and Progress (#461); Progress ships only
/// because its Strength and Volume experiences derive from real ledger data.
/// Settings opens from the header; every other working surface (coach
/// profile/invite/assignment, workout drafts, assistant chat, profile, plan,
/// logout) is reached from Settings or the header, never a placeholder
/// destination.
class PlayerShell extends ConsumerStatefulWidget {
  const PlayerShell({super.key});

  @override
  ConsumerState<PlayerShell> createState() => _PlayerShellState();
}

class _PlayerShellState extends ConsumerState<PlayerShell> {
  List<MayosNavItem> _items(MayosCopy copy) => <MayosNavItem>[
        MayosNavItem(
          label: copy.home,
          icon: Icons.home_outlined,
          selectedIcon: Icons.home,
        ),
        MayosNavItem(
          label: copy.program,
          icon: Icons.article_outlined,
          selectedIcon: Icons.article,
        ),
        MayosNavItem(
          label: copy.nutritionTab,
          icon: Icons.restaurant_menu_outlined,
          selectedIcon: Icons.restaurant_menu,
        ),
        MayosNavItem(
          label: copy.progress,
          icon: Icons.insights_outlined,
          selectedIcon: Icons.insights,
        ),
      ];

  /// Set once this shell visit has offered Resume / Discard, so the prompt
  /// appears at most once per opening of the app (#123).
  bool _offeredResume = false;
  int _confirmedDataRevision = 0;
  bool _rosterAiDisclosureChecked = false;
  String? _whatsNewAttemptedAccountId;
  bool _whatsNewRetryReady = false;
  bool _startupNoticesComplete = false;
  String? _tourAttemptedAccountId;
  GoRouter? _observedRouter;

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    final GoRouter router = GoRouter.of(context);
    if (_observedRouter != router) {
      _observedRouter?.routerDelegate.removeListener(_onRouteChanged);
      _observedRouter = router;
      router.routerDelegate.addListener(_onRouteChanged);
    }
  }

  void _onRouteChanged() {
    if (mounted) setState(() {});
  }

  @override
  void initState() {
    super.initState();
    // The stored Active workout may already have been restored before the
    // shell mounted; check once off the first frame, then rely on the listener
    // below for a restore that lands later.
    Future<void>.microtask(() {
      if (mounted) {
        _offerStartupNotices();
      }
    });
  }

  Future<void> _offerStartupNotices() async {
    final Account? account =
        ref.read(authControllerProvider).session?.account;
    final AppModeState mode = ref.read(appModeControllerProvider);
    if (account != null &&
        mode.isResolvedFor(account.accountId) &&
        mode.mode == AppMode.player) {
      unawaited(_retryPendingWhatsNewSeen());
    }
    await _offerRosterAiDisclosure();
    if (mounted) {
      setState(() => _startupNoticesComplete = true);
      _offerResume(ref.read(activeWorkoutControllerProvider));
    }
  }

  Future<void> _retryPendingWhatsNewSeen() async {
    await ref.read(tourControllerProvider.notifier).retryPendingWhatsNewSeen();
    if (mounted) setState(() => _whatsNewRetryReady = true);
  }

  Future<void> _offerRosterAiDisclosure() async {
    if (_rosterAiDisclosureChecked) return;
    try {
      final Assignment? assignment =
          await ref.read(apiClientProvider).myAssignment();
      if (!mounted) return;
      _rosterAiDisclosureChecked = true;
      if (_needsRosterAiDisclosure(assignment)) {
        await _showRosterAiDisclosure();
      }
    } on ApiException {
      _rosterAiDisclosureChecked = true;
      // Assignment details may be temporarily unavailable; the server still
      // excludes this assignment from roster snapshots until acknowledgement.
    }
  }

  void _syncTour({
    required int tabIndex,
    required String routePath,
    required Account? account,
    required ActiveWorkoutState workout,
    required bool streaming,
    required Map<String, TourTargetHandle> targets,
    required TourSession? tour,
    required int version,
    required ProgramFeatureAvailability programAvailability,
  }) {
    final bool homeIsCurrent =
        tabIndex == PlayerShellTab.home.index && routePath == homePath;
    if (!homeIsCurrent) _tourAttemptedAccountId = null;
    if (tour != null) {
      return;
    }
    if (!homeIsCurrent ||
        !_startupNoticesComplete ||
        ref.read(installPromptDialogActiveProvider) ||
        !workout.ready ||
        workout.hasWorkout ||
        streaming) {
      return;
    }
    if (account != null &&
        (account.isCoach ||
            !isTourEligible(account, currentVersion: version))) {
      _scheduleWhatsNewSheet(account, programAvailability);
    }
    final String firstStopId = tourV1StopIds.first;
    final FeatureEntry firstStop = featureList.firstWhere(
      (FeatureEntry entry) => entry.id == firstStopId,
    );
    final TourController controller = ref.read(tourControllerProvider.notifier);
    if (account == null ||
        _tourAttemptedAccountId == account.accountId ||
        (!isTourEligible(account, currentVersion: version) &&
            !controller.hasPendingSeenWriteFor(account.accountId)) ||
        !targets.containsKey(firstStop.target)) {
      return;
    }
    final String accountId = account.accountId;
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!mounted) return;
      final String currentPath =
          GoRouter.of(context).routeInformationProvider.value.uri.path;
      final Account? currentAccount =
          ref.read(authControllerProvider).session?.account;
      final Map<String, TourTargetHandle> currentTargets =
          ref.read(tourTargetRegistryProvider);
      if (ref.read(playerShellTabProvider) != PlayerShellTab.home.index ||
          currentPath != homePath ||
          currentAccount == null ||
          currentAccount.accountId != accountId ||
          (!isTourEligible(currentAccount, currentVersion: version) &&
              !controller.hasPendingSeenWriteFor(accountId)) ||
          !currentTargets.containsKey(firstStop.target)) {
        return;
      }
      final ActiveWorkoutState currentWorkout =
          ref.read(activeWorkoutControllerProvider);
      if (!currentWorkout.ready ||
          currentWorkout.hasWorkout ||
          ref.read(installPromptDialogActiveProvider) ||
          ref.read(playerChatStreamingProvider)) {
        return;
      }
      _tourAttemptedAccountId = account.accountId;
      unawaited(controller.startTour(version));
    });
  }

  void _scheduleWhatsNewSheet(
    Account account,
    ProgramFeatureAvailability programAvailability,
  ) {
    if (!_startupNoticesComplete ||
        !_whatsNewRetryReady ||
        programAvailability.accountId != account.accountId ||
        programAvailability.playerControlsProgram == null ||
        ref.read(tourControllerProvider.notifier)
            .hasShownTourThisSession(account.accountId) ||
        account.whatsNewSeenRelease >= currentFeatureRelease ||
        _whatsNewAttemptedAccountId == account.accountId) {
      return;
    }
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!mounted || _whatsNewAttemptedAccountId == account.accountId) return;
      final ActiveWorkoutState workout = ref.read(activeWorkoutControllerProvider);
      final bool canShow = workout.ready &&
          !workout.hasWorkout &&
          !ref.read(installPromptDialogActiveProvider) &&
          !ref.read(playerChatStreamingProvider) &&
          ref.read(appModeControllerProvider).isResolvedFor(account.accountId) &&
          ref.read(appModeControllerProvider).mode == AppMode.player &&
          !ref.read(tourControllerProvider.notifier)
              .hasShownTourThisSession(account.accountId) &&
          ref.read(tourControllerProvider) == null &&
          GoRouter.of(context).routeInformationProvider.value.uri.path == homePath;
      if (!canShow) return;
      final List<FeatureEntry> entries = ref.read(featureEntriesProvider).where((FeatureEntry entry) =>
          entry.audience == 'lifter' &&
          entry.release > account.whatsNewSeenRelease &&
          entry.release <= currentFeatureRelease &&
          isFeatureAvailableForAccount(entry, account.accountId, programAvailability)).toList();
      if (entries.isEmpty) return;
      _whatsNewAttemptedAccountId = account.accountId;
      _recordWhatsNewOpened(entries);
      unawaited(_showWhatsNewSheet(entries));
    });
  }

  void _recordWhatsNewOpened(List<FeatureEntry> entries) {
    final Set<int> releases = entries.map((FeatureEntry entry) => entry.release).toSet();
    ref.read(analyticsClientProvider).whatsNewOpened(
      releaseCount: releases.length,
      highestRelease: releases.reduce((int a, int b) => a > b ? a : b),
      source: 'sheet',
    );
  }

  Future<void> _showWhatsNewSheet(List<FeatureEntry> entries) async {
    final String language = ref.read(displayLanguageProvider);
    final MayosCopy copy = MayosCopy(language);
    ref.read(discoverySheetActiveProvider.notifier).state = true;
    String? selectedFeature;
    try {
      selectedFeature = await showModalBottomSheet<String>(
        context: context,
        isScrollControlled: true,
        showDragHandle: true,
        builder: (BuildContext sheetContext) => SafeArea(
          child: Padding(
            padding: const EdgeInsets.all(20),
            child: SizedBox(
              height: MediaQuery.sizeOf(sheetContext).height * 0.78,
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: <Widget>[
                  Row(
                    children: <Widget>[
                      Expanded(
                        child: Text(copy.whatsNewTitle,
                            style: Theme.of(context).textTheme.headlineSmall),
                      ),
                      IconButton(
                        tooltip: copy.close,
                        constraints: const BoxConstraints.tightFor(
                          width: 44,
                          height: 44,
                        ),
                        onPressed: () => Navigator.pop(sheetContext),
                        icon: const Icon(Icons.close),
                      ),
                    ],
                  ),
                  Text(copy.whatsNewSinceLastVisit),
                  const SizedBox(height: 12),
                  Expanded(
                    child: ListView(
                      padding: EdgeInsets.zero,
                      children: <Widget>[
                        for (final FeatureEntry entry in entries)
                          WhatsNewFeatureRow(
                            entry: entry,
                            copy: copy,
                            onShowMe: () =>
                                _showFeatureFromWhatsNew(sheetContext, entry),
                          ),
                      ],
                    ),
                  ),
                  SizedBox(
                    width: double.infinity,
                    child: FilledButton(
                      onPressed: () => Navigator.pop(sheetContext),
                      child: Text(copy.gotIt),
                    ),
                  ),
                ],
              ),
            ),
          ),
        ),
      );
    } finally {
      if (selectedFeature == null) {
        ref.read(discoverySheetActiveProvider.notifier).state = false;
      }
    }
    unawaited(_markWhatsNewSeen());
    if (selectedFeature != null) {
      try {
        await ref
            .read(tourControllerProvider.notifier)
            .showMe(selectedFeature, source: 'whats_new');
      } finally {
        ref.read(discoverySheetActiveProvider.notifier).state = false;
      }
    }
  }

  void _showFeatureFromWhatsNew(BuildContext sheetContext, FeatureEntry entry) {
    Navigator.pop(sheetContext, entry.id);
  }

  Future<void> _markWhatsNewSeen() async {
    try {
      await ref.read(tourControllerProvider.notifier).markWhatsNewSeen(currentFeatureRelease);
    } on ApiException {
      // The next authenticated account refresh will offer the release again.
    }
  }

  bool _needsRosterAiDisclosure(Assignment? assignment) =>
      assignment != null &&
      (assignment.rosterAiDisclosureVersion != rosterAiDisclosureVersion ||
          assignment.rosterAiDisclosedAt == null);

  Future<void> _showRosterAiDisclosure() => showDialog<void>(
        context: context,
        barrierDismissible: false,
        builder: (BuildContext dialogContext) => PopScope(
          canPop: false,
          child: _RosterAiDisclosureDialog(
            copy: AssignmentCopy(ref.read(displayLanguageProvider)),
            onAcknowledge: () => ref
                .read(apiClientProvider)
                .acknowledgeRosterAiDisclosure(),
          ),
        ),
      );

  /// Offers Resume / Discard when this account restored an Active workout
  /// from device storage; a workout the player just started never re-triggers
  /// the offer. Web resumes its browser-stored workout too.
  void _offerResume(ActiveWorkoutState active) {
    if (!_startupNoticesComplete ||
        _offeredResume ||
        !active.ready ||
        !active.restoredFromDevice ||
        active.workout == null) {
      return;
    }
    _offeredResume = true;
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!mounted) {
        return;
      }
      unawaited(offerActiveWorkoutOnOpen(context, ref));
    });
  }

  @override
  Widget build(BuildContext context) {
    ref.listen<AuthState>(authControllerProvider, (previous, next) {
      if (previous?.isOffline == true && next.isAuthenticated && !next.isOffline) {
        // Recreate the read views once after confirmation, including the nested
        // Nutrition day. Active workouts remain in their account-scoped provider.
        setState(() => _confirmedDataRevision++);
      }
    });
    ref.listen<ActiveWorkoutState>(
      activeWorkoutControllerProvider,
      (_, ActiveWorkoutState next) => _offerResume(next),
    );
    final Account? account =
        ref.watch(authControllerProvider).session?.account;
    // The router redirects on the next frame. Do not recreate the keyed tabs
    // for a null account and start fresh reads after session cleanup.
    if (account == null) return const SizedBox.shrink();
    final int index = ref.watch(playerShellTabProvider);
    final bool isCoach = account.isCoach;
    final MayosCopy copy = MayosCopy(ref.watch(displayLanguageProvider));
    final String settingsLabel = copy.settings;
    final ActiveWorkoutState workout =
        ref.watch(activeWorkoutControllerProvider);
    final bool streaming = ref.watch(playerChatStreamingProvider);
    ref.watch(installPromptDialogActiveProvider);
    final TourSession? tour = ref.watch(tourControllerProvider);
    final Map<String, TourTargetHandle> targets =
        ref.watch(tourTargetRegistryProvider);
    final ProgramFeatureAvailability programAvailability =
        ref.watch(programFeatureAvailabilityProvider);
    final int tourVersion = ref.watch(tourCurrentVersionProvider);
    final String currentRoutePath =
        GoRouter.of(context).routeInformationProvider.value.uri.path;
    _syncTour(
      tabIndex: index,
      routePath: currentRoutePath,
      account: account,
      workout: workout,
      streaming: streaming,
      targets: targets,
      tour: tour,
      version: tourVersion,
      programAvailability: programAvailability,
    );
    return MayosScaffold(
      header: TourTarget(
        id: 'brand_mayos',
        child: MayosAppHeader(
          actions: <Widget>[
            TourTarget(
              id: 'assistant',
              child: IconButton(
                tooltip: copy.assistant,
                onPressed: () => context.push(chatPath),
                icon: const Icon(Icons.chat_bubble_outline),
              ),
            ),
            IconButton(
              tooltip: settingsLabel,
              onPressed: () => context.push(settingsPath),
              icon: const Icon(Icons.settings_outlined),
            ),
            // A coach account carries the C/P mode badge in Player mode too
            // (#119); non-coach accounts render nothing here.
            if (isCoach) const ModeAvatarButton(),
          ],
        ),
      ),
      body: IndexedStack(
            key: ValueKey<String>('${account.accountId}:$_confirmedDataRevision'),
            index: index,
            children: <Widget>[
              TickerMode(enabled: index == 0, child: const DashboardTab()),
              TickerMode(enabled: index == 1, child: const ProgramTab()),
              TickerMode(enabled: index == 2, child: const NutritionTab()),
              TickerMode(enabled: index == 3, child: const ProgressTab()),
            ],
          ),
      bottomBar: MayosBottomNavigation(
        items: _items(copy),
        index: index,
        onSelected: (int selected) =>
            ref.read(playerShellTabProvider.notifier).state = selected,
      ),
    );
  }

  @override
  void dispose() {
    _observedRouter?.routerDelegate.removeListener(_onRouteChanged);
    super.dispose();
  }
}

class _RosterAiDisclosureDialog extends StatefulWidget {
  const _RosterAiDisclosureDialog({
    required this.copy,
    required this.onAcknowledge,
  });

  final AssignmentCopy copy;
  final Future<void> Function() onAcknowledge;

  @override
  State<_RosterAiDisclosureDialog> createState() =>
      _RosterAiDisclosureDialogState();
}

class _RosterAiDisclosureDialogState
    extends State<_RosterAiDisclosureDialog> {
  bool _saving = false;
  FailureMessage? _error;

  Future<void> _acknowledge() async {
    setState(() {
      _saving = true;
      _error = null;
    });
    try {
      await widget.onAcknowledge();
      if (mounted) Navigator.of(context).pop();
    } on ApiException catch (error) {
      if (!mounted) return;
      setState(() {
        _saving = false;
        _error = apiFailureMessage(error);
      });
    }
  }

  @override
  Widget build(BuildContext context) => AlertDialog(
        content: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: <Widget>[
            Text(widget.copy.rosterAiDisclosure),
            if (_error != null) ...<Widget>[
              const SizedBox(height: 12),
              Text(
                displayCopyOf(context).failureMessage(_error!),
                style: TextStyle(color: Theme.of(context).colorScheme.error),
              ),
            ],
          ],
        ),
        actions: <Widget>[
          MayosButton(
            label: widget.copy.rosterAiDisclosureOk,
            expand: false,
            loading: _saving,
            onPressed: _saving ? null : _acknowledge,
          ),
        ],
      );
}

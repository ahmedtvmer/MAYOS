import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/api_client.dart';
import '../../core/app_failure.dart';
import '../../core/connectivity_message.dart';
import '../../core/display_language/assignment_copy.dart';
import '../../core/display_language/controller.dart';
import '../../core/display_language/copy_context.dart';
import '../../core/display_language/settings_copy.dart';
import '../../core/models.dart';
import '../../core/theme/mayos_spacing.dart';
import '../../core/theme/mayos_theme.dart';
import '../../core/theme/mayos_typography.dart';
import '../../core/ui/first_strong_direction.dart';
import '../../core/ui/mayos_button.dart';
import '../../providers.dart';
import '../../router.dart';
import '../player/assignment/player_assignment_activity.dart';

class PlayerNotificationsScreen extends ConsumerStatefulWidget {
  const PlayerNotificationsScreen({super.key});

  @override
  ConsumerState<PlayerNotificationsScreen> createState() =>
      _PlayerNotificationsScreenState();
}

class _PlayerNotificationsScreenState
    extends ConsumerState<PlayerNotificationsScreen> {
  bool _loading = true;
  bool _hasLoaded = false;
  bool _markingNoticesRead = false;
  FailureMessage? _error;
  List<AssignmentNotice> _notices = const <AssignmentNotice>[];
  List<CheckIn> _checkIns = const <CheckIn>[];

  String get _language => ref.read(displayLanguageProvider);

  AssignmentCopy get _copy => AssignmentCopy(_language);

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    await _loadContent();
  }

  Future<void> _refreshInPlace() async {
    setState(() => _error = null);
    await _loadContent();
  }

  Future<void> _loadContent() async {
    try {
      final List<Object?> responses = await Future.wait<Object?>(
        <Future<Object?>>[
          ref.read(apiClientProvider).playerNotices(),
          ref.read(apiClientProvider).playerCheckIns(),
        ],
      );
      if (!mounted) return;
      _showLoadedNotifications(responses);
    } on ApiException catch (error) {
      if (!mounted) return;
      _showLoadFailure(error);
    }
  }

  void _showLoadedNotifications(List<Object?> responses) {
    setState(() {
      _notices = responses[0] as List<AssignmentNotice>;
      _checkIns = responses[1] as List<CheckIn>;
      _loading = false;
      _hasLoaded = true;
    });
  }

  void _showLoadFailure(ApiException error) {
    setState(() {
      _loading = false;
      _error = apiFailureMessage(error);
    });
  }

  Future<void> _markNoticesRead() async {
    setState(() => _markingNoticesRead = true);
    try {
      await ref.read(apiClientProvider).markPlayerNoticesRead();
      if (mounted) await _refreshInPlace();
    } on ApiException catch (error) {
      if (!mounted) return;
      setState(() => _error = apiFailureMessage(error));
    } finally {
      if (mounted) setState(() => _markingNoticesRead = false);
    }
  }

  void _openProgram() {
    ref.read(playerShellTabProvider.notifier).state =
        PlayerShellTab.program.index;
    context.go(homePath);
  }

  Widget _errorBanner(BuildContext context) {
    if (_error == null) return const SizedBox.shrink();
    final String message = displayCopyOf(context).failureMessage(_error!);
    return Padding(
      padding: const EdgeInsets.only(bottom: MayosSpacing.md),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          _errorText(context, message),
          _retryButton(),
        ],
      ),
    );
  }

  Widget _errorText(BuildContext context, String message) =>
      FirstStrongDirection(
        text: message,
        child: Text(
          message,
          style: MayosTypography.of(context)
              .bodySecondary
              .copyWith(color: MayosTheme.of(context).danger),
        ),
      );

  Widget _retryButton() => MayosButton(
        label: SettingsCopy(_language).retry,
        variant: MayosButtonVariant.tertiary,
        expand: false,
        onPressed: _load,
      );

  @override
  Widget build(BuildContext context) {
    ref.watch(displayLanguageProvider);
    if (_loading) {
      return const Center(child: CircularProgressIndicator());
    }
    return ListView(
      key: const Key('player_notifications_surface'),
      padding: MayosSpacing.screen,
      children: <Widget>[
        _errorBanner(context),
        if (_hasLoaded) ...<Widget>[
          _notificationsLead(context),
          PlayerAssignmentNoticesCard(
            notices: _notices,
            copy: _copy,
            actions: PlayerNoticeActions(
              onMarkAllRead: _markNoticesRead,
              onViewProgram: _openProgram,
              markingRead: _markingNoticesRead,
            ),
          ),
          const SizedBox(height: MayosSpacing.lg),
          PlayerAssignmentCheckInsCard(checkIns: _checkIns, copy: _copy),
        ],
      ],
    );
  }

  Widget _notificationsLead(BuildContext context) => Padding(
        padding: const EdgeInsets.only(bottom: MayosSpacing.md),
        child: Text(
          _copy.playerNotificationsLead,
          style: MayosTypography.of(context)
              .bodySecondary
              .copyWith(color: MayosTheme.of(context).textSecondary),
        ),
      );
}

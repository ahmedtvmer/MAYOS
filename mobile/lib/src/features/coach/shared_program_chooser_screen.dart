import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/api_client.dart';
import '../../core/app_mode.dart';
import '../../core/display_language/feature_copy_context.dart';
import '../../core/models.dart';
import '../../core/shared_program_text.dart';
import '../../core/theme/mayos_spacing.dart';
import '../../core/ui/mayos_button.dart';
import '../../features/player/auth/auth_controller.dart';
import '../../providers.dart';
import '../../router.dart';

enum _ChooserError { assignmentsUnavailable }

class SharedProgramChooserScreen extends ConsumerStatefulWidget {
  const SharedProgramChooserScreen({super.key});

  @override
  ConsumerState<SharedProgramChooserScreen> createState() =>
      _SharedProgramChooserScreenState();
}

class _SharedProgramChooserScreenState
    extends ConsumerState<SharedProgramChooserScreen> {
  StreamSubscription<SharedProgramText>? _sharedTextSubscription;
  bool _loading = true;
  _ChooserError? _error;
  List<CoachRosterEntry> _assignments = <CoachRosterEntry>[];

  @override
  void initState() {
    super.initState();
    _sharedTextSubscription = ref
        .read(sharedProgramTextStoreProvider)
        .events
        .listen((SharedProgramText _) {
      if (mounted) {
        setState(() {});
      }
    });
    _schedulePrepare();
  }

  @override
  void dispose() {
    _sharedTextSubscription?.cancel();
    super.dispose();
  }

  Future<void> _prepare() async {
    final AuthState auth = ref.read(authControllerProvider);
    final Account? account = auth.session?.account;
    if (account == null || !account.isCoach) {
      if (mounted) {
        setState(() => _loading = false);
      }
      return;
    }
    await ref.read(appModeControllerProvider.notifier).setMode(
          AppMode.coach,
          accountId: account.accountId,
          isCoach: true,
        );
    if (ref.read(sharedProgramTextStoreProvider).pending?.error != null) {
      if (mounted) {
        setState(() => _loading = false);
      }
      return;
    }
    try {
      final List<CoachRosterEntry> assignments =
          await ref.read(apiClientProvider).coachAssignments();
      if (mounted) {
        setState(() {
          _assignments = assignments;
          _loading = false;
        });
      }
    } on ApiException {
      if (mounted) {
        setState(() {
          _error = _ChooserError.assignmentsUnavailable;
          _loading = false;
        });
      }
    }
  }

  void _schedulePrepare() {
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (mounted) _prepare();
    });
  }

  void _backToRoster() {
    ref.read(sharedProgramTextStoreProvider).clear();
    context.go(coachRosterPath);
  }

  void _retryAssignments() {
    setState(() {
      _loading = true;
      _error = null;
    });
    _schedulePrepare();
  }

  @override
  Widget build(BuildContext context) {
    ref.listen<AuthState>(authControllerProvider, (previous, next) {
      if (previous?.session == null && next.session != null) {
        _schedulePrepare();
      }
    });
    final copy = coachCopyOf(context);
    final AuthState auth = ref.watch(authControllerProvider);
    final Account? account = auth.session?.account;
    final SharedProgramText? text =
        ref.watch(sharedProgramTextStoreProvider).pending;

    if (auth.status == AuthStatus.loading ||
        _loading && account?.isCoach == true) {
      return Scaffold(
        key: const Key('shared_program_chooser'),
        appBar: AppBar(title: Text(copy.programImportTitle)),
        body: const SafeArea(child: Center(child: CircularProgressIndicator())),
      );
    }

    String? message;
    if (text == null) {
      message = copy.sharedProgramUnavailable;
    } else if (account == null) {
      message = copy.sharedProgramSignInRequired;
    } else if (!account.isCoach) {
      message = copy.sharedProgramCoachOnly;
    } else if (text.error != null) {
      message = copy.sharedProgramRefusal(text.error!);
    }

    return Scaffold(
      key: const Key('shared_program_chooser'),
      appBar: AppBar(title: Text(copy.programImportTitle)),
      body: SafeArea(
        child: ListView(
          padding: const EdgeInsetsDirectional.all(MayosSpacing.md),
          children: <Widget>[
            if (message != null) ...<Widget>[
              Text(message),
              if (account != null && !account.isCoach)
                MayosButton(
                  label: copy.sharedProgramGoHome,
                  onPressed: () {
                    ref.read(sharedProgramTextStoreProvider).clear();
                    context.go(homePath);
                  },
                )
              else
                MayosButton(
                  label: copy.sharedProgramBackToRoster,
                  onPressed: _backToRoster,
                ),
            ] else ...<Widget>[
              Text(copy.choosePlayerForSharedProgram),
              if (_error == _ChooserError.assignmentsUnavailable) ...<Widget>[
                Text(copy.sharedProgramAssignmentsUnavailable),
                MayosButton(
                  label: copy.sharedProgramRetry,
                  onPressed: _retryAssignments,
                ),
                MayosButton(
                  label: copy.sharedProgramBackToRoster,
                  onPressed: _backToRoster,
                ),
              ],
              for (final CoachRosterEntry entry in _assignments)
                MayosButton(
                  label: entry.playerUsername,
                  variant: MayosButtonVariant.secondary,
                  onPressed: () {
                    final SharedProgramText? currentText =
                        ref.read(sharedProgramTextStoreProvider).pending;
                    final String? sharedText = currentText?.text;
                    if (sharedText == null) return;
                    ref.read(sharedProgramTextStoreProvider).clear();
                    context.go(
                      sharedProgramImportLocation(entry.assignmentId),
                      extra: <String, String>{
                        'text': sharedText,
                        'player': entry.playerUsername,
                      },
                    );
                  },
                ),
              if (_assignments.isEmpty && _error == null) ...<Widget>[
                Text(copy.noAssignedPlayers),
                MayosButton(
                  label: copy.sharedProgramBackToRoster,
                  onPressed: _backToRoster,
                ),
              ],
            ],
          ],
        ),
      ),
    );
  }
}

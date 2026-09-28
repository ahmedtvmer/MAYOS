import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api_client.dart';
import '../../core/models.dart';
import '../../core/theme/mayos_spacing.dart';
import '../../core/theme/mayos_theme.dart';
import '../../core/theme/mayos_typography.dart';
import '../../core/ui/mayos_section_header.dart';
import '../../providers.dart';
import 'coach_request_sheet.dart';
import 'coach_shared.dart';

/// The Requests tab of the Coach mode shell (#121): every program request
/// across the roster from `GET /coach/program-requests`, pending first, then
/// **Answered**. A pending row opens the resolve sheet; answered rows are
/// read-only. The tab publishes the pending count for the shell's badge and
/// refetches when the player page resolves a request.
class CoachRequestsScreen extends ConsumerStatefulWidget {
  const CoachRequestsScreen({super.key});

  @override
  ConsumerState<CoachRequestsScreen> createState() =>
      _CoachRequestsScreenState();
}

class _CoachRequestsScreenState extends ConsumerState<CoachRequestsScreen> {
  bool _loading = true;
  String? _error;
  List<ProgramRequest> _requests = const <ProgramRequest>[];

  /// Bumped by every load so a slower, older response can never overwrite a
  /// newer one when revision bumps start overlapping loads (#120/#121).
  int _loadSeq = 0;

  @override
  void initState() {
    super.initState();
    _load();
  }

  /// Publishes the pending count so the shell's badge tracks every change
  /// made here or on the player page without a second fetch (#121).
  void _publishCount() {
    ref.read(coachPendingRequestsCountProvider.notifier).state =
        _requests.where((ProgramRequest request) => request.isPending).length;
  }

  Future<void> _load({bool showLoader = true}) async {
    final int seq = ++_loadSeq;
    if (showLoader) {
      setState(() {
        _loading = true;
        _error = null;
      });
    }
    try {
      final List<ProgramRequest> requests = sortCoachRequests(
          await ref.read(apiClientProvider).coachAllProgramRequests());
      if (!mounted || seq != _loadSeq) return;
      setState(() {
        _requests = requests;
        _loading = false;
        _error = null;
      });
      _publishCount();
    } on ApiException catch (error) {
      if (!mounted || seq != _loadSeq) return;
      setState(() {
        _loading = false;
        _error = error.message;
      });
    }
  }

  /// Opens the resolve sheet for one pending request and runs the shared
  /// post-resolve flow (#121): snackbar, roster-chip refresh, this list's
  /// refetch, and — on a refusal — the readable message it refreshes from.
  Future<void> _resolve(ProgramRequest request) async {
    setState(() => _error = null);
    final CoachRequestResolution result = await showCoachRequestResolveSheet(
      context,
      request: request,
      playerUsername: request.playerUsername,
    );
    if (!mounted) return;
    await applyCoachRequestAction(
      ref,
      context: context,
      result: result,
      reload: () => _load(showLoader: false),
      showError: (String message) => setState(() => _error = message),
      // This tab republishes the badge from its own reload.
      notifyRequestsTab: false,
    );
  }

  Widget _errorBanner(BuildContext context) {
    if (_error == null) {
      return const SizedBox.shrink();
    }
    return Padding(
      padding: const EdgeInsets.only(bottom: MayosSpacing.sm),
      child: Text(
        _error!,
        style: MayosTypography.bodySecondary
            .copyWith(color: MayosTheme.of(context).danger),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    // The player page resolved one of these requests: refetch so this list
    // and the tab badge track it (#121). The player page bumps the revision
    // and this tab never does, so the listener cannot loop.
    ref.listen<int>(coachRequestsRevisionProvider, (int? previous, int next) {
      if (previous != next) {
        _load(showLoader: false);
      }
    });
    if (_loading) {
      return const Center(child: CircularProgressIndicator());
    }
    final MayosThemeExtension c = MayosTheme.of(context);
    final List<ProgramRequest> pending = _requests
        .where((ProgramRequest request) => request.isPending)
        .toList(growable: false);
    final List<ProgramRequest> answered = _requests
        .where((ProgramRequest request) => !request.isPending)
        .toList(growable: false);
    return ListView(
      padding: MayosSpacing.screen,
      children: <Widget>[
        _errorBanner(context),
        if (_requests.isEmpty)
          Text(
            'No program requests yet.',
            style: MayosTypography.bodySecondary
                .copyWith(color: c.textSecondary),
          )
        else ...<Widget>[
          const MayosSectionHeader(title: 'Pending'),
          if (pending.isEmpty)
            Text(
              'No pending requests.',
              style:
                  MayosTypography.bodySecondary.copyWith(color: c.textSecondary),
            )
          else
            for (final ProgramRequest request in pending)
              CoachRequestCard(
                request: request,
                onTap: () => _resolve(request),
              ),
          const SizedBox(height: MayosSpacing.md),
          const MayosSectionHeader(title: 'Answered'),
          if (answered.isEmpty)
            Text(
              'Nothing answered yet.',
              style:
                  MayosTypography.bodySecondary.copyWith(color: c.textSecondary),
            )
          else
            for (final ProgramRequest request in answered)
              CoachRequestCard(
                request: request,
                onTap: () => _resolve(request),
              ),
        ],
      ],
    );
  }
}

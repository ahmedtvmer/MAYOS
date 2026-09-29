import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/api_client.dart';
import '../../core/models.dart';
import '../../core/theme/mayos_spacing.dart';
import '../../core/theme/mayos_theme.dart';
import '../../core/theme/mayos_typography.dart';
import '../../core/ui/mayos_card.dart';
import '../../core/ui/mayos_section_header.dart';
import '../../providers.dart';
import '../../router.dart';
import 'coach_request_sheet.dart';
import 'coach_shared.dart';

/// The Requests tab of the Coach mode shell (#121): every program request
/// across the roster from `GET /coach/program-requests`, pending first, then
/// **Answered**. On desktop a request opens in the URL-backed detail pane; on
/// phones a pending row keeps the existing resolve sheet. The tab publishes
/// the pending count for the shell's badge and refetches after resolutions.
class CoachRequestsScreen extends ConsumerStatefulWidget {
  const CoachRequestsScreen({super.key, this.selectedRequestId});

  final String? selectedRequestId;

  @override
  ConsumerState<CoachRequestsScreen> createState() =>
      _CoachRequestsScreenState();
}

class _CoachRequestsScreenState extends ConsumerState<CoachRequestsScreen> {
  final TextEditingController _reply = TextEditingController();
  bool _loading = true;
  bool _resolving = false;
  String? _error;
  List<ProgramRequest> _requests = const <ProgramRequest>[];

  /// Bumped by every load so a slower, older response can never overwrite a
  /// newer one when revision bumps start overlapping loads (#120/#121).
  int _loadSeq = 0;

  @override
  void dispose() {
    _reply.dispose();
    super.dispose();
  }

  @override
  void didUpdateWidget(covariant CoachRequestsScreen oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.selectedRequestId != widget.selectedRequestId) {
      _reply.clear();
      _error = null;
    }
  }

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

  Future<void> _resolveInline(
      ProgramRequest request, CoachRequestDecision decision) async {
    setState(() {
      _resolving = true;
      _error = null;
    });
    final CoachRequestResolution resolution =
        await resolveCoachProgramRequest(
      api: ref.read(apiClientProvider),
      request: request,
      decision: decision,
      reply: _reply.text.trim(),
    );
    if (!mounted) return;
    setState(() => _resolving = false);
    await applyCoachRequestAction(
      ref,
      context: context,
      result: resolution,
      reload: () => _load(showLoader: false),
      showError: (String message) => setState(() => _error = message),
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

  Widget _requestList(BuildContext context) {
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
          _emptyRequests(context)
        else ...<Widget>[
          _pendingSection(context, pending),
          const SizedBox(height: MayosSpacing.md),
          _answeredSection(context, answered),
        ],
      ],
    );
  }

  Widget _emptyRequests(BuildContext context) => Text(
        'No program requests yet.',
        style: MayosTypography.bodySecondary
            .copyWith(color: MayosTheme.of(context).textSecondary),
      );

  Widget _pendingSection(
      BuildContext context, List<ProgramRequest> pending) {
    final Color secondary = MayosTheme.of(context).textSecondary;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: <Widget>[
        const MayosSectionHeader(title: 'Pending'),
        if (pending.isEmpty)
          Text('No pending requests.',
              style: MayosTypography.bodySecondary.copyWith(color: secondary))
        else
          for (final ProgramRequest request in pending)
            CoachRequestCard(
              request: request,
              onTap: () => _openRequest(context, request),
            ),
      ],
    );
  }

  void _openRequest(BuildContext context, ProgramRequest request) {
    final bool desktop = MediaQuery.sizeOf(context).width >=
        MayosLayout.desktopNavigationBreakpoint;
    if (desktop) {
      context.go(
          '$coachRequestsPath/${Uri.encodeComponent(request.requestId)}');
      return;
    }
    _resolve(request);
  }

  Widget _answeredSection(
      BuildContext context, List<ProgramRequest> answered) {
    final Color secondary = MayosTheme.of(context).textSecondary;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: <Widget>[
        const MayosSectionHeader(title: 'Answered'),
        if (answered.isEmpty)
          Text('Nothing answered yet.',
              style: MayosTypography.bodySecondary.copyWith(color: secondary))
        else
          for (final ProgramRequest request in answered)
            CoachRequestCard(request: request),
      ],
    );
  }

  Widget _requestDetail(BuildContext context, ProgramRequest? request) {
    if (request == null) {
      return const Center(child: Text('This request is no longer available.'));
    }
    return ListView(
      key: const Key('coach_request_detail_pane'),
      padding: MayosSpacing.screen,
      children: <Widget>[
        _errorBanner(context),
        const MayosSectionHeader(title: 'Request detail'),
        _requestSummary(context, request),
        if (request.isPending) ...<Widget>[
          const SizedBox(height: MayosSpacing.md),
          _decisionControls(request),
        ] else
          _answeredRequestMessage(context),
      ],
    );
  }

  Widget _requestSummary(BuildContext context, ProgramRequest request) {
    final MayosThemeExtension theme = MayosTheme.of(context);
    return MayosCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          Text(request.playerUsername ?? 'Player'),
          const SizedBox(height: MayosSpacing.xs),
          Text(coachRequestTitle(request),
              style: MayosTypography.exerciseTitle
                  .copyWith(color: theme.textPrimary)),
          const SizedBox(height: MayosSpacing.xs),
          Text('“${request.reason}”'),
          const SizedBox(height: MayosSpacing.xs),
          coachRequestStatusChip(context, request),
          if (request.hasResponse) ...<Widget>[
            const SizedBox(height: MayosSpacing.xs),
            Text('You: ${request.response}'),
          ],
        ],
      ),
    );
  }

  Widget _decisionControls(ProgramRequest request) =>
      CoachRequestDecisionControls(
        request: request,
        replyController: _reply,
        busy: _resolving,
        onDecision: (CoachRequestDecision decision) =>
            _resolveInline(request, decision),
      );

  Widget _answeredRequestMessage(BuildContext context) => Text(
        'This request has been answered.',
        style: MayosTypography.bodySecondary
            .copyWith(color: MayosTheme.of(context).textSecondary),
      );

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
    final String? selectedId = widget.selectedRequestId;
    ProgramRequest? selected;
    if (selectedId != null) {
      for (final ProgramRequest request in _requests) {
        if (request.requestId == selectedId) {
          selected = request;
          break;
        }
      }
    }
    final bool desktop = MediaQuery.sizeOf(context).width >=
        MayosLayout.desktopNavigationBreakpoint;
    if (desktop) {
      return Row(
        children: <Widget>[
          SizedBox(
            width: MayosLayout.coachMasterPaneWidth,
            child: _requestList(context),
          ),
          const VerticalDivider(width: 1),
          Expanded(
            child: selectedId == null
                ? const Center(child: Text('Select a request to review.'))
                : _requestDetail(context, selected),
          ),
        ],
      );
    }
    return selectedId == null
        ? _requestList(context)
        : _requestDetail(context, selected);
  }
}

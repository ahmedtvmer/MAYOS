import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/api_client.dart';
import '../../core/app_failure.dart';
import '../../core/connectivity_message.dart';
import '../../core/display_language/copy_context.dart';
import '../../core/display_language/feature_copy_context.dart';
import '../../core/models.dart';
import '../../core/theme/mayos_spacing.dart';
import '../../core/theme/mayos_theme.dart';
import '../../core/theme/mayos_typography.dart';
import '../../core/ui/is_desktop_layout.dart';
import '../../core/ui/mayos_card.dart';
import '../../core/ui/mayos_section_header.dart';
import '../../core/ui/first_strong_direction.dart';
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
  bool _loading = true;
  FailureMessage? _error;
  List<ProgramRequest> _requests = const <ProgramRequest>[];

  /// Bumped by every load so a slower, older response can never overwrite a
  /// newer one when revision bumps start overlapping loads (#120/#121).
  int _loadSeq = 0;

  @override
  void didUpdateWidget(covariant CoachRequestsScreen oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.selectedRequestId != widget.selectedRequestId) {
      _error = null;
    }
  }

  @override
  void initState() {
    super.initState();
    final List<ProgramRequest>? cached = ref.read(coachRequestsListProvider);
    final int? cacheRevision = ref.read(coachRequestsListRevisionProvider);
    if (cached == null ||
        cacheRevision != ref.read(coachRequestsRevisionProvider)) {
      _load();
    } else {
      _requests = cached;
      _loading = false;
      _publishCount();
    }
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
      ref.read(coachRequestsListProvider.notifier).state = requests;
      ref.read(coachRequestsListRevisionProvider.notifier).state =
          ref.read(coachRequestsRevisionProvider);
      _publishCount();
    } on ApiException catch (error) {
      if (!mounted || seq != _loadSeq) return;
      setState(() {
        _loading = false;
        _error = apiFailureMessage(error);
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
      showError: (FailureMessage failure) => setState(() => _error = failure),
      // This tab republishes the badge from its own reload.
      notifyRequestsTab: false,
    );
  }

  Future<void> _resolveInline(ProgramRequest request,
      CoachRequestDecision decision, String reply) async {
    setState(() => _error = null);
    final CoachRequestResolution resolution = await resolveCoachProgramRequest(
      api: ref.read(apiClientProvider),
      request: request,
      decision: decision,
      reply: reply,
    );
    if (!mounted) return;
    await applyCoachRequestAction(
      ref,
      context: context,
      result: resolution,
      reload: () => _load(showLoader: false),
      showError: (FailureMessage failure) => setState(() => _error = failure),
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
        displayCopyOf(context).failureMessage(_error!),
        style: MayosTypography.of(context).bodySecondary
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
          _pendingSection(context, pending, widget.selectedRequestId),
          const SizedBox(height: MayosSpacing.md),
          _answeredSection(context, answered, widget.selectedRequestId),
        ],
      ],
    );
  }

  Widget _emptyRequests(BuildContext context) => Text(
        coachCopyOf(context).noProgramRequests,
        style: MayosTypography.of(context).bodySecondary
            .copyWith(color: MayosTheme.of(context).textSecondary),
      );

  Widget _pendingSection(
      BuildContext context, List<ProgramRequest> pending, String? selectedId) {
    final copy = coachCopyOf(context);
    final Color secondary = MayosTheme.of(context).textSecondary;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: <Widget>[
        MayosSectionHeader(title: copy.pending),
        if (pending.isEmpty)
          Text(copy.noPendingRequests,
              style: MayosTypography.of(context).bodySecondary.copyWith(color: secondary))
        else
          for (final ProgramRequest request in pending)
            CoachRequestCard(
              request: request,
              selected: request.requestId == selectedId,
              onTap: () => _openRequest(context, request),
            ),
      ],
    );
  }

  void _openRequest(BuildContext context, ProgramRequest request) {
    final bool desktop = isDesktopLayout(context);
    if (desktop) {
      context.go(coachRequestLocation(request.requestId));
      return;
    }
    _resolve(request);
  }

  Widget _answeredSection(
      BuildContext context, List<ProgramRequest> answered, String? selectedId) {
    final copy = coachCopyOf(context);
    final Color secondary = MayosTheme.of(context).textSecondary;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: <Widget>[
        MayosSectionHeader(title: copy.answered),
        if (answered.isEmpty)
          Text(copy.nothingAnswered,
              style: MayosTypography.of(context).bodySecondary.copyWith(color: secondary))
        else
          for (final ProgramRequest request in answered)
            CoachRequestCard(
              request: request,
              selected: request.requestId == selectedId,
            ),
      ],
    );
  }

  Widget _requestDetail(BuildContext context, ProgramRequest? request) {
    if (request == null) {
      return Center(child: Text(coachCopyOf(context).requestUnavailable));
    }
    return CoachRequestDetailPane(
      key: ValueKey<String>(request.requestId),
      request: request,
      error: _error,
      onDecision: (CoachRequestDecision decision, String reply) =>
          _resolveInline(request, decision, reply),
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
    final bool desktop = isDesktopLayout(context);
    final copy = coachCopyOf(context);
    if (desktop) {
      return CoachListDetail(
        list: _requestList(context),
        detail: selectedId == null
            ? Center(child: Text(copy.selectRequest))
            : _requestDetail(context, selected),
        listKey: const Key('coach_request_master_pane'),
        detailKey: const Key('coach_request_detail_region'),
      );
    }
    return selectedId == null
        ? _requestList(context)
        : _requestDetail(context, selected);
  }
}

class CoachRequestDetailPane extends StatefulWidget {
  const CoachRequestDetailPane({
    super.key,
    required this.request,
    required this.onDecision,
    this.error,
  });

  final ProgramRequest request;
  final FailureMessage? error;
  final Future<void> Function(CoachRequestDecision decision, String reply)
      onDecision;

  @override
  State<CoachRequestDetailPane> createState() => _CoachRequestDetailPaneState();
}

class _CoachRequestDetailPaneState extends State<CoachRequestDetailPane> {
  final TextEditingController _reply = TextEditingController();
  bool _resolving = false;

  @override
  void dispose() {
    _reply.dispose();
    super.dispose();
  }

  Future<void> _resolve(CoachRequestDecision decision) async {
    setState(() => _resolving = true);
    await widget.onDecision(decision, _reply.text.trim());
    if (mounted) {
      setState(() => _resolving = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final ProgramRequest request = widget.request;
    final copy = coachCopyOf(context);
    final MayosThemeExtension theme = MayosTheme.of(context);
    return ListView(
      key: const Key('coach_request_detail_pane'),
      padding: MayosSpacing.screen,
      children: <Widget>[
        if (widget.error != null)
          Padding(
            padding: const EdgeInsets.only(bottom: MayosSpacing.sm),
            child: Text(
              displayCopyOf(context).failureMessage(widget.error!),
              style:
                  MayosTypography.of(context).bodySecondary.copyWith(color: theme.danger),
            ),
          ),
        MayosSectionHeader(title: copy.requestDetail),
        MayosCard(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: <Widget>[
              Text(request.playerUsername ?? copy.player),
              const SizedBox(height: MayosSpacing.xs),
              Text(
                coachRequestTitle(context, request),
                style: MayosTypography.of(context).exerciseTitle
                    .copyWith(color: theme.textPrimary),
              ),
              const SizedBox(height: MayosSpacing.xs),
              FirstStrongDirection(
                text: request.reason,
                child: Text('“${request.reason}”'),
              ),
              const SizedBox(height: MayosSpacing.xs),
              coachRequestStatusChip(context, request),
              if (request.hasResponse) ...<Widget>[
                const SizedBox(height: MayosSpacing.xs),
                FirstStrongDirection(
                  text: copy.youReplied(request.response!),
                  child: Text(copy.youReplied(request.response!)),
                ),
              ],
            ],
          ),
        ),
        if (request.isPending) ...<Widget>[
          const SizedBox(height: MayosSpacing.md),
          CoachRequestDecisionControls(
            request: request,
            replyController: _reply,
            busy: _resolving,
            onDecision: _resolve,
          ),
        ] else
          Text(
            copy.requestAnswered,
            style: MayosTypography.of(context).bodySecondary
                .copyWith(color: theme.textSecondary),
          ),
      ],
    );
  }
}

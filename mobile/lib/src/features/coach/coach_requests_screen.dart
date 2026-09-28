import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api_client.dart';
import '../../core/models.dart';
import '../../core/theme/mayos_spacing.dart';
import '../../core/theme/mayos_theme.dart';
import '../../core/theme/mayos_typography.dart';
import '../../core/ui/mayos_card.dart';
import '../../providers.dart';
import 'coach_request_sheet.dart';

/// The Requests tab of the Coach mode shell (#121): every program request
/// across the roster from `GET /coach/program-requests`, pending first (the
/// service's order), then **Answered**. A pending row opens the resolve sheet;
/// answered rows are read-only. The tab publishes the pending count for the
/// shell's badge and refetches when the player page resolves a request.
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
      final List<ProgramRequest> requests =
          await ref.read(apiClientProvider).coachAllProgramRequests();
      if (!mounted || seq != _loadSeq) return;
      setState(() {
        _requests = requests;
        _loading = false;
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

  /// Opens the resolve sheet for one pending request, then applies what it
  /// reported: a success updates the list and the roster row's chip, a service
  /// refusal is shown readably and the list is refreshed anyway (#121).
  Future<void> _resolve(ProgramRequest request) async {
    final CoachRequestResolution result =
        await showCoachRequestResolveSheet(
      context,
      request: request,
      playerUsername: request.playerUsername,
    );
    if (!mounted) return;
    if (result.resolved) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text(result.request!.status == 'applied'
              ? 'Program request applied.'
              : 'Program request declined.'),
        ),
      );
      ref.read(coachRosterRevisionProvider.notifier).state++;
      await _load(showLoader: false);
      return;
    }
    if (result.message != null) {
      setState(() => _error = result.message);
      await _load(showLoader: false);
    }
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

  /// One request row: the player and day, the swap or new split, the reason,
  /// and the status. Only a pending row is tappable (#121).
  Widget _requestCard(BuildContext context, ProgramRequest request) {
    final MayosThemeExtension c = MayosTheme.of(context);
    final bool pending = request.isPending;
    return Padding(
      padding: const EdgeInsets.only(bottom: MayosSpacing.sm),
      child: MayosCard(
        key: Key('request_card_${request.requestId}'),
        onTap: pending ? () => _resolve(request) : null,
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: <Widget>[
            Row(
              children: <Widget>[
                Icon(
                  request.isExerciseSubstitution
                      ? Icons.swap_horiz
                      : Icons.calendar_view_week,
                  size: 20,
                  color: c.accent,
                ),
                const SizedBox(width: MayosSpacing.xs),
                Expanded(
                  child: Text(
                    '${request.playerUsername ?? 'Player'}'
                    '${request.dayName == null ? '' : ' · ${request.dayName}'}',
                    style:
                        MayosTypography.caption.copyWith(color: c.textSecondary),
                  ),
                ),
                coachRequestStatusChip(context, request),
              ],
            ),
            const SizedBox(height: MayosSpacing.xs),
            Text(
              coachRequestTitle(request),
              style:
                  MayosTypography.exerciseTitle.copyWith(color: c.textPrimary),
            ),
            const SizedBox(height: MayosSpacing.xxs),
            Text(
              '“${request.reason}”',
              style:
                  MayosTypography.bodySecondary.copyWith(color: c.textPrimary),
            ),
            if (request.hasResponse) ...<Widget>[
              const SizedBox(height: MayosSpacing.xs),
              Text(
                'You: ${request.response}',
                style:
                    MayosTypography.caption.copyWith(color: c.textSecondary),
              ),
            ],
            if (pending) ...<Widget>[
              const SizedBox(height: MayosSpacing.xxs),
              Text(
                'Sent ${request.createdAt} · tap to review',
                style: MayosTypography.caption.copyWith(color: c.textMuted),
              ),
            ],
          ],
        ),
      ),
    );
  }

  Widget _section(BuildContext context, String title, List<Widget> children) {
    final MayosThemeExtension c = MayosTheme.of(context);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: <Widget>[
        Text(
          title,
          style: MayosTypography.sectionHeading.copyWith(color: c.textPrimary),
        ),
        const SizedBox(height: MayosSpacing.xs),
        ...children,
        const SizedBox(height: MayosSpacing.md),
      ],
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
          _section(
            context,
            'Pending',
            pending.isEmpty
                ? <Widget>[
                    Text(
                      'No pending requests.',
                      style: MayosTypography.bodySecondary
                          .copyWith(color: c.textSecondary),
                    )
                  ]
                : <Widget>[
                    for (final ProgramRequest request in pending)
                      _requestCard(context, request),
                  ],
          ),
          _section(
            context,
            'Answered',
            answered.isEmpty
                ? <Widget>[
                    Text(
                      'Nothing answered yet.',
                      style: MayosTypography.bodySecondary
                          .copyWith(color: c.textSecondary),
                    )
                  ]
                : <Widget>[
                    for (final ProgramRequest request in answered)
                      _requestCard(context, request),
                  ],
          ),
        ],
      ],
    );
  }
}

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../../core/api_client.dart';
import '../../../core/app_failure.dart';
import '../../../core/connectivity_message.dart';
import '../../../core/display_language/assignment_copy.dart';
import '../../../core/display_language/controller.dart';
import '../../../core/display_language/copy_context.dart';
import '../../../core/models.dart';
import '../../../core/theme/mayos_spacing.dart';
import '../../../core/theme/mayos_theme.dart';
import '../../../core/theme/mayos_typography.dart';
import '../../../core/ui/mayos_button.dart';
import '../../../core/ui/mayos_card.dart';
import '../../../core/ui/mayos_section_header.dart';
import '../../../core/ui/mayos_text_field.dart';
import '../../../core/ui/first_strong_direction.dart';
import '../program/program_change_summary_card.dart';
import '../../../providers.dart';
import '../../../router.dart';
import 'program_request_dialog.dart';

/// Player-side coaching assignment (#24).
///
/// When no assignment is active, the player pastes a coach's bearer code,
/// previews the coach identity and the exact access it grants, then explicitly
/// consents to redeem it. When an assignment is active, the player can end it,
/// which revokes the coach's access immediately.
class PlayerAssignmentScreen extends ConsumerStatefulWidget {
  const PlayerAssignmentScreen({super.key});

  @override
  ConsumerState<PlayerAssignmentScreen> createState() =>
      _PlayerAssignmentScreenState();
}

class _PlayerAssignmentScreenState
    extends ConsumerState<PlayerAssignmentScreen> {
  final TextEditingController _code = TextEditingController();

  bool _loading = true;
  bool _previewing = false;
  bool _redeeming = false;
  bool _ending = false;
  FailureMessage? _error;
  String? _localError;
  Assignment? _assignment;
  List<AssignmentNotice> _notices = const <AssignmentNotice>[];
  List<ProgramRequest> _programRequests = const <ProgramRequest>[];
  List<CheckIn> _checkIns = const <CheckIn>[];
  AssignmentInvitePreview? _preview;
  String? _previewToken;
  bool _requestingChange = false;
  String? _cancellingRequestId;
  FailureMessage? _requestError;

  AssignmentCopy get _copy => AssignmentCopy(ref.read(displayLanguageProvider));

  FailureMessage _mutationFailure(ApiException error) =>
      mutationFailureMessage(error);

  FailureMessage _rawFailure(ApiException error) => apiFailureMessage(error);

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void dispose() {
    _code.dispose();
    super.dispose();
  }

  Future<void> _load() async {
    setState(() {
      _loading = true;
      _error = null;
      _localError = null;
    });
    try {
      final ApiClient api = ref.read(apiClientProvider);
      final List<Object?> results =
          await Future.wait<Object?>(<Future<Object?>>[
        api.myAssignment(),
        api.playerNotices(),
        api.playerProgramRequests(),
        api.playerCheckIns(),
      ]);
      if (!mounted) return;
      setState(() {
        _assignment = results[0] as Assignment?;
        _notices = results[1] as List<AssignmentNotice>;
        _programRequests = results[2] as List<ProgramRequest>;
        _checkIns = results[3] as List<CheckIn>;
        _loading = false;
      });
    } on ApiException catch (error) {
      if (!mounted) return;
      setState(() {
        _loading = false;
        _error = _rawFailure(error);
      });
    }
  }

  /// Any edit invalidates the preview so consent can never target a different code.
  void _onCodeChanged(String _) {
    if (_preview == null && _previewToken == null) {
      return;
    }
    setState(() {
      _preview = null;
      _previewToken = null;
      _error = null;
      _localError = null;
    });
  }

  Future<void> _previewCode() async {
    final String token = _code.text.trim();
    if (token.length < 10) {
      setState(() {
        _error = null;
        _localError = _copy.enterInviteCode;
      });
      return;
    }
    setState(() {
      _previewing = true;
      _error = null;
      _localError = null;
      _preview = null;
      _previewToken = null;
    });
    try {
      final AssignmentInvitePreview preview =
          await ref.read(apiClientProvider).previewAssignmentInvite(token);
      if (!mounted) return;
      if (_code.text.trim() != token) {
        setState(() => _previewing = false);
        return;
      }
      setState(() {
        _previewing = false;
        _preview = preview;
        _previewToken = token;
      });
    } on ApiException catch (error) {
      if (!mounted) return;
      setState(() {
        _previewing = false;
        _error = _rawFailure(error);
      });
    }
  }

  Future<void> _consent() async {
    final String? previewedToken = _previewToken;
    if (previewedToken == null) {
      return;
    }
    setState(() {
      _redeeming = true;
      _error = null;
      _localError = null;
    });
    try {
      final Assignment assignment = await ref
          .read(apiClientProvider)
          .redeemAssignmentInvite(previewedToken);
      if (!mounted) return;
      _code.clear();
      setState(() {
        _redeeming = false;
        _preview = null;
        _previewToken = null;
        // The redeem response is the committed truth; no follow-up read is needed.
        _assignment = assignment;
      });
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text(_copy.assignmentAccepted)),
      );
    } on ApiException catch (error) {
      if (!mounted) return;
      setState(() {
        _redeeming = false;
        _error = _rawFailure(error);
      });
    }
  }

  Future<void> _end() async {
    final bool? confirmed = await showDialog<bool>(
      context: context,
      builder: (BuildContext context) => AlertDialog(
        title: Text(_copy.leaveCoachQuestion),
        content: Text(_copy.leaveCoachLead),
        actions: <Widget>[
          MayosButton(
            label: _copy.cancel,
            variant: MayosButtonVariant.tertiary,
            expand: false,
            onPressed: () => Navigator.of(context).pop(false),
          ),
          MayosButton(
            label: _copy.leaveCoach,
            expand: false,
            onPressed: () => Navigator.of(context).pop(true),
          ),
        ],
      ),
    );
    if (confirmed != true || !mounted) return;
    setState(() {
      _ending = true;
      _error = null;
      _localError = null;
    });
    try {
      await ref.read(apiClientProvider).endMyAssignment();
      if (!mounted) return;
      setState(() {
        _ending = false;
        _assignment = null;
      });
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text(_copy.leaveCoachComplete)),
      );
    } on ApiException catch (error) {
      if (!mounted) return;
      setState(() {
        _ending = false;
        _error = _rawFailure(error);
      });
    }
  }

  Future<void> _markNoticesRead() async {
    try {
      await ref.read(apiClientProvider).markPlayerNoticesRead();
      if (!mounted) return;
      await _load();
    } on ApiException catch (error) {
      if (!mounted) return;
      setState(() => _error = _rawFailure(error));
    }
  }

  void _openProgram() {
    ref.read(playerShellTabProvider.notifier).state = 1;
    context.go(homePath);
  }

  Future<void> _requestChange() async {
    try {
      final ProgramRequest? created = await requestProgramChange(
        context,
        ref,
        onSubmitting: () => setState(() {
          _requestingChange = true;
          _requestError = null;
        }),
      );
      if (created == null || !mounted) return;
      setState(() {
        _requestingChange = false;
        _programRequests = <ProgramRequest>[created, ..._programRequests];
      });
    } on ApiException catch (error) {
      if (!mounted) return;
      setState(() {
        _requestingChange = false;
        _requestError = _mutationFailure(error);
      });
    }
  }

  Future<void> _cancelRequest(ProgramRequest request) async {
    setState(() {
      _cancellingRequestId = request.requestId;
      _requestError = null;
    });
    try {
      final ProgramRequest cancelled = await ref
          .read(apiClientProvider)
          .cancelPlayerProgramRequest(request.requestId);
      if (!mounted) return;
      setState(() {
        _cancellingRequestId = null;
        _programRequests = _programRequests
            .map((ProgramRequest item) =>
                item.requestId == cancelled.requestId ? cancelled : item)
            .toList(growable: false);
      });
    } on ApiException catch (error) {
      if (!mounted) return;
      setState(() {
        _cancellingRequestId = null;
        _requestError = _mutationFailure(error);
      });
    }
  }

  Widget _programRequestsCard(BuildContext context) {
    final MayosThemeExtension c = MayosTheme.of(context);
    final AssignmentCopy copy = _copy;
    return Padding(
      padding: const EdgeInsets.only(top: MayosSpacing.lg),
      child: MayosCard(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: <Widget>[
            MayosSectionHeader(
              title: copy.programRequests,
              padding: EdgeInsets.zero,
              trailing: MayosButton(
                label: copy.requestChange,
                icon: Icons.add,
                variant: MayosButtonVariant.tertiary,
                expand: false,
                loading: _requestingChange,
                onPressed: _requestingChange ? null : _requestChange,
              ),
            ),
            if (_requestError != null) ...<Widget>[
              Text(
                displayCopyOf(context).failureMessage(_requestError!),
                style: MayosTypography.bodySecondary.copyWith(color: c.danger),
              ),
              const SizedBox(height: MayosSpacing.sm),
            ],
            if (_programRequests.isEmpty)
              Text(
                copy.noProgramRequests,
                style: MayosTypography.bodySecondary
                    .copyWith(color: c.textSecondary),
              )
            else
              for (final ProgramRequest request in _programRequests)
                Padding(
                  padding: const EdgeInsets.only(bottom: MayosSpacing.sm),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: <Widget>[
                      Row(
                        children: <Widget>[
                          Chip(label: Text(copy.requestStatus(request.status))),
                          const SizedBox(width: MayosSpacing.xs),
                          Expanded(
                            child: Text(
                              copy.programRequestDescription(
                                kind: request.kind,
                                exercise: request.exerciseId,
                                day: request.dayName,
                                replacement: request.replacementExerciseId,
                                frequency: request.desiredWeeklyFrequency,
                                preference: request.desiredSplitPreference,
                              ),
                              style: MayosTypography.body
                                  .copyWith(color: c.textPrimary),
                              textAlign: copy.isArabic ? TextAlign.end : null,
                            ),
                          ),
                        ],
                      ),
                      FirstStrongDirection(
                        text: request.reason,
                        child: Text(
                          '${copy.reasonPrefix}${request.reason}',
                          style: MayosTypography.caption
                              .copyWith(color: c.textMuted),
                        ),
                      ),
                      if (request.hasResponse)
                        FirstStrongDirection(
                          text: request.response!,
                          child: Text(
                            '${copy.coachPrefix}${request.response}',
                            style: MayosTypography.caption
                                .copyWith(color: c.textSecondary),
                          ),
                        ),
                      if (request.isPending)
                        MayosButton(
                          label: copy.cancelRequest,
                          variant: MayosButtonVariant.tertiary,
                          expand: false,
                          onPressed: _cancellingRequestId == request.requestId
                              ? null
                              : () => _cancelRequest(request),
                        ),
                    ],
                  ),
                ),
          ],
        ),
      ),
    );
  }

  Widget _noticesCard(BuildContext context) {
    if (_notices.isEmpty) {
      return const SizedBox.shrink();
    }
    final MayosThemeExtension c = MayosTheme.of(context);
    final AssignmentCopy copy = _copy;
    final int unread =
        _notices.where((AssignmentNotice notice) => notice.isUnread).length;
    return Padding(
      padding: const EdgeInsets.only(bottom: MayosSpacing.md),
      child: MayosCard(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: <Widget>[
            MayosSectionHeader(
              title: copy.notices,
              padding: EdgeInsets.zero,
              trailing: unread > 0
                  ? MayosButton(
                      label: copy.markAllRead,
                      variant: MayosButtonVariant.tertiary,
                      expand: false,
                      onPressed: _markNoticesRead,
                    )
                  : null,
            ),
            for (final AssignmentNotice notice in _notices)
              if (notice.programChangeSummary != null)
                Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: <Widget>[
                    ProgramChangeSummaryCard(
                      summary: notice.programChangeSummary!,
                      message: notice.message,
                      onViewProgram: _openProgram,
                    ),
                    Text(
                      '${notice.kind} · ${notice.createdAt}',
                      textDirection: TextDirection.ltr,
                      style: MayosTypography.caption
                          .copyWith(color: c.textMuted),
                    ),
                  ],
                )
              else
                ListTile(
                  dense: true,
                  contentPadding: EdgeInsets.zero,
                  leading: Icon(
                    notice.isUnread
                        ? Icons.notifications_active
                        : Icons.notifications_none,
                    color: notice.isUnread ? c.accent : c.textMuted,
                  ),
                  title: FirstStrongDirection(
                    text: notice.message,
                    child: Text(
                      notice.message,
                      textAlign: TextAlign.start,
                    ),
                  ),
                  subtitle: Text(
                    '${notice.kind} · ${notice.createdAt}',
                    textDirection: TextDirection.ltr,
                  ),
                ),
          ],
        ),
      ),
    );
  }

  Widget _checkInsCard(BuildContext context) {
    if (_checkIns.isEmpty) {
      return const SizedBox.shrink();
    }
    final MayosThemeExtension c = MayosTheme.of(context);
    final AssignmentCopy copy = _copy;
    return Padding(
      padding: const EdgeInsets.only(top: MayosSpacing.lg),
      child: MayosCard(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: <Widget>[
            MayosSectionHeader(title: copy.checkIns, padding: EdgeInsets.zero),
            for (final CheckIn checkIn in _checkIns)
              ListTile(
                dense: true,
                contentPadding: EdgeInsets.zero,
                leading: Icon(Icons.handshake_outlined, color: c.textSecondary),
                title: Text(
                  '${copy.isArabic ? '\u2066${checkIn.checkedInOn}\u2069' : checkIn.checkedInOn} · ${copy.checkInChannel(checkIn.channel)}',
                ),
                subtitle: Builder(
                  builder: (BuildContext context) {
                    final String subtitle = _checkInSubtitle(checkIn, copy);
                    return FirstStrongDirection(
                      text: subtitle,
                      child: Text(subtitle),
                    );
                  },
                ),
              ),
          ],
        ),
      ),
    );
  }

  String _checkInSubtitle(CheckIn checkIn, AssignmentCopy copy) => <String>[
        if (checkIn.coachUsername != null)
          checkIn.coachUsername == 'Former coach'
              ? copy.formerCoach
              : copy.coachUsername(checkIn.coachUsername!),
        if (checkIn.assignmentStatus == 'ended') copy.assignmentEndedStatus,
        if (checkIn.note != null && checkIn.note!.isNotEmpty) checkIn.note!,
      ].join(' · ');

  Widget _errorBanner(BuildContext context) {
    if (_error == null && _localError == null) {
      return const SizedBox.shrink();
    }
    return Padding(
      padding: const EdgeInsets.only(bottom: MayosSpacing.sm),
      child: FirstStrongDirection(
        text: _error == null
            ? _localError!
            : displayCopyOf(context).failureMessage(_error!),
        child: Text(
          _error == null
              ? _localError!
              : displayCopyOf(context).failureMessage(_error!),
          style: MayosTypography.bodySecondary
              .copyWith(color: MayosTheme.of(context).danger),
        ),
      ),
    );
  }

  Widget _activeAssignment(BuildContext context, Assignment assignment) {
    final MayosThemeExtension c = MayosTheme.of(context);
    final String specialization = assignment.coach.specialization.isEmpty
        ? _copy.yourCoach
        : assignment.coach.specialization;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: <Widget>[
        MayosSectionHeader(title: _copy.yourCoach),
        MayosCard(
          child: ListTile(
            contentPadding: EdgeInsets.zero,
            leading: Icon(Icons.person_outline, color: c.textSecondary),
            title: Text(assignment.coach.displayName),
            subtitle: FirstStrongDirection(
              text: specialization,
              child: Text(specialization),
            ),
          ),
        ),
        const SizedBox(height: MayosSpacing.sm),
        Text(
          _copy.activeAssignmentAccess,
          style: MayosTypography.bodySecondary.copyWith(color: c.textSecondary),
        ),
        const SizedBox(height: MayosSpacing.lg),
        MayosButton(
          label: _copy.leaveCoach,
          icon: Icons.link_off,
          variant: MayosButtonVariant.secondary,
          expand: false,
          loading: _ending,
          onPressed: _ending ? null : _end,
        ),
        _programRequestsCard(context),
      ],
    );
  }

  Widget _inviteSection(BuildContext context) {
    final MayosThemeExtension c = MayosTheme.of(context);
    final AssignmentInvitePreview? preview = _preview;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: <Widget>[
        MayosSectionHeader(title: _copy.myCoach),
        Text(
          _copy.inviteExplanation,
          style: MayosTypography.bodySecondary.copyWith(color: c.textSecondary),
        ),
        const SizedBox(height: MayosSpacing.md),
        MayosTextField(
          fieldKey: const Key('assignment_code_field'),
          controller: _code,
          autocorrect: false,
          enableSuggestions: false,
          onChanged: _onCodeChanged,
          label: _copy.inviteCodeFromCoach,
        ),
        const SizedBox(height: MayosSpacing.sm),
        MayosButton(
          label: _copy.previewAccess,
          loading: _previewing,
          onPressed: _previewing || _redeeming ? null : _previewCode,
        ),
        if (preview != null) ...<Widget>[
          const Divider(height: MayosSpacing.xxl),
          Text(
            _copy.coachWillBe(preview.coach.displayName),
            style:
                MayosTypography.sectionHeading.copyWith(color: c.textPrimary),
          ),
          if (preview.coach.bio.isNotEmpty) ...<Widget>[
            const SizedBox(height: MayosSpacing.xxs),
            Text(preview.coach.bio,
                style: MayosTypography.bodySecondary
                    .copyWith(color: c.textSecondary)),
          ],
          if (preview.coach.specialization.isNotEmpty) ...<Widget>[
            const SizedBox(height: MayosSpacing.xxs),
            Text(preview.coach.specialization,
                style: MayosTypography.caption.copyWith(color: c.textMuted)),
          ],
          const SizedBox(height: MayosSpacing.sm),
          Text(preview.access.description,
              style: MayosTypography.body.copyWith(color: c.textPrimary)),
          const SizedBox(height: MayosSpacing.md),
          MayosButton(
            label: _copy.acceptAssignment,
            icon: Icons.check,
            loading: _redeeming,
            onPressed: _redeeming ? null : _consent,
          ),
        ],
      ],
    );
  }

  @override
  Widget build(BuildContext context) {
    ref.watch(displayLanguageProvider);
    if (_loading) {
      return const Center(child: CircularProgressIndicator());
    }
    return ListView(
      padding: MayosSpacing.screen,
      children: <Widget>[
        _errorBanner(context),
        _noticesCard(context),
        if (_assignment != null)
          _activeAssignment(context, _assignment!)
        else
          _inviteSection(context),
        _checkInsCard(context),
      ],
    );
  }
}

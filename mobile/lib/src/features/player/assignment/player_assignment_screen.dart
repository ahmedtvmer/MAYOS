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
import '../../../core/theme/myos_spacing.dart';
import '../../../core/theme/myos_theme.dart';
import '../../../core/theme/myos_typography.dart';
import '../../../core/ui/first_strong_direction.dart';
import '../../../core/ui/myos_button.dart';
import '../../../core/ui/myos_card.dart';
import '../../../core/ui/myos_section_header.dart';
import '../../../core/ui/myos_text_field.dart';
import 'player_assignment_activity.dart';
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
  bool _markingNoticesRead = false;
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

  void _notifyAssignmentChanged(Assignment? assignment) {
    ref.read(playerAssignmentUpdateProvider.notifier).state =
        PlayerAssignmentUpdate(assignment);
  }

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
    await _loadContent();
  }

  Future<void> _refreshInPlace() async {
    setState(() {
      _error = null;
      _localError = null;
    });
    await _loadContent();
  }

  Future<void> _loadContent() async {
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
      _notifyAssignmentChanged(assignment);
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
          MyosButton(
            label: _copy.cancel,
            variant: MyosButtonVariant.tertiary,
            expand: false,
            onPressed: () => Navigator.of(context).pop(false),
          ),
          MyosButton(
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
      _notifyAssignmentChanged(null);
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
    setState(() => _markingNoticesRead = true);
    try {
      await ref.read(apiClientProvider).markPlayerNoticesRead();
      if (!mounted) return;
      await _refreshInPlace();
    } on ApiException catch (error) {
      if (!mounted) return;
      setState(() => _error = _rawFailure(error));
    } finally {
      if (mounted) setState(() => _markingNoticesRead = false);
    }
  }

  void _openProgram() {
    ref.read(playerShellTabProvider.notifier).state = PlayerShellTab.program.index;
    context.go(homePath);
  }

  Future<void> _requestChange() async {
    final ProgramRequest? created = await requestProgramChange(
      context,
      ref,
      onSubmitting: () => setState(() {
        _requestingChange = true;
        _requestError = null;
      }),
      onFinished: () {
        if (mounted) setState(() => _requestingChange = false);
      },
    );
    if (created == null || !mounted) return;
    setState(() {
      _programRequests = <ProgramRequest>[created, ..._programRequests];
    });
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
    final MyosThemeExtension c = MyosTheme.of(context);
    final AssignmentCopy copy = _copy;
    return Padding(
      padding: const EdgeInsets.only(top: MyosSpacing.lg),
      child: MyosCard(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: <Widget>[
            MyosSectionHeader(
              title: copy.programRequests,
              padding: EdgeInsets.zero,
              trailing: MyosButton(
                label: copy.requestChange,
                icon: Icons.add,
                variant: MyosButtonVariant.tertiary,
                expand: false,
                loading: _requestingChange,
                onPressed: _requestingChange ? null : _requestChange,
              ),
            ),
            if (_requestError != null) ...<Widget>[
              Text(
                displayCopyOf(context).failureMessage(_requestError!),
                style: MyosTypography.of(context).bodySecondary.copyWith(color: c.danger),
              ),
              const SizedBox(height: MyosSpacing.sm),
            ],
            if (_programRequests.isEmpty)
              Text(
                copy.noProgramRequests,
                style: MyosTypography.of(context).bodySecondary
                    .copyWith(color: c.textSecondary),
              )
            else
              for (final ProgramRequest request in _programRequests)
                Padding(
                  padding: const EdgeInsets.only(bottom: MyosSpacing.sm),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: <Widget>[
                      Row(
                        children: <Widget>[
                          Chip(label: Text(copy.requestStatus(request.status))),
                          const SizedBox(width: MyosSpacing.xs),
                          Expanded(
                            child: Text(
                              copy.programRequestDescription(
                                kind: request.kind,
                                exercise: request.exerciseName,
                                day: request.dayName,
                                replacement: request.replacementExerciseName,
                                frequency: request.desiredWeeklyFrequency,
                                preference: request.desiredSplitPreference,
                              ),
                              style: MyosTypography.of(context).body
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
                          style: MyosTypography.of(context).caption
                              .copyWith(color: c.textMuted),
                        ),
                      ),
                      if (request.hasResponse)
                        FirstStrongDirection(
                          text: request.response!,
                          child: Text(
                            '${copy.coachPrefix}${request.response}',
                            style: MyosTypography.of(context).caption
                                .copyWith(color: c.textSecondary),
                          ),
                        ),
                      if (request.isPending)
                        MyosButton(
                          label: copy.cancelRequest,
                          variant: MyosButtonVariant.tertiary,
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
    return Padding(
      padding: const EdgeInsets.only(bottom: MyosSpacing.md),
      child: PlayerAssignmentNoticesCard(
        notices: _notices,
        copy: _copy,
        actions: PlayerNoticeActions(
          onMarkAllRead: _markNoticesRead,
          onViewProgram: _openProgram,
          markingRead: _markingNoticesRead,
        ),
      ),
    );
  }

  Widget _checkInsCard(BuildContext context) {
    if (_checkIns.isEmpty) {
      return const SizedBox.shrink();
    }
    return Padding(
      padding: const EdgeInsets.only(top: MyosSpacing.lg),
      child: PlayerAssignmentCheckInsCard(
        checkIns: _checkIns,
        copy: _copy,
      ),
    );
  }

  Widget _errorBanner(BuildContext context) {
    if (_error == null && _localError == null) {
      return const SizedBox.shrink();
    }
    return Padding(
      padding: const EdgeInsets.only(bottom: MyosSpacing.sm),
      child: FirstStrongDirection(
        text: _error == null
            ? _localError!
            : displayCopyOf(context).failureMessage(_error!),
        child: Text(
          _error == null
              ? _localError!
              : displayCopyOf(context).failureMessage(_error!),
          style: MyosTypography.of(context).bodySecondary
              .copyWith(color: MyosTheme.of(context).danger),
        ),
      ),
    );
  }

  Widget _activeAssignment(BuildContext context, Assignment assignment) {
    final MyosThemeExtension c = MyosTheme.of(context);
    final String specialization = assignment.coach.specialization.isEmpty
        ? _copy.yourCoach
        : assignment.coach.specialization;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: <Widget>[
        MyosSectionHeader(title: _copy.yourCoach),
        MyosCard(
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
        const SizedBox(height: MyosSpacing.sm),
        Text(
          _copy.activeAssignmentAccess,
          style: MyosTypography.of(context).bodySecondary.copyWith(color: c.textSecondary),
        ),
        const SizedBox(height: MyosSpacing.lg),
        MyosButton(
          label: _copy.leaveCoach,
          icon: Icons.link_off,
          variant: MyosButtonVariant.secondary,
          expand: false,
          loading: _ending,
          onPressed: _ending ? null : _end,
        ),
        _programRequestsCard(context),
      ],
    );
  }

  Widget _inviteSection(BuildContext context) {
    final MyosThemeExtension c = MyosTheme.of(context);
    final AssignmentInvitePreview? preview = _preview;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: <Widget>[
        MyosSectionHeader(title: _copy.myCoach),
        Text(
          _copy.inviteExplanation,
          style: MyosTypography.of(context).bodySecondary.copyWith(color: c.textSecondary),
        ),
        const SizedBox(height: MyosSpacing.md),
        MyosTextField(
          fieldKey: const Key('assignment_code_field'),
          controller: _code,
          autocorrect: false,
          enableSuggestions: false,
          onChanged: _onCodeChanged,
          label: _copy.inviteCodeFromCoach,
        ),
        const SizedBox(height: MyosSpacing.sm),
        MyosButton(
          label: _copy.previewAccess,
          loading: _previewing,
          onPressed: _previewing || _redeeming ? null : _previewCode,
        ),
        if (preview != null) ...<Widget>[
          const Divider(height: MyosSpacing.xxl),
          Text(
            _copy.coachWillBe(preview.coach.displayName),
            style:
                MyosTypography.of(context).sectionHeading.copyWith(color: c.textPrimary),
          ),
          if (preview.coach.bio.isNotEmpty) ...<Widget>[
            const SizedBox(height: MyosSpacing.xxs),
            Text(preview.coach.bio,
                style: MyosTypography.of(context).bodySecondary
                    .copyWith(color: c.textSecondary)),
          ],
          if (preview.coach.specialization.isNotEmpty) ...<Widget>[
            const SizedBox(height: MyosSpacing.xxs),
            Text(preview.coach.specialization,
                style: MyosTypography.of(context).caption.copyWith(color: c.textMuted)),
          ],
          const SizedBox(height: MyosSpacing.sm),
          Text(preview.access.description,
              style: MyosTypography.of(context).body.copyWith(color: c.textPrimary)),
          const SizedBox(height: MyosSpacing.sm),
          Text(
            _copy.rosterAiDisclosure,
            style: MyosTypography.of(context).body.copyWith(color: c.textPrimary),
          ),
          const SizedBox(height: MyosSpacing.md),
          MyosButton(
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
      padding: MyosSpacing.screen,
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

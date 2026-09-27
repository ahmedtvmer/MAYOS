import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api_client.dart';
import '../../../core/connectivity_message.dart';
import '../../../core/models.dart';
import '../../../core/theme/mayos_spacing.dart';
import '../../../core/theme/mayos_theme.dart';
import '../../../core/theme/mayos_typography.dart';
import '../../../core/ui/mayos_button.dart';
import '../../../core/ui/mayos_card.dart';
import '../../../core/ui/mayos_section_header.dart';
import '../../../core/ui/mayos_text_field.dart';
import '../../../providers.dart';

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
  String? _error;
  Assignment? _assignment;
  List<AssignmentNotice> _notices = const <AssignmentNotice>[];
  List<ProgramRequest> _programRequests = const <ProgramRequest>[];
  List<CheckIn> _checkIns = const <CheckIn>[];
  AssignmentInvitePreview? _preview;
  String? _previewToken;
  bool _requestingChange = false;
  String? _cancellingRequestId;
  String? _requestError;

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
        _error = error.message;
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
    });
  }

  Future<void> _previewCode() async {
    final String token = _code.text.trim();
    if (token.length < 10) {
      setState(() => _error = 'Enter the invite code you received.');
      return;
    }
    setState(() {
      _previewing = true;
      _error = null;
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
        _error = error.message;
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
        const SnackBar(content: Text('Assignment accepted.')),
      );
    } on ApiException catch (error) {
      if (!mounted) return;
      setState(() {
        _redeeming = false;
        _error = error.message;
      });
    }
  }

  Future<void> _end() async {
    final bool? confirmed = await showDialog<bool>(
      context: context,
      builder: (BuildContext context) => AlertDialog(
        title: const Text('End assignment?'),
        content: const Text(
            'Your coach will immediately lose access to your training history.'),
        actions: <Widget>[
          MayosButton(
            label: 'Cancel',
            variant: MayosButtonVariant.tertiary,
            expand: false,
            onPressed: () => Navigator.of(context).pop(false),
          ),
          MayosButton(
            label: 'End assignment',
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
    });
    try {
      await ref.read(apiClientProvider).endMyAssignment();
      if (!mounted) return;
      setState(() {
        _ending = false;
        _assignment = null;
      });
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Assignment ended.')),
      );
    } on ApiException catch (error) {
      if (!mounted) return;
      setState(() {
        _ending = false;
        _error = error.message;
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
      setState(() => _error = error.message);
    }
  }

  Future<void> _requestChange() async {
    final _ProgramRequestDraft? draft = await showDialog<_ProgramRequestDraft>(
      context: context,
      builder: (BuildContext context) => const _ProgramRequestDialog(),
    );
    if (draft == null || !mounted) return;
    setState(() {
      _requestingChange = true;
      _requestError = null;
    });
    try {
      final ProgramRequest created =
          await ref.read(apiClientProvider).createPlayerProgramRequest(
                kind: draft.kind,
                dayName: draft.dayName,
                exerciseId: draft.exerciseId,
                replacementExerciseId: draft.replacementExerciseId,
                desiredWeeklyFrequency: draft.desiredWeeklyFrequency,
                desiredSplitPreference: draft.desiredSplitPreference,
                reason: draft.reason,
              );
      if (!mounted) return;
      setState(() {
        _requestingChange = false;
        _programRequests = <ProgramRequest>[created, ..._programRequests];
      });
    } on ApiException catch (error) {
      if (!mounted) return;
      setState(() {
        _requestingChange = false;
        _requestError = mutationFailureMessage(error);
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
        _requestError = mutationFailureMessage(error);
      });
    }
  }

  Widget _programRequestsCard(BuildContext context) {
    final MayosThemeExtension c = MayosTheme.of(context);
    return Padding(
      padding: const EdgeInsets.only(top: MayosSpacing.lg),
      child: MayosCard(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: <Widget>[
            MayosSectionHeader(
              title: 'Program requests',
              padding: EdgeInsets.zero,
              trailing: MayosButton(
                label: 'Request a change',
                icon: Icons.add,
                variant: MayosButtonVariant.tertiary,
                expand: false,
                loading: _requestingChange,
                onPressed: _requestingChange ? null : _requestChange,
              ),
            ),
            if (_requestError != null) ...<Widget>[
              Text(
                _requestError!,
                style: MayosTypography.bodySecondary.copyWith(color: c.danger),
              ),
              const SizedBox(height: MayosSpacing.sm),
            ],
            if (_programRequests.isEmpty)
              Text(
                'No program requests yet.',
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
                          Chip(label: Text(request.statusLabel)),
                          const SizedBox(width: MayosSpacing.xs),
                          Expanded(
                            child: Text(
                              request.description,
                              style: MayosTypography.body
                                  .copyWith(color: c.textPrimary),
                            ),
                          ),
                        ],
                      ),
                      Text(
                        'Reason: ${request.reason}',
                        style: MayosTypography.caption
                            .copyWith(color: c.textMuted),
                      ),
                      if (request.hasResponse)
                        Text(
                          'Coach: ${request.response}',
                          style: MayosTypography.caption
                              .copyWith(color: c.textSecondary),
                        ),
                      if (request.isPending)
                        MayosButton(
                          label: 'Cancel request',
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
    final int unread =
        _notices.where((AssignmentNotice notice) => notice.isUnread).length;
    return Padding(
      padding: const EdgeInsets.only(bottom: MayosSpacing.md),
      child: MayosCard(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: <Widget>[
            MayosSectionHeader(
              title: 'Notices',
              padding: EdgeInsets.zero,
              trailing: unread > 0
                  ? MayosButton(
                      label: 'Mark all read',
                      variant: MayosButtonVariant.tertiary,
                      expand: false,
                      onPressed: _markNoticesRead,
                    )
                  : null,
            ),
            for (final AssignmentNotice notice in _notices)
              ListTile(
                dense: true,
                contentPadding: EdgeInsets.zero,
                leading: Icon(
                  notice.isUnread
                      ? Icons.notifications_active
                      : Icons.notifications_none,
                  color: notice.isUnread ? c.accent : c.textMuted,
                ),
                title: Text(notice.message),
                subtitle: Text('${notice.kind} · ${notice.createdAt}'),
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
    return Padding(
      padding: const EdgeInsets.only(top: MayosSpacing.lg),
      child: MayosCard(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: <Widget>[
            MayosSectionHeader(title: 'Check-ins', padding: EdgeInsets.zero),
            for (final CheckIn checkIn in _checkIns)
              ListTile(
                dense: true,
                contentPadding: EdgeInsets.zero,
                leading: Icon(Icons.handshake_outlined, color: c.textSecondary),
                title: Text('${checkIn.checkedInOn} · ${checkIn.channelLabel}'),
                subtitle: Text(
                  <String>[
                    if (checkIn.coachUsername != null)
                      checkIn.coachUsername == 'Former coach'
                          ? 'Former coach'
                          : 'Coach ${checkIn.coachUsername}',
                    if (checkIn.assignmentStatus == 'ended') 'assignment ended',
                    if (checkIn.note != null && checkIn.note!.isNotEmpty)
                      checkIn.note!,
                  ].join(' · '),
                ),
              ),
          ],
        ),
      ),
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

  Widget _activeAssignment(BuildContext context, Assignment assignment) {
    final MayosThemeExtension c = MayosTheme.of(context);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: <Widget>[
        const MayosSectionHeader(title: 'Your coach'),
        MayosCard(
          child: ListTile(
            contentPadding: EdgeInsets.zero,
            leading: Icon(Icons.person_outline, color: c.textSecondary),
            title: Text(assignment.coach.displayName),
            subtitle: Text(
              assignment.coach.specialization.isEmpty
                  ? 'Coaching assignment active'
                  : assignment.coach.specialization,
            ),
          ),
        ),
        const SizedBox(height: MayosSpacing.sm),
        Text(
          'While this assignment is active, your coach can view your current and '
          'historical training data. Ending it revokes that access immediately.',
          style: MayosTypography.bodySecondary.copyWith(color: c.textSecondary),
        ),
        const SizedBox(height: MayosSpacing.lg),
        MayosButton(
          label: 'End assignment',
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
        const MayosSectionHeader(title: 'Coach assignment'),
        Text(
          'Enter a coach invite code. Your coach can only see your training data '
          'after you accept, and access ends when either of you ends the assignment.',
          style: MayosTypography.bodySecondary.copyWith(color: c.textSecondary),
        ),
        const SizedBox(height: MayosSpacing.md),
        MayosTextField(
          fieldKey: const Key('assignment_code_field'),
          controller: _code,
          autocorrect: false,
          enableSuggestions: false,
          onChanged: _onCodeChanged,
          label: 'Invite code',
        ),
        const SizedBox(height: MayosSpacing.sm),
        MayosButton(
          label: 'Preview access',
          loading: _previewing,
          onPressed: _previewing || _redeeming ? null : _previewCode,
        ),
        if (preview != null) ...<Widget>[
          const Divider(height: MayosSpacing.xxl),
          Text(
            'Your coach will be ${preview.coach.displayName}',
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
            label: 'Accept assignment',
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

/// A locally assembled player program-request payload awaiting submission.
class _ProgramRequestDraft {
  const _ProgramRequestDraft({
    required this.kind,
    required this.reason,
    this.dayName,
    this.exerciseId,
    this.replacementExerciseId,
    this.desiredWeeklyFrequency,
    this.desiredSplitPreference,
  });

  final String kind;
  final String reason;
  final String? dayName;
  final String? exerciseId;
  final String? replacementExerciseId;
  final int? desiredWeeklyFrequency;
  final String? desiredSplitPreference;
}

/// The create-request dialog. It owns its controllers so they are disposed
/// only after the route fully leaves the tree.
class _ProgramRequestDialog extends StatefulWidget {
  const _ProgramRequestDialog();

  @override
  State<_ProgramRequestDialog> createState() => _ProgramRequestDialogState();
}

class _ProgramRequestDialogState extends State<_ProgramRequestDialog> {
  final TextEditingController _day = TextEditingController();
  final TextEditingController _exercise = TextEditingController();
  final TextEditingController _replacement = TextEditingController();
  final TextEditingController _preference = TextEditingController();
  final TextEditingController _reason = TextEditingController();
  String _kind = 'exercise_substitution';
  int _frequency = 4;
  String? _localError;

  @override
  void dispose() {
    _day.dispose();
    _exercise.dispose();
    _replacement.dispose();
    _preference.dispose();
    _reason.dispose();
    super.dispose();
  }

  void _submit() {
    final String reason = _reason.text.trim();
    if (reason.isEmpty) {
      setState(() => _localError = 'A reason is required.');
      return;
    }
    if (_kind == 'exercise_substitution' &&
        (_day.text.trim().isEmpty ||
            _exercise.text.trim().isEmpty ||
            _replacement.text.trim().isEmpty)) {
      setState(() =>
          _localError = 'Pick the day, the exercise, and its replacement.');
      return;
    }
    Navigator.of(context).pop(
      _ProgramRequestDraft(
        kind: _kind,
        reason: reason,
        dayName: _kind == 'exercise_substitution' ? _day.text.trim() : null,
        exerciseId:
            _kind == 'exercise_substitution' ? _exercise.text.trim() : null,
        replacementExerciseId:
            _kind == 'exercise_substitution' ? _replacement.text.trim() : null,
        desiredWeeklyFrequency: _kind == 'split_change' ? _frequency : null,
        desiredSplitPreference:
            _kind == 'split_change' ? _preference.text.trim() : null,
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final MayosThemeExtension c = MayosTheme.of(context);
    return AlertDialog(
      title: const Text('Request a program change'),
      content: SingleChildScrollView(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: <Widget>[
            DropdownButtonFormField<String>(
              key: const Key('program_request_kind_field'),
              initialValue: _kind,
              decoration: const InputDecoration(
                  labelText: 'Request type', border: OutlineInputBorder()),
              items: const <DropdownMenuItem<String>>[
                DropdownMenuItem<String>(
                    value: 'exercise_substitution',
                    child: Text('Exercise substitution')),
                DropdownMenuItem<String>(
                    value: 'split_change', child: Text('Split change')),
              ],
              onChanged: (String? value) => setState(() {
                _kind = value ?? _kind;
                _localError = null;
              }),
            ),
            const SizedBox(height: MayosSpacing.md),
            if (_kind == 'exercise_substitution') ...<Widget>[
              MayosTextField(
                fieldKey: const Key('program_request_day_field'),
                controller: _day,
                label: 'Day name',
              ),
              const SizedBox(height: MayosSpacing.md),
              MayosTextField(
                fieldKey: const Key('program_request_exercise_field'),
                controller: _exercise,
                label: 'Current exercise id',
              ),
              const SizedBox(height: MayosSpacing.md),
              MayosTextField(
                fieldKey: const Key('program_request_replacement_field'),
                controller: _replacement,
                label: 'Replacement exercise id',
              ),
            ] else ...<Widget>[
              DropdownButtonFormField<int>(
                key: const Key('program_request_frequency_field'),
                initialValue: _frequency,
                decoration: const InputDecoration(
                    labelText: 'Days per week', border: OutlineInputBorder()),
                items: <DropdownMenuItem<int>>[
                  for (int day = 1; day <= 5; day++)
                    DropdownMenuItem<int>(value: day, child: Text('$day')),
                ],
                onChanged: (int? value) =>
                    setState(() => _frequency = value ?? _frequency),
              ),
              const SizedBox(height: MayosSpacing.md),
              MayosTextField(
                fieldKey: const Key('program_request_split_field'),
                controller: _preference,
                label: 'Split preference (optional)',
              ),
            ],
            const SizedBox(height: MayosSpacing.md),
            MayosTextField(
              fieldKey: const Key('program_request_reason_field'),
              controller: _reason,
              maxLines: 2,
              label: 'Reason',
            ),
            if (_localError != null) ...<Widget>[
              const SizedBox(height: MayosSpacing.sm),
              Text(
                _localError!,
                style: MayosTypography.bodySecondary.copyWith(color: c.danger),
              ),
            ],
          ],
        ),
      ),
      actions: <Widget>[
        MayosButton(
          label: 'Cancel',
          variant: MayosButtonVariant.tertiary,
          expand: false,
          onPressed: () => Navigator.of(context).pop(),
        ),
        MayosButton(
          key: const Key('program_request_submit_button'),
          label: 'Submit request',
          expand: false,
          onPressed: _submit,
        ),
      ],
    );
  }
}

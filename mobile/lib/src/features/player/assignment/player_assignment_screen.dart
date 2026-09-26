import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api_client.dart';
import '../../../core/models.dart';
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
      final List<Object?> results = await Future.wait<Object?>(
          <Future<Object?>>[
            api.myAssignment(),
            api.playerNotices(),
            api.playerProgramRequests(),
          ]);
      if (!mounted) return;
      setState(() {
        _assignment = results[0] as Assignment?;
        _notices = results[1] as List<AssignmentNotice>;
        _programRequests = results[2] as List<ProgramRequest>;
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
          TextButton(
            onPressed: () => Navigator.of(context).pop(false),
            child: const Text('Cancel'),
          ),
          FilledButton(
            onPressed: () => Navigator.of(context).pop(true),
            child: const Text('End assignment'),
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
    final _ProgramRequestDraft? draft =
        await showDialog<_ProgramRequestDraft>(
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
        _requestError = error.message;
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
        _requestError = error.message;
      });
    }
  }

  Widget _programRequestsCard(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(top: 20),
      child: Card(
        child: Padding(
          padding: const EdgeInsets.all(16),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: <Widget>[
              Row(
                mainAxisAlignment: MainAxisAlignment.spaceBetween,
                children: <Widget>[
                  Expanded(
                    child: Text('Program requests',
                        style: Theme.of(context).textTheme.titleMedium),
                  ),
                  TextButton.icon(
                    onPressed: _requestingChange ? null : _requestChange,
                    icon: _requestingChange
                        ? const SizedBox(
                            height: 16,
                            width: 16,
                            child: CircularProgressIndicator(strokeWidth: 2),
                          )
                        : const Icon(Icons.add),
                    label: const Text('Request a change'),
                  ),
                ],
              ),
              if (_requestError != null) ...<Widget>[
                Text(
                  _requestError!,
                  style: TextStyle(color: Theme.of(context).colorScheme.error),
                ),
                const SizedBox(height: 12),
              ],
              if (_programRequests.isEmpty)
                const Text('No program requests yet.')
              else
                for (final ProgramRequest request in _programRequests)
                  Padding(
                    padding: const EdgeInsets.only(bottom: 12),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: <Widget>[
                        Row(
                          children: <Widget>[
                            Chip(label: Text(request.statusLabel)),
                            const SizedBox(width: 8),
                            Expanded(
                              child:
                                  Text(request.description),
                            ),
                          ],
                        ),
                        Text('Reason: ${request.reason}'),
                        if (request.hasResponse)
                          Text('Coach: ${request.response}'),
                        if (request.isPending)
                          TextButton(
                            onPressed: _cancellingRequestId == request.requestId
                                ? null
                                : () => _cancelRequest(request),
                            child: const Text('Cancel request'),
                          ),
                      ],
                    ),
                  ),
            ],
          ),
        ),
      ),
    );
  }

  Widget _noticesCard(BuildContext context) {
    if (_notices.isEmpty) {
      return const SizedBox.shrink();
    }
    final int unread =
        _notices.where((AssignmentNotice notice) => notice.isUnread).length;
    return Padding(
      padding: const EdgeInsets.only(bottom: 16),
      child: Card(
        child: Padding(
          padding: const EdgeInsets.all(16),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: <Widget>[
              Row(
                mainAxisAlignment: MainAxisAlignment.spaceBetween,
                children: <Widget>[
                  Text('Notices',
                      style: Theme.of(context).textTheme.titleMedium),
                  if (unread > 0)
                    TextButton(
                      onPressed: _markNoticesRead,
                      child: const Text('Mark all read'),
                    ),
                ],
              ),
              for (final AssignmentNotice notice in _notices)
                ListTile(
                  dense: true,
                  contentPadding: EdgeInsets.zero,
                  leading: Icon(notice.isUnread
                      ? Icons.notifications_active
                      : Icons.notifications_none),
                  title: Text(notice.message),
                  subtitle: Text('${notice.kind} · ${notice.createdAt}'),
                ),
            ],
          ),
        ),
      ),
    );
  }

  Widget _errorBanner(BuildContext context) {
    if (_error == null) {
      return const SizedBox.shrink();
    }
    return Padding(
      padding: const EdgeInsets.only(bottom: 12),
      child: Text(
        _error!,
        style: TextStyle(color: Theme.of(context).colorScheme.error),
      ),
    );
  }

  Widget _activeAssignment(BuildContext context, Assignment assignment) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: <Widget>[
        Text('Your coach', style: Theme.of(context).textTheme.titleLarge),
        const SizedBox(height: 8),
        Card(
          child: ListTile(
            leading: const Icon(Icons.person_outline),
            title: Text(assignment.coach.displayName),
            subtitle: Text(
              assignment.coach.specialization.isEmpty
                  ? 'Coaching assignment active'
                  : assignment.coach.specialization,
            ),
          ),
        ),
        const SizedBox(height: 8),
        const Text(
          'While this assignment is active, your coach can view your current and '
          'historical training data. Ending it revokes that access immediately.',
        ),
        const SizedBox(height: 20),
        OutlinedButton.icon(
          onPressed: _ending ? null : _end,
          icon: const Icon(Icons.link_off),
          label: _ending
              ? const SizedBox(
                  height: 18,
                  width: 18,
                  child: CircularProgressIndicator(strokeWidth: 2),
                )
              : const Text('End assignment'),
        ),
        _programRequestsCard(context),
      ],
    );
  }

  Widget _inviteSection(BuildContext context) {
    final AssignmentInvitePreview? preview = _preview;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: <Widget>[
        Text('Coach assignment',
            style: Theme.of(context).textTheme.titleLarge),
        const SizedBox(height: 8),
        const Text(
          'Enter a coach invite code. Your coach can only see your training data '
          'after you accept, and access ends when either of you ends the assignment.',
        ),
        const SizedBox(height: 16),
        TextField(
          key: const Key('assignment_code_field'),
          controller: _code,
          autocorrect: false,
          enableSuggestions: false,
          onChanged: _onCodeChanged,
          decoration: const InputDecoration(
            labelText: 'Invite code',
            border: OutlineInputBorder(),
          ),
        ),
        const SizedBox(height: 12),
        FilledButton(
          onPressed: _previewing || _redeeming ? null : _previewCode,
          child: _previewing
              ? const SizedBox(
                  height: 20,
                  width: 20,
                  child: CircularProgressIndicator(strokeWidth: 2),
                )
              : const Text('Preview access'),
        ),
        if (preview != null) ...<Widget>[
          const Divider(height: 32),
          Text(
            'Your coach will be ${preview.coach.displayName}',
            style: Theme.of(context).textTheme.titleMedium,
          ),
          if (preview.coach.bio.isNotEmpty) ...<Widget>[
            const SizedBox(height: 4),
            Text(preview.coach.bio),
          ],
          if (preview.coach.specialization.isNotEmpty) ...<Widget>[
            const SizedBox(height: 4),
            Text(preview.coach.specialization),
          ],
          const SizedBox(height: 12),
          Text(preview.access.description),
          const SizedBox(height: 16),
          FilledButton.icon(
            onPressed: _redeeming ? null : _consent,
            icon: _redeeming
                ? const SizedBox(
                    height: 18,
                    width: 18,
                    child: CircularProgressIndicator(strokeWidth: 2),
                  )
                : const Icon(Icons.check),
            label: const Text('Accept assignment'),
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
      padding: const EdgeInsets.all(16),
      children: <Widget>[
        _errorBanner(context),
        _noticesCard(context),
        if (_assignment != null)
          _activeAssignment(context, _assignment!)
        else
          _inviteSection(context),
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
            const SizedBox(height: 16),
            if (_kind == 'exercise_substitution') ...<Widget>[
              TextField(
                key: const Key('program_request_day_field'),
                controller: _day,
                decoration: const InputDecoration(
                    labelText: 'Day name', border: OutlineInputBorder()),
              ),
              const SizedBox(height: 16),
              TextField(
                key: const Key('program_request_exercise_field'),
                controller: _exercise,
                decoration: const InputDecoration(
                    labelText: 'Current exercise id',
                    border: OutlineInputBorder()),
              ),
              const SizedBox(height: 16),
              TextField(
                key: const Key('program_request_replacement_field'),
                controller: _replacement,
                decoration: const InputDecoration(
                    labelText: 'Replacement exercise id',
                    border: OutlineInputBorder()),
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
              const SizedBox(height: 16),
              TextField(
                key: const Key('program_request_split_field'),
                controller: _preference,
                decoration: const InputDecoration(
                    labelText: 'Split preference (optional)',
                    border: OutlineInputBorder()),
              ),
            ],
            const SizedBox(height: 16),
            TextField(
              key: const Key('program_request_reason_field'),
              controller: _reason,
              maxLines: 2,
              decoration: const InputDecoration(
                  labelText: 'Reason', border: OutlineInputBorder()),
            ),
            if (_localError != null) ...<Widget>[
              const SizedBox(height: 12),
              Text(
                _localError!,
                style: TextStyle(color: Theme.of(context).colorScheme.error),
              ),
            ],
          ],
        ),
      ),
      actions: <Widget>[
        TextButton(
          onPressed: () => Navigator.of(context).pop(),
          child: const Text('Cancel'),
        ),
        FilledButton(
          key: const Key('program_request_submit_button'),
          onPressed: _submit,
          child: const Text('Submit request'),
        ),
      ],
    );
  }
}

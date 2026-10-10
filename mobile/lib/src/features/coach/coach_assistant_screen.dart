import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api_client.dart';
import '../../core/app_failure.dart';
import '../../core/chat_models.dart';
import '../../core/connectivity_message.dart';
import '../../core/display_language/copy_context.dart';
import '../../core/display_language/feature_copy_context.dart';
import '../../core/models.dart';
import '../../core/theme/mayos_spacing.dart';
import '../../core/theme/mayos_theme.dart';
import '../../core/theme/mayos_typography.dart';
import '../../core/ui/mayos_markdown.dart';
import '../../core/ui/mayos_scaffold.dart';
import '../../core/ui/mayos_text_field.dart';
import '../../core/ui/first_strong_direction.dart';
import '../../providers.dart';
import 'coach_assistant_state.dart';

/// The coach assistant for ONE selected player (#45, ADR 049).
///
/// The transcript lives only in [coachAssistantControllerProvider]: the last
/// turns are sent with every question, nothing is written to disk, and the
/// transcript is dropped when the player changes, the assignment ends, the
/// session ends, or the app closes. The entry point exists only while
/// `GET /auth/me` reports `coach_ai_enabled`; a 404 here means the operator
/// turned the feature off after the screen was opened, a 403 that the player
/// is no longer assigned.
class CoachAssistantScreen extends ConsumerStatefulWidget {
  const CoachAssistantScreen({super.key, required this.entry});

  final CoachRosterEntry entry;

  @override
  ConsumerState<CoachAssistantScreen> createState() =>
      _CoachAssistantScreenState();
}

class _CoachAssistantScreenState extends ConsumerState<CoachAssistantScreen> {
  final TextEditingController _question = TextEditingController();
  bool _sending = false;
  FailureMessage? _error;
  String _draftAnswer = '';

  String get _assignmentId => widget.entry.assignmentId;

  @override
  void initState() {
    super.initState();
    // One player at a time: selecting this player replaces any other
    // transcript. Deferred off the first frame so the provider change never
    // lands during the build that mounts this route.
    Future<void>.microtask(_selectPlayer);
  }

  /// Selects the player, then re-checks the roster: a revocation can land
  /// while the coach's roster view is stale, and a transcript for a player who
  /// is no longer assigned must never be shown (issue #45).
  Future<void> _selectPlayer() async {
    if (!mounted) return;
    final CoachAssistantController controller =
        ref.read(coachAssistantControllerProvider.notifier);
    controller.openFor(_assignmentId);
    try {
      final List<CoachRosterEntry> roster =
          await ref.read(apiClientProvider).coachAssignments();
      if (!mounted) return;
      final bool stillAssigned = roster
          .any((CoachRosterEntry row) => row.assignmentId == _assignmentId);
      if (!stillAssigned) {
        controller.clearFor(_assignmentId);
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text(coachCopyOf(context).playerAssignmentEnded)),
        );
        Navigator.of(context).pop();
      }
    } on ApiException {
      // A failed re-check changes nothing: the service still gates every send
      // with its own 403.
    }
  }

  @override
  void dispose() {
    _question.dispose();
    super.dispose();
  }

  Future<void> _send() async {
    final String question = _question.text.trim();
    if (question.isEmpty || _sending) {
      return;
    }
    final List<CoachAssistantTurn> history = ref
        .read(coachAssistantControllerProvider.notifier)
        .historyFor(_assignmentId);
    _beginSending();
    try {
      await _streamAssistant(question, history);
    } on ApiException catch (failure) {
      _showApiFailure(failure);
    }
  }

  void _beginSending() {
    setState(() {
      _sending = true;
      _error = null;
      _draftAnswer = '';
    });
  }

  Future<void> _streamAssistant(
    String question,
    List<CoachAssistantTurn> history,
  ) async {
    ChatDone? completion;
    await for (final ChatStreamEvent event
        in ref.read(apiClientProvider).streamCoachAssistant(
              assignmentId: _assignmentId,
              question: question,
              history: history,
            )) {
      if (!mounted) return;
      if (event is ChatToken) {
        setState(() => _draftAnswer += event.token);
      } else if (event is ChatDone) {
        completion = event;
      } else if (event is ChatError) {
        _showStreamError(event);
        return;
      }
    }
    if (completion == null) {
      throw const ApiException(
        'The assistant stream ended before the answer was complete.',
        failureMessage: AppFailureMessage(
          AppFailureId.assistantDidNotFinish,
          'The assistant stream ended before the answer was complete.',
        ),
      );
    }
    _recordCompletedExchange(question, completion.responseContent);
  }

  void _recordCompletedExchange(String question, String answer) {
    _question.clear();
    ref.read(coachAssistantControllerProvider.notifier).recordExchange(
          _assignmentId,
          question: question,
          answer: answer,
        );
    setState(() {
      _sending = false;
      _draftAnswer = '';
    });
  }

  void _showStreamError(ChatError failure) {
    setState(() {
      _sending = false;
      _draftAnswer = '';
      _error = ServerFailureMessage(
        failure.detail,
        messageCode: failure.messageCode,
        messageParams: failure.messageParams,
        messageFallback: failure.messageFallback,
      );
    });
  }

  void _showApiFailure(ApiException failure) {
    if (!mounted) return;
    if (failure.statusCode == 403) {
      _leaveRevokedAssignment();
      return;
    }
    if (failure.statusCode == 404) {
      unawaited(ref.read(authControllerProvider.notifier).refreshAccount());
    }
    setState(() {
      _sending = false;
      _draftAnswer = '';
      _error = apiFailureMessage(failure);
    });
  }

  void _leaveRevokedAssignment() {
    ref.read(coachAssistantControllerProvider.notifier).clearFor(_assignmentId);
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(content: Text(coachCopyOf(context).playerAssignmentEnded)),
    );
    Navigator.of(context).pop();
  }

  @override
  Widget build(BuildContext context) {
    final CoachAssistantTranscript? transcript =
        ref.watch(coachAssistantControllerProvider);
    final List<CoachAssistantTurn> turns =
        transcript != null && transcript.assignmentId == _assignmentId
            ? transcript.turns
            : const <CoachAssistantTurn>[];
    final MayosThemeExtension c = MayosTheme.of(context);
    final copy = coachCopyOf(context);
    return MayosScaffold(
      title: copy.assistant,
      showBack: true,
      body: Column(
        children: <Widget>[
          Expanded(
            child: turns.isEmpty && !_sending
                ? _emptyState(c)
                : _transcript(turns, c),
          ),
          if (_error != null) _errorBanner(c),
          _note(c),
          _composer(c),
        ],
      ),
    );
  }

  Widget _emptyState(MayosThemeExtension c) {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(MayosSpacing.xl),
        child: Text(
          coachCopyOf(context).assistantNoHistory(widget.entry.playerUsername),
          textAlign: TextAlign.center,
          style: MayosTypography.of(context).bodySecondary.copyWith(color: c.textSecondary),
        ),
      ),
    );
  }

  Widget _transcript(List<CoachAssistantTurn> turns, MayosThemeExtension c) {
    return ListView.builder(
      key: const Key('coach_assistant_transcript'),
      padding: const EdgeInsets.all(MayosSpacing.md),
      itemCount: turns.length + (_sending ? 1 : 0),
      itemBuilder: (BuildContext context, int index) {
        if (index >= turns.length) {
          return _bubble(role: 'assistant', child: _liveDraft(c));
        }
        final CoachAssistantTurn turn = turns[index];
        return _bubble(
          role: turn.role,
          child: turn.role == 'assistant'
              ? MayosMarkdown(
                  source: turn.content,
                  bodyStyle: MayosTypography.of(context).bodySecondary,
                )
              : FirstStrongDirection(
                  text: turn.content,
                  child: Text(
                    turn.content,
                    style: MayosTypography.of(context).bodySecondary.copyWith(
                      color: c.onAccent,
                    ),
                  ),
                ),
        );
      },
    );
  }

  Widget _liveDraft(MayosThemeExtension c) {
    if (_draftAnswer.isEmpty) {
      return Row(
        mainAxisSize: MainAxisSize.min,
        children: <Widget>[
          const SizedBox(
            height: 14,
            width: 14,
            child: CircularProgressIndicator(strokeWidth: 2),
          ),
          const SizedBox(width: MayosSpacing.sm),
          Text(coachCopyOf(context).assistantThinking,
              style: MayosTypography.of(context).bodySecondary
                  .copyWith(color: c.textSecondary)),
        ],
      );
    }
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      mainAxisSize: MainAxisSize.min,
      children: <Widget>[
        MayosMarkdown(
          key: const Key('coach_assistant_live_draft'),
          source: _draftAnswer,
          bodyStyle: MayosTypography.of(context).bodySecondary,
        ),
        const SizedBox(height: MayosSpacing.xs),
        const SizedBox(
          height: 14,
          width: 14,
          child: CircularProgressIndicator(strokeWidth: 2),
        ),
      ],
    );
  }

  Widget _bubble({required String role, required Widget child}) {
    final bool coach = role == 'coach';
    final MayosThemeExtension c = MayosTheme.of(context);
    return Align(
      alignment: coach
          ? AlignmentDirectional.centerEnd
          : AlignmentDirectional.centerStart,
      child: Container(
        margin: const EdgeInsets.symmetric(vertical: MayosSpacing.xxs),
        padding: const EdgeInsets.symmetric(
            horizontal: MayosSpacing.sm, vertical: MayosSpacing.xs),
        constraints:
            BoxConstraints(maxWidth: MediaQuery.of(context).size.width * 0.78),
        decoration: BoxDecoration(
          color: coach ? c.accent : c.secondarySurface,
          borderRadius: MayosRadii.mediumRadius,
          border: Border.all(color: coach ? c.accent : c.border),
        ),
        child: child,
      ),
    );
  }

  Widget _errorBanner(MayosThemeExtension c) {
    final String message = displayCopyOf(context).failureMessage(_error!);
    return Container(
      key: const Key('coach_assistant_error'),
      width: double.infinity,
      margin: const EdgeInsetsDirectional.fromSTEB(
          MayosSpacing.md, MayosSpacing.xs, MayosSpacing.md, 0),
      padding: const EdgeInsets.symmetric(
          horizontal: MayosSpacing.md, vertical: MayosSpacing.xs),
      decoration: BoxDecoration(
        color: c.secondarySurface,
        borderRadius: MayosRadii.mediumRadius,
        border: Border.all(color: c.danger),
      ),
      child: FirstStrongDirection(
        text: message,
        child: Text(
          message,
          style: MayosTypography.of(context).bodySecondary.copyWith(color: c.danger),
        ),
      ),
    );
  }

  /// The one-line disclosure: figures in, prose out, nothing kept (issue #45).
  Widget _note(MayosThemeExtension c) {
    return Padding(
      padding: const EdgeInsetsDirectional.fromSTEB(
          MayosSpacing.md, MayosSpacing.xs, MayosSpacing.md, 0),
      child: Text(
        coachCopyOf(context).assistantNote(widget.entry.playerUsername),
        textAlign: TextAlign.center,
        style: MayosTypography.of(context).caption.copyWith(color: c.textMuted),
      ),
    );
  }

  Widget _composer(MayosThemeExtension c) {
    return SafeArea(
      key: const Key('coach_assistant_composer'),
      top: false,
      child: Padding(
        padding: const EdgeInsetsDirectional.fromSTEB(
            MayosSpacing.sm, MayosSpacing.xs, MayosSpacing.sm, MayosSpacing.xs),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.end,
          children: <Widget>[
            Expanded(
              child: MayosTextField(
                fieldKey: const Key('coach_assistant_question'),
                controller: _question,
                enabled: !_sending,
                minLines: 1,
                maxLines: 4,
                maxLength: coachAssistantQuestionMaxChars,
                textInputAction: TextInputAction.newline,
                hint: coachCopyOf(context).askAboutPlayer,
                onChanged: (_) => setState(() {}),
              ),
            ),
            const SizedBox(width: MayosSpacing.xs),
            Semantics(
              label: coachCopyOf(context).send,
              button: true,
              child: IconButton.filled(
                key: const Key('coach_assistant_send'),
                tooltip: coachCopyOf(context).send,
                style: IconButton.styleFrom(
                  backgroundColor: c.accent,
                  foregroundColor: c.onAccent,
                  disabledBackgroundColor: c.surfaceSunken,
                  disabledForegroundColor: c.textDisabled,
                  minimumSize:
                      const Size(kMayosMinTapTarget, kMayosMinTapTarget),
                ),
                onPressed:
                    _sending || _question.text.trim().isEmpty ? null : _send,
                icon: _sending
                    ? SizedBox(
                        height: 18,
                        width: 18,
                        child: CircularProgressIndicator(
                          strokeWidth: 2,
                          color: c.onAccent,
                        ),
                      )
                    : const Icon(Icons.send),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

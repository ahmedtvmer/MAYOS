import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api_client.dart';
import '../../core/app_failure.dart';
import '../../core/connectivity_message.dart';
import '../../core/display_language/coach_copy.dart';
import '../../core/display_language/copy_context.dart';
import '../../core/display_language/feature_copy_context.dart';
import '../../core/models.dart';
import '../../core/theme/myos_spacing.dart';
import '../../core/theme/myos_theme.dart';
import '../../core/theme/myos_typography.dart';
import '../../core/ui/myos_markdown.dart';
import '../../core/ui/myos_phone_tap_target.dart';
import '../../core/ui/myos_text_field.dart';
import '../../providers.dart';
import 'coach_assistant_screen.dart';
import 'coach_assistant_state.dart';
import 'coach_roster_alias.dart';

class CoachRosterAssistantPanel extends ConsumerStatefulWidget {
  const CoachRosterAssistantPanel({
    super.key,
    required this.enabled,
    required this.coachPro,
    required this.assignments,
  });

  final bool enabled;
  final bool coachPro;
  final List<CoachRosterEntry> assignments;

  @override
  ConsumerState<CoachRosterAssistantPanel> createState() =>
      _CoachRosterAssistantPanelState();
}

class _CoachRosterAssistantPanelState
    extends ConsumerState<CoachRosterAssistantPanel> {
  final TextEditingController _question = TextEditingController();
  bool _sending = false;
  FailureMessage? _error;

  @override
  void dispose() {
    _question.dispose();
    super.dispose();
  }

  Future<void> _send() async {
    final String question = _question.text.trim();
    if (question.isEmpty || _sending) return;
    final List<CoachAssistantTurn> history = ref
        .read(coachRosterAssistantControllerProvider.notifier)
        .history();
    setState(() {
      _sending = true;
      _error = null;
    });
    try {
      final CoachRosterAssistantReply reply = await ref
          .read(apiClientProvider)
          .coachRosterAssistant(question: question, history: history);
      if (!mounted) return;
      final String? accountId = ref
          .read(authControllerProvider)
          .session
          ?.account
          .accountId;
      if (reply.coachAiAllowance != null && accountId != null) {
        ref.read(authControllerProvider.notifier).updateCoachAiAllowance(
              accountId,
              reply.coachAiAllowance!,
            );
      }
      ref
          .read(coachRosterAssistantControllerProvider.notifier)
          .recordExchange(question, reply);
      _question.clear();
      setState(() => _sending = false);
    } on ApiException catch (failure) {
      if (!mounted) return;
      if (failure.statusCode == 404) {
        unawaited(ref.read(authControllerProvider.notifier).refreshAccount());
      }
      if (failure.statusCode == 429 || failure.statusCode == 503) {
        unawaited(ref.read(authControllerProvider.notifier).refreshAccount());
      }
      if (failure.statusCode == 429) {
        unawaited(ref.read(authControllerProvider.notifier).refreshAccount());
      }
      setState(() {
        _sending = false;
        _error = apiFailureMessage(failure);
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    final CoachCopy copy = coachCopyOf(context);
    final MyosThemeExtension colors = MyosTheme.of(context);
    final CoachRosterAssistantTranscript transcript = ref.watch(
      coachRosterAssistantControllerProvider,
    );
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: <Widget>[
        Text(
          copy.askAboutRoster,
          style: MyosTypography.of(context).sectionHeading,
        ),
        const SizedBox(height: MyosSpacing.xs),
        Text(
          copy.rosterAssistantLead,
          style: MyosTypography.of(context).bodySecondary
              .copyWith(color: colors.textSecondary),
        ),
        const SizedBox(height: MyosSpacing.sm),
        if (!widget.coachPro)
          Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: <Widget>[
              _notice(copy.rosterAssistantUpgrade, colors),
              const SizedBox(height: MyosSpacing.md),
              _rosterUrgencyOrder(copy, colors),
            ],
          )
        else if (!widget.enabled)
          _notice(copy.rosterAssistantDisabled, colors)
        else
          _enabledContent(copy, colors, transcript),
        const SizedBox(height: MyosSpacing.lg),
        const Divider(),
        const SizedBox(height: MyosSpacing.md),
      ],
    );
  }

  Widget _rosterUrgencyOrder(
    CoachCopy copy,
    MyosThemeExtension colors,
  ) =>
      Column(
        key: const Key('coach_roster_urgency_order'),
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: <Widget>[
          Text(
            copy.rosterUrgencyOrderHeading,
            style: MyosTypography.of(context).sectionHeading,
          ),
          if (widget.assignments.isEmpty)
            Padding(
              padding: const EdgeInsets.only(top: MyosSpacing.xs),
              child: Text(copy.noAssignedPlayers),
            )
          else
            for (int index = 0; index < widget.assignments.length; index++)
              Padding(
                padding: const EdgeInsets.only(top: MyosSpacing.xs),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: <Widget>[
                    Text(
                      copy.rosterUrgencyPlayer(
                        index + 1,
                        widget.assignments[index].playerUsername,
                      ),
                      style: MyosTypography.of(context).bodySecondary,
                    ),
                    Text(
                      copy.rosterUrgencySignals(
                        alerts: widget.assignments[index].alertsNew,
                        requests: widget.assignments[index].pendingRequests,
                        missedDays: widget.assignments[index].currentMissedStreak,
                        stallSessions: widget.assignments[index].stallLength,
                      ),
                      style: MyosTypography.of(context).caption
                          .copyWith(color: colors.textSecondary),
                    ),
                  ],
                ),
              ),
        ],
      );

  Widget _enabledContent(
    CoachCopy copy,
    MyosThemeExtension colors,
    CoachRosterAssistantTranscript transcript,
  ) =>
      Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: <Widget>[
          _exchangeHistory(copy, colors, transcript),
          if (_sending) _thinking(copy, colors),
          if (_error != null) _errorMessage(colors),
          const SizedBox(height: MyosSpacing.sm),
          _composer(copy, colors),
        ],
      );

  Widget _exchangeHistory(
    CoachCopy copy,
    MyosThemeExtension colors,
    CoachRosterAssistantTranscript transcript,
  ) =>
      Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: <Widget>[
          _privacyNote(copy, colors),
          const SizedBox(height: MyosSpacing.sm),
          if (transcript.exchanges.isEmpty && !_sending)
            Padding(
              padding: const EdgeInsets.symmetric(vertical: MyosSpacing.sm),
              child: Text(
                copy.rosterAssistantNoHistory,
                style: MyosTypography.of(context).bodySecondary
                    .copyWith(color: colors.textSecondary),
              ),
            )
          else
            for (final CoachRosterAssistantExchange exchange
                in transcript.exchanges)
              _exchange(exchange, copy, colors),
        ],
      );

  Widget _errorMessage(MyosThemeExtension colors) => Padding(
    padding: const EdgeInsets.only(top: MyosSpacing.sm),
    child: Text(
      displayCopyOf(context).failureMessage(_error!),
      style: MyosTypography.of(context).bodySecondary
          .copyWith(color: colors.danger),
    ),
  );

  Widget _notice(String message, MyosThemeExtension colors) => Container(
    padding: const EdgeInsets.all(MyosSpacing.sm),
    decoration: BoxDecoration(
      color: colors.surfaceSunken,
      borderRadius: BorderRadius.circular(12),
    ),
    child: Text(
      message,
      style: MyosTypography.of(context).bodySecondary
          .copyWith(color: colors.textSecondary),
    ),
  );

  Widget _privacyNote(CoachCopy copy, MyosThemeExtension colors) => Text(
    copy.rosterAssistantPrivacyNote,
    style: MyosTypography.of(context).caption
        .copyWith(color: colors.textMuted),
  );

  Widget _exchange(
    CoachRosterAssistantExchange exchange,
    CoachCopy copy,
    MyosThemeExtension colors,
  ) {
    final Map<String, CoachRosterEntry> assignmentsById = _assignmentsById();
    final Set<String> mentioned = _mentionedAliases(exchange);
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: MyosSpacing.xxs),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: <Widget>[
          Align(
            alignment: AlignmentDirectional.centerEnd,
            child: Container(
              constraints: BoxConstraints(
                maxWidth: MediaQuery.of(context).size.width * 0.86,
              ),
              padding: const EdgeInsets.all(MyosSpacing.sm),
              decoration: BoxDecoration(
                color: colors.accent,
                borderRadius: BorderRadius.circular(14),
              ),
              child: _questionBubble(exchange.question, colors),
            ),
          ),
          Align(
            alignment: AlignmentDirectional.centerStart,
            child: Container(
              key: const Key('coach_roster_assistant_answer'),
              constraints: BoxConstraints(
                maxWidth: MediaQuery.of(context).size.width * 0.9,
              ),
              padding: const EdgeInsets.all(MyosSpacing.sm),
              decoration: BoxDecoration(
                color: colors.surfaceSunken,
                borderRadius: BorderRadius.circular(14),
              ),
              child: _answerBubble(exchange, assignmentsById),
            ),
          ),
          if (mentioned.isNotEmpty)
            _playerLinks(copy, exchange, mentioned, assignmentsById),
        ],
      ),
    );
  }

  Map<String, CoachRosterEntry> _assignmentsById() => <String, CoachRosterEntry>{
        for (final CoachRosterEntry entry in widget.assignments)
          entry.assignmentId: entry,
      };

  Set<String> _mentionedAliases(CoachRosterAssistantExchange exchange) =>
      CoachRosterAlias.mentionedIn(
        exchange.answer,
        exchange.assignmentByPlayerId.keys,
      );

  String _displayAnswer(
    CoachRosterAssistantExchange exchange,
    Map<String, CoachRosterEntry> assignmentsById,
  ) => CoachRosterAlias.replaceIn(exchange.answer, (String alias) {
        final String? assignmentId = exchange.assignmentByPlayerId[alias];
        final CoachRosterEntry? entry = assignmentId == null
            ? null
            : assignmentsById[assignmentId];
        if (entry == null) return alias;
        final String displayName =
            exchange.displayNameByPlayerId[alias] ?? entry.playerUsername;
        return '$alias ($displayName)';
      });

  Widget _questionBubble(
    String question,
    MyosThemeExtension colors,
  ) =>
      Text(
        question,
        style: MyosTypography.of(context).bodySecondary
            .copyWith(color: colors.onAccent),
      );

  Widget _answerBubble(
    CoachRosterAssistantExchange exchange,
    Map<String, CoachRosterEntry> assignmentsById,
  ) =>
      Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: <Widget>[
          SelectionArea(
            child: MyosMarkdown(
              source: _displayAnswer(exchange, assignmentsById),
              bodyStyle: MyosTypography.of(context).bodySecondary,
              selectable: false,
            ),
          ),
          if (exchange.coverageSummary.isNotEmpty) ...<Widget>[
            const SizedBox(height: MyosSpacing.xs),
            Text(
              exchange.coverageSummary,
              key: const Key('coach_roster_coverage_summary'),
              style: MyosTypography.of(context).caption
                  .copyWith(color: MyosTheme.of(context).textSecondary),
            ),
          ],
        ],
      );

  Widget _playerLinks(
    CoachCopy copy,
    CoachRosterAssistantExchange exchange,
    Set<String> mentioned,
    Map<String, CoachRosterEntry> assignmentsById,
  ) =>
      Wrap(
        spacing: MyosSpacing.xs,
        runSpacing: MyosSpacing.xs,
        children: <Widget>[
          for (final String alias in mentioned)
            if (assignmentsById[exchange.assignmentByPlayerId[alias]] != null)
              _playerLink(
                copy,
                alias,
                assignmentsById[exchange.assignmentByPlayerId[alias]]!,
                exchange.displayNameByPlayerId[alias] ?? assignmentsById[
                  exchange.assignmentByPlayerId[alias]
                ]!.playerUsername,
              ),
        ],
      );

  Widget _playerLink(
    CoachCopy copy,
    String alias,
    CoachRosterEntry entry,
    String playerDisplayName,
  ) =>
      myosPhoneTapTarget(context, ActionChip(
        key: Key('coach_roster_player_link_$alias'),
        avatar: const Icon(Icons.open_in_new, size: 16),
        label: Text('${copy.askAboutPlayer}: $playerDisplayName'),
        onPressed: () => Navigator.of(context).push<void>(
          MaterialPageRoute<void>(
            builder: (BuildContext context) =>
                CoachAssistantScreen(entry: entry),
          ),
        ),
      ));

  Widget _thinking(CoachCopy copy, MyosThemeExtension colors) => Padding(
    padding: const EdgeInsets.symmetric(vertical: MyosSpacing.sm),
    child: Row(
      mainAxisSize: MainAxisSize.min,
      children: <Widget>[
        const SizedBox(
          height: 14,
          width: 14,
          child: CircularProgressIndicator(strokeWidth: 2),
        ),
        const SizedBox(width: MyosSpacing.sm),
        Text(
          copy.assistantThinking,
          style: MyosTypography.of(context).bodySecondary
              .copyWith(color: colors.textSecondary),
        ),
      ],
    ),
  );

  Widget _composer(CoachCopy copy, MyosThemeExtension colors) => Row(
    crossAxisAlignment: CrossAxisAlignment.end,
    children: <Widget>[
      Expanded(
        child: MyosTextField(
          fieldKey: const Key('coach_roster_assistant_question'),
          controller: _question,
          enabled: !_sending,
          minLines: 1,
          maxLines: 4,
          maxLength: coachAssistantQuestionMaxChars,
          hint: copy.rosterQuestionHint,
          onChanged: (_) => setState(() {}),
          onSubmitted: (_) => _send(),
        ),
      ),
      const SizedBox(width: MyosSpacing.xs),
      IconButton.filled(
        key: const Key('coach_roster_assistant_send'),
        tooltip: copy.send,
        style: IconButton.styleFrom(
          backgroundColor: colors.accent,
          foregroundColor: colors.onAccent,
          minimumSize: const Size(48, 48),
        ),
        onPressed: _sending || _question.text.trim().isEmpty ? null : _send,
        icon: _sending
            ? SizedBox(
                height: 18,
                width: 18,
                child: CircularProgressIndicator(
                  strokeWidth: 2,
                  color: colors.onAccent,
                ),
              )
            : const Icon(Icons.send),
      ),
    ],
  );
}

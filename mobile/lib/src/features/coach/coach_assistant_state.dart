import 'package:flutter/foundation.dart' show immutable;
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/models.dart';

/// Request bounds mirrored from `svc/schemas.py` (issue #45): one question of
/// at most 1000 characters, sent with at most 12 transcript turns of at most
/// 2000 characters each.
const int coachAssistantQuestionMaxChars = 1000;
const int coachAssistantHistoryMaxTurns = 12;
const int coachAssistantTurnMaxChars = 2000;

/// Upper bound on the turns kept in memory for the selected player (issue #45).
/// Only [coachAssistantHistoryMaxTurns] of them are ever sent.
const int coachAssistantTranscriptMaxTurns = 50;

/// The in-memory transcript of one selected player: the assignment it belongs
/// to and the coach/assistant turns exchanged for it.
///
/// It is deliberately a plain Dart object with no storage backing — nothing
/// here is written to secure storage, caches, shared preferences, or logs
/// (issue #45). The provider holding it is the only home it has, so it dies
/// with the process.
@immutable
class CoachAssistantTranscript {
  const CoachAssistantTranscript({
    required this.assignmentId,
    this.turns = const <CoachAssistantTurn>[],
  });

  final String assignmentId;
  final List<CoachAssistantTurn> turns;
}

/// Holds the transcript for **one** selected player and enforces the clearing
/// rules of issue #45: a different player replaces it, a revoked assignment or
/// an ended roster entry drops it, and logout (through the auth listener on the
/// provider) and app close (through the lifecycle observer in `MayosApp`) clear
/// it. The service keeps no copy either.
class CoachAssistantController
    extends StateNotifier<CoachAssistantTranscript?> {
  CoachAssistantController() : super(null);

  /// Selects the player the assistant is open for. One player at a time:
  /// opening for a different assignment drops the previous transcript before
  /// anything is asked or sent.
  void openFor(String assignmentId) {
    final CoachAssistantTranscript? transcript = state;
    if (transcript != null && transcript.assignmentId == assignmentId) {
      return;
    }
    state = CoachAssistantTranscript(assignmentId: assignmentId);
  }

  /// The turns to send as `history` for [assignmentId]: the last
  /// [coachAssistantHistoryMaxTurns] of the in-memory transcript, or nothing
  /// when a different player (or none) is selected.
  List<CoachAssistantTurn> historyFor(String assignmentId) {
    final CoachAssistantTranscript? transcript = state;
    if (transcript == null || transcript.assignmentId != assignmentId) {
      return const <CoachAssistantTurn>[];
    }
    final List<CoachAssistantTurn> turns = transcript.turns;
    if (turns.length <= coachAssistantHistoryMaxTurns) {
      return List<CoachAssistantTurn>.unmodifiable(turns);
    }
    return List<CoachAssistantTurn>.unmodifiable(
      turns.sublist(turns.length - coachAssistantHistoryMaxTurns),
    );
  }

  /// Appends one completed exchange, unless another player is now selected (or
  /// the transcript was cleared while the answer was in flight). Both sides are
  /// bounded to their wire limits so the stored transcript can always be sent
  /// back without the service answering 422 on our own history, and only the
  /// last [coachAssistantTranscriptMaxTurns] turns are ever kept in memory.
  void recordExchange(
    String assignmentId, {
    required String question,
    required String answer,
  }) {
    final CoachAssistantTranscript? transcript = state;
    if (transcript == null || transcript.assignmentId != assignmentId) {
      return;
    }
    final List<CoachAssistantTurn> turns = <CoachAssistantTurn>[
      ...transcript.turns,
      CoachAssistantTurn(
          role: 'coach',
          content: _bounded(question, coachAssistantQuestionMaxChars)),
      CoachAssistantTurn(
          role: 'assistant',
          content: _bounded(answer, coachAssistantTurnMaxChars)),
    ];
    state = CoachAssistantTranscript(
      assignmentId: assignmentId,
      turns: turns.length <= coachAssistantTranscriptMaxTurns
          ? turns
          : turns.sublist(turns.length - coachAssistantTranscriptMaxTurns),
    );
  }

  /// Drops everything (logout, session teardown, app close).
  void clear() => state = null;

  /// Drops the transcript only when it belongs to [assignmentId], so a late
  /// failure can never erase another player's context.
  void clearFor(String assignmentId) {
    if (state != null && state!.assignmentId == assignmentId) {
      state = null;
    }
  }

  /// Drops the transcript when a refreshed roster no longer holds its
  /// assignment (the player was revoked or ended coaching).
  void clearUnlessAssigned(Iterable<String> activeAssignmentIds) {
    final CoachAssistantTranscript? transcript = state;
    if (transcript == null) {
      return;
    }
    if (!activeAssignmentIds.contains(transcript.assignmentId)) {
      state = null;
    }
  }
}

/// Bounds [content] to [maxChars], never splitting a UTF-16 surrogate pair, so
/// a stored turn is always well-formed and always within the wire limit.
String _bounded(String content, int maxChars) {
  if (content.length <= maxChars) {
    return content;
  }
  int end = maxChars;
  final int lastUnit = content.codeUnitAt(end - 1);
  if (lastUnit >= 0xd800 && lastUnit <= 0xdbff) {
    end -= 1;
  }
  return content.substring(0, end);
}

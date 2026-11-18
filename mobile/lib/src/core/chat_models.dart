// Hosted player-assistant chat models (ADR 016/036).

import 'models.dart';

/// Signed, account-bound context for voting on or reporting one assistant
/// reply (#748). The server signs it into the chat done frame; the client
/// sends it back unchanged with a vote or report, or omits it for a reply
/// restored from history (the server then re-derives it from the message id).
class AssistantFeedbackContext {
  const AssistantFeedbackContext({
    required this.messageId,
    required this.questionText,
    required this.replyText,
    required this.language,
    required this.route,
    this.model,
    this.promptVersion,
    this.redactTerms = const <String>[],
    required this.signature,
  });

  factory AssistantFeedbackContext.fromJson(Map<String, dynamic> json) =>
      AssistantFeedbackContext(
        messageId: json['message_id'] is String ? json['message_id'] as String : '',
        questionText: json['question_text'] is String
            ? json['question_text'] as String
            : '',
        replyText:
            json['reply_text'] is String ? json['reply_text'] as String : '',
        language: json['language'] is String ? json['language'] as String : 'en',
        route: json['route'] is String ? json['route'] as String : 'assistant',
        model: json['model'] is String ? json['model'] as String : null,
        promptVersion: json['prompt_version'] is String
            ? json['prompt_version'] as String
            : null,
        redactTerms: json['redact_terms'] is List<dynamic>
            ? List<String>.from(json['redact_terms'] as List<dynamic>)
            : const <String>[],
        signature:
            json['signature'] is String ? json['signature'] as String : '',
      );

  final String messageId;
  final String questionText;
  final String replyText;
  final String language;
  final String route;
  final String? model;
  final String? promptVersion;
  final List<String> redactTerms;
  final String signature;

  Map<String, dynamic> toJson() => <String, dynamic>{
        'message_id': messageId,
        'question_text': questionText,
        'reply_text': replyText,
        'language': language,
        'route': route,
        if (model != null) 'model': model,
        if (promptVersion != null) 'prompt_version': promptVersion,
        'redact_terms': redactTerms,
        'signature': signature,
      };
}

/// This account's own vote/report state for one assistant reply, as the
/// history endpoint annotates it. Coaches and other accounts never see it.
class ChatFeedbackState {
  const ChatFeedbackState({
    required this.feedbackId,
    this.vote,
    this.reported = false,
  });

  factory ChatFeedbackState.fromJson(Map<String, dynamic> json) =>
      ChatFeedbackState(
        feedbackId:
            json['feedback_id'] is String ? json['feedback_id'] as String : '',
        vote: json['vote'] is String ? json['vote'] as String : null,
        reported: json['reported'] == true,
      );

  final String feedbackId;
  final String? vote;
  final bool reported;

  Map<String, dynamic> toJson() => <String, dynamic>{
        'feedback_id': feedbackId,
        if (vote != null) 'vote': vote,
        'reported': reported,
      };
}

/// One persisted turn in the player's chat history (`GET /chat/history`).
class ChatMessage {
  const ChatMessage({
    required this.id,
    required this.role,
    required this.content,
    this.createdAt,
    this.kind = 'message',
    this.requestSuggestion,
    this.programEditPreview,
    this.feedback,
    this.feedbackContext,
  });

  factory ChatMessage.fromJson(Map<String, dynamic> json) => ChatMessage(
        id: _string(json['id']),
        role: _string(json['role']),
        content: _string(json['content']),
        createdAt:
            json['created_at'] is String ? json['created_at'] as String : null,
        kind: json['kind'] is String ? json['kind'] as String : 'message',
        programEditPreview: json['program_edit_preview'] is Map<String, dynamic>
            ? json['program_edit_preview'] as Map<String, dynamic>
            : null,
        feedback: json['feedback'] is Map<String, dynamic>
            ? ChatFeedbackState.fromJson(
                json['feedback'] as Map<String, dynamic>)
            : null,
        feedbackContext: json['feedback_context'] is Map<String, dynamic>
            ? AssistantFeedbackContext.fromJson(
                json['feedback_context'] as Map<String, dynamic>)
            : null,
      );

  final String id;
  final String role;
  final String content;
  final String? createdAt;

  /// The server's classification of this message: `debrief` for a
  /// session-logged pointer written at workout commit (ADR 033/036), else
  /// `message`. The client never re-derives it from the wording.
  final String kind;

  /// A transient action from this streamed reply; never part of stored history.
  final ProgramRequestDraft? requestSuggestion;
  final Map<String, dynamic>? programEditPreview;

  /// This account's vote/report state for the reply, and the signed context
  /// to vote or report with (fresh replies only; history restores the state).
  final ChatFeedbackState? feedback;
  final AssistantFeedbackContext? feedbackContext;

  bool get isUser => role == 'user';

  /// A session-commit pointer written at workout commit (ADR 033). Rendered as
  /// a distinct debrief card rather than a normal assistant bubble.
  bool get isDebriefPointer => kind == 'debrief';

  ChatMessage copyWith({
    ChatFeedbackState? feedback,
    AssistantFeedbackContext? feedbackContext,
  }) =>
      ChatMessage(
        id: id,
        role: role,
        content: content,
        createdAt: createdAt,
        kind: kind,
        requestSuggestion: requestSuggestion,
        programEditPreview: programEditPreview,
        feedback: feedback ?? this.feedback,
        feedbackContext: feedbackContext ?? this.feedbackContext,
      );

  Map<String, dynamic> toJson() => <String, dynamic>{
        'id': id,
        'role': role,
        'content': content,
        if (createdAt != null) 'created_at': createdAt,
        'kind': kind,
        if (programEditPreview != null)
          'program_edit_preview': programEditPreview,
        if (feedback != null) 'feedback': feedback!.toJson(),
        if (feedbackContext != null) 'feedback_context': feedbackContext!.toJson(),
      };

  static String _string(dynamic value) => value is String ? value : '';
}

/// One event decoded from the `POST /chat/messages` SSE stream.
sealed class ChatStreamEvent {
  const ChatStreamEvent();
}

/// A streamed assistant token chunk; append it to the live draft.
class ChatToken extends ChatStreamEvent {
  const ChatToken(this.token);

  final String token;
}

/// A transient server status while a read-only player tool is running.
class ChatStatus extends ChatStreamEvent {
  const ChatStatus(this.status);

  final String status;
}

/// The turn finished: the reply is final and may have changed the program.
class ChatDone extends ChatStreamEvent {
  const ChatDone({
    required this.responseContent,
    required this.programUpdated,
    this.movementRestrictionsUpdated = false,
    this.outcome = 'completed',
    this.lifterAllowance,
    this.coachAllowance,
    this.requestSuggestion,
    this.programEditPreview,
    this.feedbackContext,
  });

  final String responseContent;
  final bool programUpdated;
  final bool movementRestrictionsUpdated;
  final String outcome;
  final AiAllowance? lifterAllowance;
  final AiAllowance? coachAllowance;
  final ProgramRequestDraft? requestSuggestion;
  final Map<String, dynamic>? programEditPreview;

  /// Signed context to vote on or report this reply (#748); null when the
  /// server could not sign one, which simply hides the feedback bar.
  final AssistantFeedbackContext? feedbackContext;
}

/// The turn failed; [detail] is the service's fixed, non-leaking message.
class ChatError extends ChatStreamEvent {
  const ChatError(
    this.detail, {
    this.messageCode,
    this.messageParams,
    this.messageFallback,
  });

  final String detail;
  final String? messageCode;
  final Map<String, dynamic>? messageParams;
  final String? messageFallback;
}

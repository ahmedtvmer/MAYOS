// Hosted player-assistant chat models (ADR 016/036).

import 'models.dart';

/// The hosted-processing disclosure shown before the first chat use (#37).
///
/// Kept short and honest per ADR 016: it names the hosted provider and admits
/// that user-written free text may contain identifying information.
const String hostedChatDisclosure = 'Chat is answered by a hosted AI model. '
    'Your message and the training context needed to answer it are sent to that '
    'model provider. Free text can contain identifying details, so do not include '
    'anything you do not want processed there.';

/// One persisted turn in the player's chat history (`GET /chat/history`).
class ChatMessage {
  const ChatMessage({
    required this.id,
    required this.role,
    required this.content,
    this.createdAt,
    this.kind = 'message',
    this.requestSuggestion,
  });

  factory ChatMessage.fromJson(Map<String, dynamic> json) => ChatMessage(
        id: _string(json['id']),
        role: _string(json['role']),
        content: _string(json['content']),
        createdAt:
            json['created_at'] is String ? json['created_at'] as String : null,
        kind: json['kind'] is String ? json['kind'] as String : 'message',
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

  bool get isUser => role == 'user';

  /// A session-commit pointer written at workout commit (ADR 033). Rendered as
  /// a distinct debrief card rather than a normal assistant bubble.
  bool get isDebriefPointer => kind == 'debrief';

  Map<String, dynamic> toJson() => <String, dynamic>{
        'id': id,
        'role': role,
        'content': content,
        if (createdAt != null) 'created_at': createdAt,
        'kind': kind,
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

/// The turn finished: the reply is final and may have changed the program.
class ChatDone extends ChatStreamEvent {
  const ChatDone({
    required this.responseContent,
    required this.programUpdated,
    this.requestSuggestion,
  });

  final String responseContent;
  final bool programUpdated;
  final ProgramRequestDraft? requestSuggestion;
}

/// The turn failed; [detail] is the service's fixed, non-leaking message.
class ChatError extends ChatStreamEvent {
  const ChatError(this.detail);

  final String detail;
}

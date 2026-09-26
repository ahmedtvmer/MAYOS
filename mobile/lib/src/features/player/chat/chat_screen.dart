import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api_client.dart';
import '../../../core/chat_models.dart';
import '../../../core/chat_storage.dart';
import '../../../core/models.dart';
import '../../../core/workout_storage.dart';
import '../../../providers.dart';

/// Hosted player-assistant chat (#37, ADR 016/036).
///
/// Reads and writes go through `POST/GET/DELETE /chat/*`. Chat requires
/// connectivity: the composer disables with an explanatory message once a load
/// or send fails with a network error, and sends are never queued. The
/// last-loaded history is cached per account so it stays readable offline.
class ChatScreen extends ConsumerStatefulWidget {
  const ChatScreen({super.key});

  @override
  ConsumerState<ChatScreen> createState() => _ChatScreenState();
}

class _ChatScreenState extends ConsumerState<ChatScreen> {
  final TextEditingController _controller = TextEditingController();

  bool _disposed = false;
  StreamSubscription<ChatStreamEvent>? _subscription;

  bool _disclosureLoaded = false;
  bool _disclosureAccepted = false;
  bool _loadingHistory = true;
  bool _offline = false;
  String? _historyError;
  List<ChatMessage> _messages = <ChatMessage>[];
  bool _sending = false;
  String? _streamingText;
  String? _sendError;
  String? _failedContent;
  bool _retryAddsBubble = true;

  String? get _accountId =>
      ref.read(authControllerProvider).session?.account.accountId;

  ChatCacheStore get _store => ref.read(chatCacheStoreProvider);

  @override
  void initState() {
    super.initState();
    _init();
  }

  @override
  void dispose() {
    _disposed = true;
    unawaited(_subscription?.cancel());
    _controller.dispose();
    super.dispose();
  }

  /// Marks state dirty only while the widget is mounted, so an in-flight
  /// stream that resolves after dispose never calls [setState].
  void _setStateIfMounted(VoidCallback update) {
    if (_disposed || !mounted) return;
    setState(update);
  }

  Future<void> _init() async {
    final String? accountId = _accountId;
    if (accountId == null) {
      _setStateIfMounted(() {
        _disclosureLoaded = true;
        _loadingHistory = false;
        _historyError = 'You are not signed in.';
      });
      return;
    }
    // Secure-storage reads are best-effort: a keystore failure must still let
    // the screen render (treated as no acceptance and an empty cache).
    bool accepted = false;
    List<ChatMessage> cached = <ChatMessage>[];
    try {
      accepted = await _store.readDisclosureAccepted(accountId);
      cached = await _store.readHistory(accountId);
    } on Object {
      accepted = false;
      cached = <ChatMessage>[];
    }
    _setStateIfMounted(() {
      _disclosureAccepted = accepted;
      _disclosureLoaded = true;
      _messages = cached;
    });
    await _loadHistory();
  }

  Future<void> _loadHistory() async {
    final String? accountId = _accountId;
    if (accountId == null) return;
    _setStateIfMounted(() {
      _loadingHistory = true;
      _historyError = null;
    });
    try {
      final List<ChatMessage> fresh =
          await ref.read(apiClientProvider).chatHistory();
      await _store.writeHistory(accountId, fresh);
      _setStateIfMounted(() {
        _messages = fresh;
        _offline = false;
        _historyError = null;
        _loadingHistory = false;
      });
    } on ApiException catch (error) {
      _setStateIfMounted(() {
        _loadingHistory = false;
        if (error.statusCode == null) {
          // Network failure: keep the cached history and read-only offline.
          _offline = true;
        } else {
          _historyError = error.message;
        }
      });
    }
  }

  /// The offline banner's retry: reload from the server and, on success, leave
  /// the offline state so the composer re-enables.
  Future<void> _retryHistory() => _loadHistory();

  Future<void> _acceptDisclosure() async {
    final String? accountId = _accountId;
    if (accountId == null) return;
    try {
      await _store.writeDisclosureAccepted(accountId);
    } on Object {
      // Not fatal: acceptance still applies for this session.
    }
    _setStateIfMounted(() => _disclosureAccepted = true);
  }

  Future<void> _send() async {
    final String content = _controller.text.trim();
    if (content.isEmpty || _sending || !_disclosureAccepted || _offline) {
      return;
    }
    _controller.clear();
    _retryAddsBubble = true;
    await _sendContent(content);
  }

  Future<void> _retry() async {
    final String? content = _failedContent;
    if (content == null || _sending) return;
    await _sendContent(content);
  }

  /// Sends [content]. A fresh send shows the user's message immediately as a
  /// local bubble; a retry does not (the failed attempt's user message was
  /// reloaded from the server, so it must not appear twice).
  Future<void> _sendContent(String content) async {
    final String? accountId = _accountId;
    if (accountId == null) return;
    final bool addUserBubble = _retryAddsBubble;
    _setStateIfMounted(() {
      _sending = true;
      _sendError = null;
      _failedContent = null;
      _streamingText = '';
      if (addUserBubble) {
        _messages = <ChatMessage>[
          ..._messages,
          ChatMessage(
            id: 'local-user-${DateTime.now().microsecondsSinceEpoch}',
            role: 'user',
            content: content,
          ),
        ];
      }
    });

    String buffer = '';
    bool finished = false;
    try {
      await for (final ChatStreamEvent event
          in ref.read(apiClientProvider).streamChatMessage(content)) {
        if (_disposed) return;
        switch (event) {
          case ChatToken(:final String token):
            buffer += token;
            _setStateIfMounted(() => _streamingText = buffer);
          case ChatDone(
              :final String responseContent,
              :final bool programUpdated
            ):
            finished = true;
            final String reply =
                responseContent.isNotEmpty ? responseContent : buffer;
            _setStateIfMounted(() {
              _messages = <ChatMessage>[
                ..._messages,
                ChatMessage(
                  id: 'local-assistant-${DateTime.now().microsecondsSinceEpoch}',
                  role: 'assistant',
                  content: reply,
                ),
              ];
              _streamingText = null;
              _sending = false;
              _offline = false;
              _historyError = null;
            });
            await _store.writeHistory(accountId, _messages);
            if (programUpdated) {
              unawaited(_refreshProgramCache());
            }
          case ChatError(:final String detail):
            finished = true;
            await _failTurn(content, detail);
            return;
        }
      }
    } on ApiException catch (error) {
      final bool offline = error.statusCode == null;
      await _failTurn(
        content,
        offline
            ? 'Chat needs a connection. Reconnect and retry.'
            : error.message,
        offline: offline,
      );
      return;
    } on Object {
      await _failTurn(content, 'The assistant did not finish. Please retry.');
      return;
    }
    if (!_disposed && !finished && _sending) {
      await _failTurn(content, 'The assistant did not finish. Please retry.');
    }
  }

  /// Records a failed turn: shows the error, reloads the server history so the
  /// persisted (unanswered) user message appears exactly once, and arms Retry.
  /// A retry re-sends the same content without adding another local bubble.
  Future<void> _failTurn(String content, String message,
      {bool offline = false}) async {
    _setStateIfMounted(() {
      _streamingText = null;
      _sending = false;
      _offline = _offline || offline;
      _sendError = message;
      _failedContent = content;
      // The reloaded server history already contains the user's message, so a
      // retry must not insert it again.
      _retryAddsBubble = false;
    });
    await _loadHistory();
  }

  /// A program-changing turn refreshes the offline program cache so the logger
  /// and Program tab see the change (ADR 020/036). Best-effort only.
  Future<void> _refreshProgramCache() async {
    final String? accountId = _accountId;
    if (accountId == null) return;
    try {
      final TrainingProgram? program =
          await ref.read(apiClientProvider).activeProgram();
      if (program == null) return;
      final WorkoutCacheStore cache = ref.read(workoutCacheStoreProvider);
      await cache.writeProgram(accountId, program);
    } on Object {
      // The online Program tab still fetches the authoritative copy.
    }
  }

  Future<void> _confirmClear() async {
    final bool? confirmed = await showDialog<bool>(
      context: context,
      builder: (BuildContext context) => AlertDialog(
        title: const Text('Clear chat history?'),
        content:
            const Text('This permanently deletes your assistant chat history.'),
        actions: <Widget>[
          TextButton(
            onPressed: () => Navigator.of(context).pop(false),
            child: const Text('Cancel'),
          ),
          FilledButton(
            onPressed: () => Navigator.of(context).pop(true),
            child: const Text('Clear'),
          ),
        ],
      ),
    );
    if (confirmed != true || !mounted) return;
    final String? accountId = _accountId;
    if (accountId == null) return;
    _setStateIfMounted(() => _sendError = null);
    try {
      await ref.read(apiClientProvider).clearChatHistory();
      await _store.clearHistory(accountId);
      _setStateIfMounted(() {
        _messages = <ChatMessage>[];
        _failedContent = null;
        _offline = false;
      });
    } on ApiException catch (error) {
      _setStateIfMounted(() {
        _sendError = error.statusCode == null
            ? 'Clearing history needs a connection.'
            : error.message;
      });
    }
  }

  bool get _composerEnabled =>
      _disclosureLoaded && _disclosureAccepted && !_sending && !_offline;

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Assistant'),
        actions: <Widget>[
          IconButton(
            key: const Key('chat_clear'),
            tooltip: 'Clear chat history',
            onPressed: _messages.isEmpty ? null : _confirmClear,
            icon: const Icon(Icons.delete_outline),
          ),
        ],
      ),
      body: _disclosureLoaded && _loadingHistory && _messages.isEmpty
          ? const Center(child: CircularProgressIndicator())
          : Column(
              children: <Widget>[
                if (!_disclosureAccepted) _disclosureCard(),
                if (_offline) _OfflineChatBanner(onRetry: _retryHistory),
                if (_historyError != null)
                  _ErrorBanner(
                    message: _historyError!,
                    onRetry: _loadHistory,
                  ),
                Expanded(child: _messageList()),
                if (_sendError != null)
                  _ErrorBanner(
                    key: const Key('chat_send_error'),
                    message: _sendError!,
                    onRetry: _failedContent == null ? null : _retry,
                  ),
                _composer(),
              ],
            ),
    );
  }

  Widget _disclosureCard() {
    return Card(
      key: const Key('chat_disclosure'),
      margin: const EdgeInsets.all(12),
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: <Widget>[
            Row(
              children: <Widget>[
                const Icon(Icons.privacy_tip_outlined, size: 18),
                const SizedBox(width: 8),
                Text('Before you start',
                    style: Theme.of(context).textTheme.titleMedium),
              ],
            ),
            const SizedBox(height: 8),
            const Text(hostedChatDisclosure),
            const SizedBox(height: 12),
            Align(
              alignment: Alignment.centerRight,
              child: FilledButton(
                key: const Key('chat_disclosure_accept'),
                onPressed: _acceptDisclosure,
                child: const Text('I understand'),
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _messageList() {
    if (_messages.isEmpty && _streamingText == null) {
      return Center(
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: Text(
            _disclosureAccepted
                ? 'Ask your assistant about training, technique, or your program.'
                : 'Accept the disclosure to start chatting.',
            textAlign: TextAlign.center,
          ),
        ),
      );
    }
    final bool showStreaming = _streamingText != null;
    return ListView.builder(
      padding: const EdgeInsets.all(12),
      itemCount: _messages.length + (showStreaming ? 1 : 0),
      itemBuilder: (BuildContext context, int index) {
        if (index >= _messages.length) {
          final String text = _streamingText ?? '';
          return _bubble(
            context,
            role: 'assistant',
            child: text.isEmpty ? const _TypingIndicator() : Text(text),
          );
        }
        final ChatMessage message = _messages[index];
        if (message.isDebriefPointer) {
          return _DebriefCard(message: message);
        }
        return _bubble(
          context,
          role: message.role,
          child: Text(message.content),
        );
      },
    );
  }

  Widget _bubble(BuildContext context,
      {required String role, required Widget child}) {
    final bool user = role == 'user';
    final ColorScheme colors = Theme.of(context).colorScheme;
    return Align(
      alignment: user ? Alignment.centerRight : Alignment.centerLeft,
      child: Container(
        margin: const EdgeInsets.symmetric(vertical: 4),
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
        constraints:
            BoxConstraints(maxWidth: MediaQuery.of(context).size.width * 0.78),
        decoration: BoxDecoration(
          color:
              user ? colors.primaryContainer : colors.surfaceContainerHighest,
          borderRadius: BorderRadius.circular(12),
        ),
        child: child,
      ),
    );
  }

  Widget _composer() {
    final String? helper = _offline && !_disclosureAccepted
        ? null
        : !_disclosureAccepted
            ? 'Accept the disclosure above to enable chat.'
            : _offline
                ? 'Chat needs a connection.'
                : null;
    return SafeArea(
      top: false,
      child: Padding(
        padding: const EdgeInsets.fromLTRB(12, 4, 12, 8),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.end,
          children: <Widget>[
            Expanded(
              child: TextField(
                key: const Key('chat_composer'),
                controller: _controller,
                enabled: _composerEnabled,
                minLines: 1,
                maxLines: 4,
                textInputAction: TextInputAction.newline,
                decoration: InputDecoration(
                  hintText: _offline ? 'Offline' : 'Message your assistant',
                  helperText: helper,
                  border: const OutlineInputBorder(),
                ),
                onSubmitted: (_) => _send(),
              ),
            ),
            const SizedBox(width: 8),
            IconButton.filled(
              key: const Key('chat_send'),
              tooltip: 'Send',
              onPressed: _composerEnabled ? _send : null,
              icon: _sending
                  ? const SizedBox(
                      height: 18,
                      width: 18,
                      child: CircularProgressIndicator(strokeWidth: 2),
                    )
                  : const Icon(Icons.send),
            ),
          ],
        ),
      ),
    );
  }
}

class _DebriefCard extends StatelessWidget {
  const _DebriefCard({required this.message});

  final ChatMessage message;

  @override
  Widget build(BuildContext context) {
    return Card(
      key: const Key('chat_debrief'),
      margin: const EdgeInsets.symmetric(vertical: 6),
      child: ListTile(
        leading: const Icon(Icons.assignment_turned_in_outlined),
        title: const Text('Session debrief'),
        subtitle: Text(message.content),
      ),
    );
  }
}

class _TypingIndicator extends StatelessWidget {
  const _TypingIndicator();

  @override
  Widget build(BuildContext context) => const Text('Assistant is replying…');
}

class _OfflineChatBanner extends StatelessWidget {
  const _OfflineChatBanner({required this.onRetry});

  final VoidCallback onRetry;

  @override
  Widget build(BuildContext context) {
    return Container(
      key: const Key('chat_offline_banner'),
      width: double.infinity,
      margin: const EdgeInsets.fromLTRB(12, 8, 12, 0),
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
      decoration: BoxDecoration(
        color: Theme.of(context).colorScheme.errorContainer,
        borderRadius: BorderRadius.circular(8),
      ),
      child: Row(
        children: <Widget>[
          Icon(Icons.cloud_off,
              size: 18, color: Theme.of(context).colorScheme.onErrorContainer),
          const SizedBox(width: 8),
          Expanded(
            child: Text(
              'Offline — showing saved chat history. Sending needs a connection.',
              style: TextStyle(
                  color: Theme.of(context).colorScheme.onErrorContainer),
            ),
          ),
          TextButton(
            key: const Key('chat_offline_retry'),
            onPressed: onRetry,
            child: const Text('Retry'),
          ),
        ],
      ),
    );
  }
}

class _ErrorBanner extends StatelessWidget {
  const _ErrorBanner({super.key, required this.message, this.onRetry});

  final String message;
  final VoidCallback? onRetry;

  @override
  Widget build(BuildContext context) {
    return Container(
      width: double.infinity,
      margin: const EdgeInsets.fromLTRB(12, 8, 12, 0),
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
      decoration: BoxDecoration(
        color: Theme.of(context).colorScheme.errorContainer,
        borderRadius: BorderRadius.circular(8),
      ),
      child: Row(
        children: <Widget>[
          Expanded(child: Text(message)),
          if (onRetry != null)
            TextButton(
              key: const Key('chat_retry'),
              onPressed: onRetry,
              child: const Text('Retry'),
            ),
        ],
      ),
    );
  }
}

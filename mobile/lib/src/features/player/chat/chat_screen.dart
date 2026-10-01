import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api_client.dart';
import '../../../core/chat_models.dart';
import '../../../core/chat_storage.dart';
import '../../../core/models.dart';
import '../../../core/theme/mayos_spacing.dart';
import '../../../core/theme/mayos_theme.dart';
import '../../../core/ui/mayos_button.dart';
import '../../../core/ui/mayos_card.dart';
import '../../../core/ui/mayos_markdown.dart';
import '../../../core/ui/mayos_scaffold.dart';
import '../../../core/ui/mayos_text_field.dart';
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
  String? _streamingMessageId;
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
    final String assistantMessageId =
        'local-assistant-${DateTime.now().microsecondsSinceEpoch}';
    final bool addUserBubble = _retryAddsBubble;
    _setStateIfMounted(() {
      _sending = true;
      _sendError = null;
      _failedContent = null;
      _streamingText = '';
      _streamingMessageId = assistantMessageId;
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
                  id: assistantMessageId,
                  role: 'assistant',
                  content: reply,
                ),
              ];
              _streamingText = null;
              _streamingMessageId = null;
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
      _streamingMessageId = null;
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
      final ProgramDay? nextWorkout = program.days.isEmpty ? null : program.days.first;
      if (nextWorkout != null) {
        try {
          final prescription = await ref.read(apiClientProvider).prescription(nextWorkout.dayOrder);
          await cache.writePrescription(accountId, nextWorkout.dayOrder, prescription);
        } on Object {
          // Keep the existing next-workout prescription if refresh fails.
        }
      }
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
    return MayosScaffold(
      title: 'Assistant',
      showBack: true,
      actions: <Widget>[
        IconButton(
          key: const Key('chat_clear'),
          tooltip: 'Clear chat history',
          onPressed: _messages.isEmpty ? null : _confirmClear,
          icon: const Icon(Icons.delete_outline),
        ),
      ],
      body: _disclosureLoaded && _loadingHistory && _messages.isEmpty
          ? const Center(child: CircularProgressIndicator())
          : Column(
              children: <Widget>[
                // The gate, banners, and history share one scroll view so the
                // composer stays docked at the bottom at any text scale (#54).
                Expanded(child: _scrollableBody()),
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
    final MayosThemeExtension c = MayosTheme.of(context);
    return Padding(
      padding: const EdgeInsets.all(MayosSpacing.md),
      child: MayosCard(
        key: const Key('chat_disclosure'),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: <Widget>[
            Row(
              children: <Widget>[
                Icon(Icons.privacy_tip_outlined, size: 18, color: c.accent),
                const SizedBox(width: MayosSpacing.xs),
                Expanded(
                  child: Text('Before you start',
                      style: Theme.of(context).textTheme.titleMedium),
                ),
              ],
            ),
            const SizedBox(height: MayosSpacing.xs),
            const Text(hostedChatDisclosure),
            const SizedBox(height: MayosSpacing.sm),
            Align(
              alignment: Alignment.centerRight,
              child: MayosButton(
                key: const Key('chat_disclosure_accept'),
                label: 'I understand',
                expand: false,
                onPressed: _acceptDisclosure,
              ),
            ),
          ],
        ),
      ),
    );
  }

  /// The disclosure gate, transient banners, and message history in one
  /// scroll view. A short history is anchored to the top of the remaining
  /// space; the composer below is always pinned to the bottom (#54).
  Widget _scrollableBody() {
    final List<Widget> banners = <Widget>[
      if (!_disclosureAccepted) _disclosureCard(),
      if (_offline) _OfflineChatBanner(onRetry: _retryHistory),
      if (_historyError != null)
        _ErrorBanner(message: _historyError!, onRetry: _loadHistory),
    ];
    final bool empty = _messages.isEmpty && _streamingText == null;
    return CustomScrollView(
      slivers: <Widget>[
        if (banners.isNotEmpty)
          SliverToBoxAdapter(
            child: Column(children: banners),
          ),
        if (empty)
          SliverFillRemaining(
            hasScrollBody: false,
            child: _emptyState(),
          )
        else
          SliverPadding(
            padding: const EdgeInsets.all(MayosSpacing.md),
            sliver: SliverList(
              delegate: SliverChildBuilderDelegate(
                _buildMessageItem,
                childCount: _messages.length + (_streamingText != null ? 1 : 0),
              ),
            ),
          ),
      ],
    );
  }

  Widget _emptyState() {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(MayosSpacing.xl),
        child: Text(
          _disclosureAccepted
              ? 'Ask your assistant about training, technique, or your program.'
              : 'Accept the disclosure to start chatting.',
          textAlign: TextAlign.center,
        ),
      ),
    );
  }

  Widget _buildMessageItem(BuildContext context, int index) {
    if (index >= _messages.length) {
      final String text = _streamingText ?? '';
      return _bubble(
        context,
        role: 'assistant',
        child: text.isEmpty
            ? const _TypingIndicator()
            : MayosMarkdown(
                key: ValueKey<String>(_streamingMessageId!),
                source: text,
              ),
      );
    }
    final ChatMessage message = _messages[index];
    if (message.isDebriefPointer) {
      return _DebriefCard(message: message);
    }
    return _bubble(
      context,
      role: message.role,
      child: message.role == 'assistant'
          ? MayosMarkdown(
              key: ValueKey<String>(message.id),
              source: message.content,
            )
          : Text(message.content),
    );
  }

  Widget _bubble(BuildContext context,
      {required String role, required Widget child}) {
    final bool user = role == 'user';
    final MayosThemeExtension c = MayosTheme.of(context);
    return Align(
      alignment: user ? Alignment.centerRight : Alignment.centerLeft,
      child: Container(
        margin: const EdgeInsets.symmetric(vertical: MayosSpacing.xxs),
        padding: const EdgeInsets.symmetric(
            horizontal: MayosSpacing.sm, vertical: MayosSpacing.xs),
        constraints:
            BoxConstraints(maxWidth: MediaQuery.of(context).size.width * 0.78),
        decoration: BoxDecoration(
          color: user ? c.accent : c.secondarySurface,
          borderRadius: BorderRadius.circular(12),
          border: Border.all(color: user ? c.accent : c.border),
        ),
        child: DefaultTextStyle.merge(
          style: TextStyle(color: user ? c.onAccent : c.textPrimary),
          child: child,
        ),
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
    final MayosThemeExtension c = MayosTheme.of(context);
    return SafeArea(
      key: const Key('chat_composer_bar'),
      top: false,
      child: Padding(
        padding: const EdgeInsets.fromLTRB(MayosSpacing.sm, MayosSpacing.xxs,
            MayosSpacing.sm, MayosSpacing.xs),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.end,
          children: <Widget>[
            Expanded(
              child: MayosTextField(
                fieldKey: const Key('chat_composer'),
                controller: _controller,
                enabled: _composerEnabled,
                minLines: 1,
                maxLines: 4,
                textInputAction: TextInputAction.newline,
                hint: _offline ? 'Offline' : 'Message your assistant',
                helperText: helper,
                onSubmitted: (_) => _send(),
              ),
            ),
            const SizedBox(width: MayosSpacing.xs),
            Semantics(
              label: 'Send',
              button: true,
              child: IconButton.filled(
                key: const Key('chat_send'),
                tooltip: 'Send',
                style: IconButton.styleFrom(
                  backgroundColor: c.accent,
                  foregroundColor: c.onAccent,
                  disabledBackgroundColor: c.surfaceSunken,
                  disabledForegroundColor: c.textDisabled,
                  minimumSize:
                      const Size(kMayosMinTapTarget, kMayosMinTapTarget),
                ),
                onPressed: _composerEnabled ? _send : null,
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

class _DebriefCard extends StatelessWidget {
  const _DebriefCard({required this.message});

  final ChatMessage message;

  @override
  Widget build(BuildContext context) {
    final MayosThemeExtension c = MayosTheme.of(context);
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: MayosSpacing.xs),
      child: MayosCard(
        key: const Key('chat_debrief'),
        color: c.accentSubtle,
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: <Widget>[
            Icon(Icons.assignment_turned_in_outlined, color: c.accent),
            const SizedBox(width: MayosSpacing.sm),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: <Widget>[
                  Text('Session debrief',
                      style: Theme.of(context).textTheme.titleSmall),
                  const SizedBox(height: MayosSpacing.xxs),
                  MayosMarkdown(source: message.content),
                ],
              ),
            ),
          ],
        ),
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
    final MayosThemeExtension c = MayosTheme.of(context);
    return Container(
      key: const Key('chat_offline_banner'),
      width: double.infinity,
      margin: const EdgeInsets.fromLTRB(
          MayosSpacing.md, MayosSpacing.sm, MayosSpacing.md, 0),
      padding: const EdgeInsets.symmetric(
          horizontal: MayosSpacing.md, vertical: MayosSpacing.xs),
      decoration: BoxDecoration(
        color: c.secondarySurface,
        borderRadius: MayosRadii.mediumRadius,
        border: Border.all(color: c.border),
      ),
      child: Row(
        children: <Widget>[
          Icon(Icons.cloud_off, size: 18, color: c.textSecondary),
          const SizedBox(width: MayosSpacing.xs),
          Expanded(
            child: Text(
              'Offline — showing saved chat history. Sending needs a connection.',
              style: Theme.of(context)
                  .textTheme
                  .bodySmall
                  ?.copyWith(color: c.textSecondary),
            ),
          ),
          MayosButton(
            key: const Key('chat_offline_retry'),
            label: 'Retry',
            variant: MayosButtonVariant.tertiary,
            expand: false,
            onPressed: onRetry,
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
    final MayosThemeExtension c = MayosTheme.of(context);
    return Container(
      width: double.infinity,
      margin: const EdgeInsets.fromLTRB(
          MayosSpacing.md, MayosSpacing.sm, MayosSpacing.md, 0),
      padding: const EdgeInsets.symmetric(
          horizontal: MayosSpacing.md, vertical: MayosSpacing.xs),
      decoration: BoxDecoration(
        color: c.secondarySurface,
        borderRadius: MayosRadii.mediumRadius,
        border: Border.all(color: c.danger),
      ),
      child: Row(
        children: <Widget>[
          Expanded(
            child: Text(
              message,
              style: Theme.of(context)
                  .textTheme
                  .bodySmall
                  ?.copyWith(color: c.danger),
            ),
          ),
          if (onRetry != null)
            MayosButton(
              key: const Key('chat_retry'),
              label: 'Retry',
              variant: MayosButtonVariant.tertiary,
              expand: false,
              onPressed: onRetry,
            ),
        ],
      ),
    );
  }
}

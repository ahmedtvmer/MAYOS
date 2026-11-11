import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter/services.dart';

import '../../../core/api_client.dart';
import '../../../core/refetch_on_reconnect.dart';
import '../../../core/app_failure.dart';
import '../../../core/connectivity_message.dart';
import '../../../core/chat_models.dart';
import '../../../core/chat_message_limit.dart';
import '../../../core/display_language/catalog.dart';
import '../../../core/display_language/controller.dart';
import '../../../core/display_language/copy_context.dart';
import '../../../core/chat_storage.dart';
import '../../../core/models.dart';
import '../../../core/theme/mayos_spacing.dart';
import '../../../core/theme/mayos_theme.dart';
import '../../../core/theme/mayos_typography.dart';
import '../../../core/ui/mayos_button.dart';
import '../../../core/ui/mayos_card.dart';
import '../../../core/ui/mayos_markdown.dart';
import '../../../core/ui/mayos_scaffold.dart';
import '../../../core/ui/mayos_text_field.dart';
import '../../../core/ui/first_strong_direction.dart';
import '../../../core/workout_storage.dart';
import '../../../providers.dart';
import '../assignment/program_request_dialog.dart';
import '../tour/tour_targets.dart';

/// Hosted player-assistant chat (#37, ADR 016/036).
///
/// Reads and writes go through `POST/GET/DELETE /chat/*`. Chat requires
/// connectivity: the composer disables with an explanatory message once a load
/// or send fails with a network error, and sends are never queued. The
/// last-loaded history is cached per account so it stays readable offline.
MayosCopy _chatCopy(BuildContext context) => MayosCopy(
      ProviderScope.containerOf(context).read(displayLanguageProvider),
    );

class ChatScreen extends ConsumerStatefulWidget {
  const ChatScreen({super.key});

  @override
  ConsumerState<ChatScreen> createState() => _ChatScreenState();
}

class _ProgramEditPreviewCard extends StatefulWidget {
  const _ProgramEditPreviewCard({
    required this.preview,
    required this.arabic,
    required this.onDecision,
  });

  final Map<String, dynamic> preview;
  final bool arabic;
  final Future<bool> Function(bool confirm, List<String> selectedOptional)
      onDecision;

  @override
  State<_ProgramEditPreviewCard> createState() =>
      _ProgramEditPreviewCardState();
}

class _ProgramEditPreviewCardState extends State<_ProgramEditPreviewCard> {
  final Set<String> _selected = <String>{};
  bool _busy = false;

  String _exercisePrescription(Map<String, dynamic> exercise) {
    final List<dynamic> groups = exercise['set_groups'] is List<dynamic>
        ? exercise['set_groups'] as List<dynamic>
        : <dynamic>[];
    if (groups.length > 1) {
      final String prescriptions = groups
          .whereType<Map<String, dynamic>>()
          .map((Map<String, dynamic> group) =>
              '${group['sets']} × ${group['reps_min']}-${group['reps_max']} '
              '${widget.arabic ? 'تكرار' : 'reps'}, ${group['rir']} RIR')
          .join('; ');
      return '${exercise['name']} · $prescriptions · '
          '${widget.arabic ? 'راحة' : 'rest'} ${exercise['rest_seconds']}s';
    }
    final String optional = exercise['optional'] == true
        ? (widget.arabic ? 'اختياري: ' : 'Optional: ')
        : '';
    if (widget.arabic) {
      return '$optional${exercise['name']} · ${exercise['sets']} مجموعات · '
          '${exercise['reps_min']}-${exercise['reps_max']} تكرار · '
          '${exercise['rir']} RIR · راحة ${exercise['rest_seconds']} ثانية';
    }
    return '$optional${exercise['name']} · ${exercise['sets']} sets · '
        '${exercise['reps_min']}-${exercise['reps_max']} reps · '
        '${exercise['rir']} RIR · ${exercise['rest_seconds']}s';
  }

  Future<void> _decide(bool confirm) async {
    setState(() => _busy = true);
    final bool resolved =
        await widget.onDecision(confirm, _selected.toList(growable: false));
    if (!mounted) return;
    setState(() => _busy = false);
    if (!resolved) {
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(
        content: Text(widget.arabic
            ? 'المعاينة انتهت أو حصل خطأ. حدّث المحادثة.'
            : 'The preview expired or could not be saved. Refresh chat.'),
      ));
    }
  }

  @override
  Widget build(BuildContext context) {
    final List<dynamic> days = widget.preview['days'] is List<dynamic>
        ? widget.preview['days'] as List<dynamic>
        : <dynamic>[];
    final List<dynamic> optional = widget.preview['optional'] is List<dynamic>
        ? widget.preview['optional'] as List<dynamic>
        : <dynamic>[];
    final List<dynamic> warnings = widget.preview['warnings'] is List<dynamic>
        ? widget.preview['warnings'] as List<dynamic>
        : <dynamic>[];
    return Card(
      key: const Key('chat_program_edit_preview'),
      child: Padding(
        padding: const EdgeInsets.all(MayosSpacing.md),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: <Widget>[
            Text(widget.arabic ? 'معاينة تعديل البرنامج' : 'Program edit preview',
                style: Theme.of(context).textTheme.titleSmall),
            for (final dynamic day in days)
              if (day is Map<String, dynamic>) ...<Widget>[
                const SizedBox(height: MayosSpacing.xs),
                Text(day['week_order'] == null
                    ? (day['day_name']?.toString() ?? '')
                    : '${widget.arabic ? 'الأسبوع' : 'Week'} ${day['week_order']} · ${day['day_name']}'),
                for (final dynamic exercise in
                    (day['exercises'] is List<dynamic>
                        ? day['exercises'] as List<dynamic>
                        : <dynamic>[]))
                  if (exercise is Map<String, dynamic>)
                    Padding(
                      padding: const EdgeInsets.only(left: MayosSpacing.sm),
                      child: Text(_exercisePrescription(exercise)),
                    ),
              ],
            for (final dynamic option in optional)
              if (option is Map<String, dynamic>)
                CheckboxListTile(
                  key: Key('chat_program_edit_optional_${option['exercise_id']}'),
                  contentPadding: EdgeInsets.zero,
                  value: _selected.contains(option['exercise_id']?.toString()),
                  title: Text(
                    '${widget.arabic ? 'اختياري' : 'Optional'}: ${option['name']} '
                    '(${option['sets']} ${widget.arabic ? 'مجموعات' : 'sets'})',
                  ),
                  onChanged: _busy
                      ? null
                      : (bool? checked) {
                          final String id = option['exercise_id'].toString();
                          setState(() {
                            if (checked == true) {
                              _selected.add(id);
                            } else {
                              _selected.remove(id);
                            }
                          });
                        },
                ),
            for (final dynamic warning in warnings)
              if (warning is Map<String, dynamic>)
                Text(widget.arabic
                    ? 'مراجعة الحجم: ${warning['muscle']}'
                    : 'Volume review: ${warning['muscle']}'),
            const SizedBox(height: MayosSpacing.sm),
            Wrap(
              spacing: MayosSpacing.sm,
              children: <Widget>[
                MayosButton(
                  key: const Key('chat_program_edit_confirm'),
                  label: widget.arabic ? 'تأكيد' : 'Confirm',
                  expand: false,
                  onPressed: _busy ? null : () => _decide(true),
                ),
                MayosButton(
                  key: const Key('chat_program_edit_cancel'),
                  label: widget.arabic ? 'إلغاء' : 'Cancel',
                  variant: MayosButtonVariant.tertiary,
                  expand: false,
                  onPressed: _busy ? null : () => _decide(false),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }
}

class _ChatScreenState extends ConsumerState<ChatScreen>
    with RefetchOnReconnect<ChatScreen> {
  @override
  Future<void> refreshAfterReconnect() async {
    if (!_sending) await _loadHistory();
  }

  final TextEditingController _controller = TextEditingController();

  bool _disposed = false;
  StreamSubscription<ChatStreamEvent>? _subscription;

  bool _disclosureLoaded = false;
  bool _disclosureAccepted = false;
  bool _loadingHistory = true;
  bool _offline = false;
  FailureMessage? _historyFailure;
  List<ChatMessage> _messages = <ChatMessage>[];
  bool _sending = false;
  String? _streamingText;
  String? _streamingMessageId;
  String? _toolStatus;
  String? _sendError;
  FailureMessage? _sendFailure;
  String? _failedContent;
  bool _retryAddsBubble = true;
  final Set<String> _resolvedProgramEditPreviews = <String>{};
  late StateController<bool> _playerChatStreaming;

  String? get _accountId =>
      ref.read(authControllerProvider).session?.account.accountId;

  ChatCacheStore get _store => ref.read(chatCacheStoreProvider);

  @override
  void initState() {
    super.initState();
    _playerChatStreaming = ref.read(playerChatStreamingProvider.notifier);
    _init();
  }

  @override
  void dispose() {
    _disposed = true;
    unawaited(Future<void>.microtask(() {
      if (_playerChatStreaming.mounted) {
        _playerChatStreaming.state = false;
      }
    }));
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
        _historyFailure = const AppFailureMessage(
          AppFailureId.chatAccountNotSignedIn,
          'You are not signed in.',
        );
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
      _historyFailure = null;
    });
    try {
      final List<ChatMessage> fresh =
          await ref.read(apiClientProvider).chatHistory();
      await _store.writeHistory(accountId, fresh);
      _setStateIfMounted(() {
        _messages = fresh;
        _offline = false;
        _historyFailure = null;
        _loadingHistory = false;
      });
      unawaited(ref.read(authControllerProvider.notifier).refreshAccount());
    } on ApiException catch (error) {
      _setStateIfMounted(() {
        _loadingHistory = false;
        if (error.statusCode == null) {
          // Network failure: keep the cached history and read-only offline.
          _offline = true;
        } else {
          _historyFailure = apiFailureMessage(error);
        }
      });
    }
  }

  /// The offline banner's retry: reload from the server and, on success, leave
  /// the offline state so the composer re-enables.
  Future<void> _retryHistory() => _loadHistory();

  void _refreshAllowanceAfterIncompleteTurn() {
    if (_disposed) return;
    unawaited(ref.read(authControllerProvider.notifier).refreshAccount());
  }

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
    ref.read(playerChatStreamingProvider.notifier).state = true;
    final String assistantMessageId =
        'local-assistant-${DateTime.now().microsecondsSinceEpoch}';
    final bool addUserBubble = _retryAddsBubble;
    _setStateIfMounted(() {
      _sending = true;
      _sendError = null;
      _sendFailure = null;
      _failedContent = null;
      _streamingText = '';
      _streamingMessageId = assistantMessageId;
      _toolStatus = null;
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
            _setStateIfMounted(() {
              _streamingText = buffer;
              _toolStatus = null;
            });
          case ChatStatus(:final String status):
            _setStateIfMounted(() => _toolStatus = status);
          case ChatDone(
              :final String responseContent,
              :final bool programUpdated,
              :final bool movementRestrictionsUpdated,
              :final String outcome,
              :final AiAllowance? lifterAllowance,
              :final ProgramRequestDraft? requestSuggestion,
              :final Map<String, dynamic>? programEditPreview
            ):
            if (outcome == 'truncated') {
              finished = true;
              _refreshAllowanceAfterIncompleteTurn();
              final String message =
                  MayosCopy(ref.read(displayLanguageProvider)).aiAnswerTruncated;
              await _failTurn(content, message);
              return;
            }
            if (lifterAllowance != null) {
              ref.read(authControllerProvider.notifier).updateLifterAiAllowance(
                    accountId,
                    lifterAllowance,
                  );
            } else {
              unawaited(ref.read(authControllerProvider.notifier).refreshAccount());
            }
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
                  requestSuggestion: requestSuggestion,
                  programEditPreview: programEditPreview,
                ),
              ];
              _streamingText = null;
              _streamingMessageId = null;
              _toolStatus = null;
              _sending = false;
              _offline = false;
              _historyFailure = null;
            });
            ref.read(playerChatStreamingProvider.notifier).state = false;
            await _store.writeHistory(accountId, _messages);
            if (programUpdated) {
              unawaited(_refreshProgramCache());
            }
            if (movementRestrictionsUpdated) {
              unawaited(ref.read(activeWorkoutControllerProvider.notifier)
                  .refreshMovementRestrictionAnnotations());
            }
          case ChatError(
              :final String detail,
              :final String? messageCode,
              :final Map<String, dynamic>? messageParams,
              :final String? messageFallback
            ):
            finished = true;
            _refreshAllowanceAfterIncompleteTurn();
            final ServerFailureMessage failure = ServerFailureMessage(
              detail,
              messageCode: messageCode,
              messageParams: messageParams,
              messageFallback: messageFallback,
            );
            await _failTurn(
              content,
              MayosCopy(ref.read(displayLanguageProvider))
                  .failureMessage(failure),
              failure: failure,
            );
            return;
        }
      }
    } on ApiException catch (error) {
      _refreshAllowanceAfterIncompleteTurn();
      final bool offline = error.statusCode == null;
      final FailureMessage failure = offline
          ? const AppFailureMessage(
              AppFailureId.chatReconnectRetry,
              'Chat needs a connection. Reconnect and retry.',
            )
          : apiFailureMessage(error);
      await _failTurn(
        content,
        MayosCopy(ref.read(displayLanguageProvider)).failureMessage(failure),
        offline: offline,
        failure: failure,
      );
      return;
    } on Object {
      _refreshAllowanceAfterIncompleteTurn();
      const FailureMessage failure = AppFailureMessage(
        AppFailureId.assistantDidNotFinish,
        'The assistant did not finish. Please retry.',
      );
      await _failTurn(
        content,
        MayosCopy(ref.read(displayLanguageProvider)).failureMessage(failure),
        failure: failure,
      );
      return;
    }
    if (!_disposed && !finished && _sending) {
      const FailureMessage failure = AppFailureMessage(
        AppFailureId.assistantDidNotFinish,
        'The assistant did not finish. Please retry.',
      );
      await _failTurn(
        content,
        MayosCopy(ref.read(displayLanguageProvider)).failureMessage(failure),
        failure: failure,
      );
    }
  }

  /// Records a failed turn: shows the error, reloads the server history so the
  /// persisted (unanswered) user message appears exactly once, and arms Retry.
  /// A retry re-sends the same content without adding another local bubble.
  Future<void> _failTurn(String content, String message,
      {bool offline = false, FailureMessage? failure}) async {
    ref.read(playerChatStreamingProvider.notifier).state = false;
    _setStateIfMounted(() {
      _streamingText = null;
      _streamingMessageId = null;
      _toolStatus = null;
      _sending = false;
      _offline = _offline || offline;
      _sendError = message;
      _sendFailure = failure;
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
      if (!mounted) return;
      ref.read(playerProgramUpdateProvider.notifier).state =
          PlayerProgramUpdate(
        accountId: accountId,
        program: program,
        fromCache: false,
      );
      await cache.writeProgram(accountId, program);
      final ProgramDay? nextWorkout =
          program.days.isEmpty ? null : program.days.first;
      if (nextWorkout != null) {
        try {
          final prescription = await ref
              .read(apiClientProvider)
              .prescription(nextWorkout.dayOrder);
          await cache.writePrescription(
              accountId, nextWorkout.dayOrder, prescription);
        } on Object {
          // Keep the existing next-workout prescription if refresh fails.
        }
      }
    } on Object {
      // The online Program tab still fetches the authoritative copy.
    }
  }

  Future<void> _confirmClear() async {
    final MayosCopy copy = MayosCopy(ref.read(displayLanguageProvider));
    final bool? confirmed = await showDialog<bool>(
      context: context,
      builder: (BuildContext context) => AlertDialog(
        title: Text(copy.clearChatHistoryQuestion),
        content: Text(copy.clearChatHistoryConfirmation),
        actions: <Widget>[
          TextButton(
            onPressed: () => Navigator.of(context).pop(false),
            child: Text(copy.cancel),
          ),
          FilledButton(
            onPressed: () => Navigator.of(context).pop(true),
            child: Text(copy.clear),
          ),
        ],
      ),
    );
    if (confirmed != true || !mounted) return;
    final String? accountId = _accountId;
    if (accountId == null) return;
    _setStateIfMounted(() {
      _sendError = null;
      _sendFailure = null;
    });
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
        _sendFailure = error.statusCode == null
            ? const AppFailureMessage(
                AppFailureId.clearingHistoryNeedsConnection,
                'Clearing history needs a connection.',
              )
            : apiFailureMessage(error);
        _sendError = copy.failureMessage(_sendFailure!);
      });
    }
  }

  bool get _composerEnabled =>
      _disclosureLoaded && _disclosureAccepted && !_sending && !_offline;

  @override
  Widget build(BuildContext context) {
    ref.watch(authControllerProvider);
    final MayosCopy copy = MayosCopy(ref.watch(displayLanguageProvider));
    return MayosScaffold(
      title: copy.assistant,
      showBack: true,
      actions: <Widget>[
        IconButton(
          key: const Key('chat_clear'),
          tooltip: copy.clearChatHistory,
          onPressed: _messages.isEmpty ? null : _confirmClear,
          icon: const Icon(Icons.delete_outline),
        ),
      ],
      body: Column(
              children: <Widget>[
                // The gate, banners, and history share one scroll view so the
                // composer stays docked at the bottom at any text scale (#54).
                Expanded(child: _scrollableBody()),
                if (_sendError != null)
                  _ErrorBanner(
                    key: const Key('chat_send_error'),
                    message: _sendFailure == null
                        ? _sendError!
                        : copy.failureMessage(_sendFailure!),
                    onRetry: _failedContent == null ? null : _retry,
                  ),
                TourTarget(
                  id: 'whats_new_edit_program_chat',
                  child: _composer(),
                ),
              ],
            ),
    );
  }

  Widget _disclosureCard() {
    final MayosCopy copy = MayosCopy(ref.read(displayLanguageProvider));
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
                  child: Text(copy.beforeYouStart,
                      style: Theme.of(context).textTheme.titleMedium),
                ),
              ],
            ),
            const SizedBox(height: MayosSpacing.xs),
            Text(displayCopyOf(context).hostedChatDisclosure),
            const SizedBox(height: MayosSpacing.sm),
            Align(
              alignment: AlignmentDirectional.centerEnd,
              child: MayosButton(
                key: const Key('chat_disclosure_accept'),
                label: copy.understood,
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
    final AiAllowance? allowance =
        ref.read(authControllerProvider).session?.account.lifterAiAllowance;
    final List<Widget> banners = <Widget>[
      if (!_disclosureAccepted) _disclosureCard(),
      if (allowance?.mode == 'launch')
        _AllowanceBanner(
          key: const Key('chat_allowance_summary'),
          message: allowance!.requestsRemaining == 0
              ? displayCopyOf(context).lifterAllowanceExhausted(allowance.resetAt)
              : displayCopyOf(context).lifterAllowanceSummary(
                  allowance.requestsRemaining ?? 0,
                  allowance.resetAt,
                ),
        ),
      if (allowance?.status == 'warning')
        _AllowanceBanner(
          key: const Key('chat_allowance_warning'),
          message: displayCopyOf(context).aiAllowanceWarning(
            allowance!.requestsRemaining ?? 0,
            allowance.resetAt,
          ),
        ),
      if (allowance?.status == 'resource_cutoff')
        _AllowanceBanner(
          key: const Key('chat_allowance_cutoff'),
          message: displayCopyOf(context).aiAllowanceCutoff(
            allowance!.requestsRemaining ?? 0,
            allowance.resetAt,
          ),
        ),
      if (_offline) _OfflineChatBanner(onRetry: _retryHistory),
      if (_historyFailure != null)
        _ErrorBanner(
          message: displayCopyOf(context).failureMessage(_historyFailure!),
          onRetry: _loadHistory,
        ),
    ];
    final bool empty = _messages.isEmpty && _streamingText == null;
    return CustomScrollView(
      slivers: <Widget>[
        if (banners.isNotEmpty)
          SliverToBoxAdapter(
            child: Column(children: banners),
          ),
        if (_loadingHistory && _messages.isEmpty)
          const SliverFillRemaining(
            hasScrollBody: false,
            child: Center(child: CircularProgressIndicator()),
          )
        else if (empty)
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
              ? displayCopyOf(context).askAssistantAboutTraining
              : displayCopyOf(context).acceptDisclosureToStartChatting,
          textAlign: TextAlign.center,
        ),
      ),
    );
  }

  Widget _buildMessageItem(BuildContext context, int index) {
    if (index >= _messages.length) {
      final String text = _streamingText ?? '';
      final MayosThemeExtension colors = MayosTheme.of(context);
      return _bubble(
        context,
        role: 'assistant',
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: <Widget>[
            if (text.isEmpty)
              const _TypingIndicator()
            else
              MayosMarkdown(
                key: ValueKey<String>(_streamingMessageId!),
                source: text,
              ),
            if (_toolStatus != null) ...<Widget>[
              const SizedBox(height: MayosSpacing.xxs),
              Text(
                _toolStatus!,
                key: const Key('chat_tool_status'),
                style: MayosTypography.of(context)
                    .caption
                    .copyWith(color: colors.textSecondary),
              ),
            ],
          ],
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
          ? _assistantReplyContent(message)
          : FirstStrongDirection(
              text: message.content,
              child: Text(message.content),
            ),
    );
  }

  Widget _assistantReplyContent(ChatMessage message) {
    final ProgramRequestDraft? suggestion = message.requestSuggestion;
    final Map<String, dynamic>? editPreview = message.programEditPreview;
    final RegExp offerPattern = RegExp(r'<!--movement-offer:([0-9a-f-]{36})-->');
    final String? offerId = offerPattern.firstMatch(message.content)?.group(1);
    String? newestOfferId;
    for (final ChatMessage item in _messages.reversed) {
      if (item.role != 'assistant') continue;
      final String? found = offerPattern.firstMatch(item.content)?.group(1);
      if (found != null) { newestOfferId = found; break; }
    }
    final bool supersededOffer = offerId != null && newestOfferId != offerId;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: <Widget>[
        MayosMarkdown(
          key: ValueKey<String>(message.id),
          source: message.content,
        ),
        if (message.content.contains('Should I keep these out of your program?') ||
            message.content.contains('هل أستبعد هذه الحركات من برنامجك؟')) ...<Widget>[
          const SizedBox(height: MayosSpacing.xs),
          Wrap(spacing: MayosSpacing.xs, children: <Widget>[
            OutlinedButton(
              key: const Key('chat_confirm_movement_restrictions'),
              onPressed: _sending || supersededOffer || offerId == null ? null : () => _sendContent('yes $offerId'),
              child: Text(_chatCopy(context).isArabic ? 'نعم، استبعدها' : 'Yes, keep them out'),
            ),
            TextButton(
              key: const Key('chat_decline_movement_restrictions'),
              onPressed: _sending || supersededOffer || offerId == null ? null : () => _sendContent('no $offerId'),
              child: Text(_chatCopy(context).isArabic ? 'لا' : 'No'),
            ),
          ]),
        ],
        if (suggestion != null) ...<Widget>[
          const SizedBox(height: MayosSpacing.xs),
          MayosButton(
            key: const Key('chat_request_from_coach'),
            label: _chatCopy(context).requestFromCoach,
            icon: Icons.edit_note,
            variant: MayosButtonVariant.tertiary,
            expand: false,
            onPressed: () => _openRequestSuggestion(suggestion),
          ),
        ],
        if (editPreview != null &&
            !_resolvedProgramEditPreviews.contains(editPreview['id']))
          _ProgramEditPreviewCard(
            preview: editPreview,
            arabic: _chatCopy(context).isArabic,
            onDecision: (bool confirm, List<String> selected) =>
                _decideProgramEdit(editPreview, confirm, selected),
          ),
      ],
    );
  }

  Future<bool> _decideProgramEdit(
    Map<String, dynamic> preview,
    bool confirm,
    List<String> selectedOptional,
  ) async {
    try {
      await ref.read(apiClientProvider).decideChatProgramEditPreview(
            previewId: preview['id'] as String,
            confirm: confirm,
            includeOptional: selectedOptional,
          );
      _setStateIfMounted(() =>
          _resolvedProgramEditPreviews.add(preview['id'] as String));
      if (confirm) unawaited(_refreshProgramCache());
      return true;
    } on Object {
      unawaited(_loadHistory());
      return false;
    }
  }

  Future<void> _openRequestSuggestion(ProgramRequestDraft initialDraft) async {
    try {
      final ProgramRequest? created = await requestProgramChange(
        context,
        ref,
        initialDraft: initialDraft,
      );
      if (created == null || !mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text(displayCopyOf(context).programChangeRequestSent)),
      );
    } on ApiException catch (error) {
      if (!mounted) return;
      final String message = displayCopyOf(context).failureMessage(
        apiFailureMessage(error),
      );
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text(message)));
    }
  }

  Widget _bubble(BuildContext context,
      {required String role, required Widget child}) {
    final bool user = role == 'user';
    final MayosThemeExtension c = MayosTheme.of(context);
    return Align(
      alignment: user
          ? AlignmentDirectional.centerEnd
          : AlignmentDirectional.centerStart,
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
    final MayosCopy copy = MayosCopy(ref.read(displayLanguageProvider));
    final int typedCharacters = _controller.text.runes.length;
    final String? helper = _offline && !_disclosureAccepted
        ? null
        : !_disclosureAccepted
            ? copy.acceptDisclosureToEnableChat
            : _offline
                ? copy.chatNeedsConnection
                : null;
    final List<String> helperLines = <String>[
      if (helper != null) helper,
      if (typedCharacters >= chatMessageCounterStart)
        copy.chatCharactersLeft(chatMessageMaxChars - typedCharacters),
    ];
    final String? helperText =
        helperLines.isEmpty ? null : helperLines.join('\n');
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
              child: TourTarget(
                id: 'whats_new_assistant_why',
                child: MayosTextField(
                  fieldKey: const Key('chat_composer'),
                  controller: _controller,
                  enabled: _composerEnabled,
                  minLines: 1,
                  maxLines: 4,
                  maxLength: chatMessageMaxChars,
                  maxLengthEnforcement: MaxLengthEnforcement.enforced,
                  inputFormatters: const <TextInputFormatter>[
                    ChatMessageCodePointLengthFormatter(),
                  ],
                  hideCounter: true,
                  textInputAction: TextInputAction.newline,
                  hint: _offline ? copy.offline : copy.messageAssistant,
                  helperText: helperText,
                  onChanged: (_) => _setStateIfMounted(() {}),
                  onSubmitted: (_) => _send(),
                ),
              ),
            ),
            const SizedBox(width: MayosSpacing.xs),
            Semantics(
              label: copy.send,
              button: true,
              child: IconButton.filled(
                key: const Key('chat_send'),
                tooltip: copy.send,
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

class _AllowanceBanner extends StatelessWidget {
  const _AllowanceBanner({super.key, required this.message});

  final String message;

  @override
  Widget build(BuildContext context) {
    final MayosThemeExtension colors = MayosTheme.of(context);
    return Padding(
      padding: const EdgeInsets.all(MayosSpacing.md),
      child: MayosCard(
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: <Widget>[
            Icon(Icons.info_outline, size: 20, color: colors.accent),
            const SizedBox(width: MayosSpacing.xs),
            Expanded(
              child: Text(
                message,
                style: MayosTypography.of(context).body.copyWith(
                      color: colors.textPrimary,
                    ),
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
                  Text(_chatCopy(context).sessionDebrief,
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
  Widget build(BuildContext context) =>
      Text(_chatCopy(context).assistantReplying);
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
              _chatCopy(context).offlineChatSaved,
              style: Theme.of(context)
                  .textTheme
                  .bodySmall
                  ?.copyWith(color: c.textSecondary),
            ),
          ),
          MayosButton(
            key: const Key('chat_offline_retry'),
            label: _chatCopy(context).retry,
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
            child: FirstStrongDirection(
              text: message,
              child: Text(
                message,
                style: Theme.of(context)
                    .textTheme
                    .bodySmall
                    ?.copyWith(color: c.danger),
              ),
            ),
          ),
          if (onRetry != null)
            MayosButton(
              key: const Key('chat_retry'),
              label: _chatCopy(context).retry,
              variant: MayosButtonVariant.tertiary,
              expand: false,
              onPressed: onRetry,
            ),
        ],
      ),
    );
  }
}

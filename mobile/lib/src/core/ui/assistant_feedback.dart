import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../display_language/catalog.dart';
import '../display_language/copy_context.dart';
import '../theme/mayos_spacing.dart';
import '../theme/mayos_theme.dart';
import '../theme/mayos_typography.dart';
import 'mayos_button.dart';
import 'mayos_text_field.dart';

/// The 👍/👎 vote bar and ⋯ menu (Copy / Report) under one assistant reply
/// (#748). Both the player chat and the coach assistant use it; the caller
/// owns the vote state and the network calls.
///
/// A 👎 opens the optional reasons sheet — closing it keeps the 👎, and the
/// reasons can be added later from the same sheet. Reporting opens the same
/// sheet with a reason required; the caller confirms the send.
class AssistantFeedbackBar extends StatefulWidget {
  const AssistantFeedbackBar({
    super.key,
    required this.replyText,
    required this.vote,
    required this.onVote,
    required this.onReport,
  });

  /// The reply's plain text for the ⋯ → Copy action.
  final String replyText;

  /// The currently stored vote: 'up', 'down', or null.
  final String? vote;

  /// Commits a vote; null clears it. [reasons]/[note] carry the 👎 sheet's
  /// optional reason pass.
  final Future<void> Function(
    String? vote, {
    List<String> reasons,
    String? note,
  }) onVote;

  /// Sends a report with at least one reason and an optional note.
  final Future<void> Function(List<String> reasons, String? note) onReport;

  /// The sheet lists Offensive and Unsafe advice first so the harmful-answer
  /// reasons are one tap away (issue #748).
  static const List<String> reasonOrder = <String>[
    'offensive',
    'unsafe_advice',
    'wrong_information',
    'not_helpful',
    'didnt_understand',
  ];

  @override
  State<AssistantFeedbackBar> createState() => _AssistantFeedbackBarState();
}

class _AssistantFeedbackBarState extends State<AssistantFeedbackBar> {
  MayosCopy get _copy => displayCopyOf(context);

  Future<void> _toggleVote(String target) async {
    if (widget.vote == target) {
      await widget.onVote(null);
      return;
    }
    if (target == 'down') {
      // The 👎 commits immediately; the reasons sheet is optional and closing
      // it keeps the vote.
      await widget.onVote('down');
      if (!mounted) return;
      await _openReasonSheet(isReport: false);
      return;
    }
    await widget.onVote(target);
  }

  Future<void> _openReasonSheet({required bool isReport}) async {
    if (!mounted) return;
    await showModalBottomSheet<void>(
      context: context,
      isScrollControlled: true,
      builder: (BuildContext sheetContext) => _ReasonSheet(
        isReport: isReport,
        onSubmit: (Set<String> reasons, String note) async {
          Navigator.of(sheetContext).pop();
          final List<String> ordered = <String>[
            for (final String reason in AssistantFeedbackBar.reasonOrder)
              if (reasons.contains(reason)) reason,
          ];
          final String trimmedNote = note.trim();
          if (isReport) {
            await widget.onReport(ordered, trimmedNote);
          } else {
            await widget.onVote('down', reasons: ordered, note: trimmedNote);
          }
        },
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final MayosThemeExtension c = MayosTheme.of(context);
    final MayosCopy copy = _copy;
    return Row(
      children: <Widget>[
        IconButton(
          key: const Key('assistant_feedback_up'),
          tooltip: copy.assistantFeedbackUp,
          icon: Icon(
            Icons.thumb_up_outlined,
            size: 18,
            color: widget.vote == 'up' ? c.accent : c.textSecondary,
          ),
          constraints: const BoxConstraints(
            minWidth: kMayosMinTapTarget,
            minHeight: kMayosMinTapTarget,
          ),
          onPressed: () => _toggleVote('up'),
        ),
        IconButton(
          key: const Key('assistant_feedback_down'),
          tooltip: copy.assistantFeedbackDown,
          icon: Icon(
            Icons.thumb_down_outlined,
            size: 18,
            color: widget.vote == 'down' ? c.danger : c.textSecondary,
          ),
          constraints: const BoxConstraints(
            minWidth: kMayosMinTapTarget,
            minHeight: kMayosMinTapTarget,
          ),
          onPressed: () => _toggleVote('down'),
        ),
        const SizedBox(width: MayosSpacing.xs),
        PopupMenuButton<String>(
          key: const Key('assistant_feedback_menu'),
          tooltip: copy.assistantFeedbackMenu,
          icon: Icon(Icons.more_vert, size: 18, color: c.textSecondary),
          constraints: const BoxConstraints(
            minWidth: kMayosMinTapTarget,
            minHeight: kMayosMinTapTarget,
          ),
          onSelected: (String action) async {
            if (action == 'copy') {
              await Clipboard.setData(ClipboardData(text: widget.replyText));
              if (mounted) {
                ScaffoldMessenger.of(context).showSnackBar(SnackBar(
                  content: Text(_copy.assistantFeedbackCopied),
                ));
              }
              return;
            }
            if (action == 'report') {
              await _openReasonSheet(isReport: true);
            }
          },
          itemBuilder: (BuildContext menuContext) => <PopupMenuEntry<String>>[
            PopupMenuItem<String>(
              key: const Key('assistant_feedback_copy'),
              value: 'copy',
              child: Text(copy.assistantFeedbackCopy),
            ),
            PopupMenuItem<String>(
              key: const Key('assistant_feedback_report'),
              value: 'report',
              child: Text(copy.assistantFeedbackReport),
            ),
          ],
        ),
      ],
    );
  }
}

/// The reasons sheet: ⋯ → Report requires at least one reason before send;
/// a 👎 reason pass may simply be closed. Submit is disabled until a reason
/// is chosen when reporting.
///
/// The sheet owns its note controller (created in [State.initState], disposed
/// in [State.dispose]) so its lifetime matches the sheet's, including the
/// closing animation, and its content scrolls so it fits at any width or text
/// scale without overflowing.
class _ReasonSheet extends StatefulWidget {
  const _ReasonSheet({
    required this.isReport,
    required this.onSubmit,
  });

  final bool isReport;
  final Future<void> Function(Set<String> reasons, String note) onSubmit;

  @override
  State<_ReasonSheet> createState() => _ReasonSheetState();
}

class _ReasonSheetState extends State<_ReasonSheet> {
  final Set<String> _selected = <String>{};
  late final TextEditingController _note = TextEditingController();
  bool _sending = false;

  @override
  void dispose() {
    _note.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final MayosCopy copy = displayCopyOf(context);
    // Keyboard insets lift the sheet; SafeArea keeps it above the system
    // gesture area; the scroll view absorbs any height shortfall (360dp,
    // 1.5× text) instead of overflowing.
    return Padding(
      padding: EdgeInsets.only(bottom: MediaQuery.viewInsetsOf(context).bottom),
      child: SafeArea(
        child: SingleChildScrollView(
          padding: const EdgeInsets.all(MayosSpacing.md),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: <Widget>[
              Text(
                copy.assistantFeedbackReportTitle,
                style: Theme.of(context).textTheme.titleMedium,
              ),
              const SizedBox(height: MayosSpacing.xs),
              for (final String reason in AssistantFeedbackBar.reasonOrder)
                CheckboxListTile(
                  key: Key('assistant_feedback_reason_$reason'),
                  contentPadding: EdgeInsets.zero,
                  dense: true,
                  value: _selected.contains(reason),
                  title: Text(copy.assistantFeedbackReason(reason)),
                  onChanged: _sending
                      ? null
                      : (bool? checked) => setState(() {
                            if (checked == true) {
                              _selected.add(reason);
                            } else {
                              _selected.remove(reason);
                            }
                          }),
                ),
              const SizedBox(height: MayosSpacing.xs),
              MayosTextField(
                fieldKey: const Key('assistant_feedback_note'),
                controller: _note,
                enabled: !_sending,
                minLines: 1,
                maxLines: 3,
                maxLength: 500,
                hint: copy.assistantFeedbackReportNote,
              ),
              if (widget.isReport && _selected.isEmpty)
                Padding(
                  padding: const EdgeInsets.only(top: MayosSpacing.xs),
                  child: Text(
                    copy.assistantFeedbackReportRequired,
                    style: MayosTypography.of(context)
                        .caption
                        .copyWith(color: MayosTheme.of(context).danger),
                  ),
                ),
              const SizedBox(height: MayosSpacing.sm),
              Row(
                mainAxisAlignment: MainAxisAlignment.end,
                children: <Widget>[
                  if (widget.isReport)
                    MayosButton(
                      key: const Key('assistant_feedback_report_send'),
                      label: copy.assistantFeedbackReportSend,
                      expand: false,
                      onPressed:
                          _selected.isEmpty || _sending ? null : _submit,
                    )
                  else
                    MayosButton(
                      key: const Key('assistant_feedback_reasons_done'),
                      label: copy.gotIt,
                      variant: MayosButtonVariant.tertiary,
                      expand: false,
                      onPressed: _sending ? null : _submit,
                    ),
                ],
              ),
            ],
          ),
        ),
      ),
    );
  }

  Future<void> _submit() async {
    if (_sending) return;
    setState(() => _sending = true);
    await widget.onSubmit(Set<String>.of(_selected), _note.text);
    if (mounted) setState(() => _sending = false);
  }
}

/// The card that replaces a reported reply until "Show anyway" is tapped.
class AssistantReportedCard extends StatelessWidget {
  const AssistantReportedCard({super.key, required this.onShowAnyway});

  final VoidCallback onShowAnyway;

  @override
  Widget build(BuildContext context) {
    final MayosThemeExtension c = MayosTheme.of(context);
    final MayosCopy copy = displayCopyOf(context);
    return Padding(
      padding: const EdgeInsets.only(top: MayosSpacing.xxs),
      child: Container(
        key: const Key('assistant_feedback_reported_card'),
        padding: const EdgeInsets.symmetric(
          horizontal: MayosSpacing.sm,
          vertical: MayosSpacing.xxs,
        ),
        decoration: BoxDecoration(
          color: c.secondarySurface,
          borderRadius: MayosRadii.mediumRadius,
          border: Border.all(color: c.border),
        ),
        child: Row(
          children: <Widget>[
            Icon(Icons.visibility_off_outlined,
                size: 16, color: c.textSecondary),
            const SizedBox(width: MayosSpacing.xs),
            Expanded(
              child: Text(
                copy.assistantFeedbackReported,
                style: MayosTypography.of(context)
                    .caption
                    .copyWith(color: c.textSecondary),
              ),
            ),
            MayosButton(
              key: const Key('assistant_feedback_show_anyway'),
              label: copy.assistantFeedbackShowAnyway,
              variant: MayosButtonVariant.tertiary,
              expand: false,
              onPressed: onShowAnyway,
            ),
          ],
        ),
      ),
    );
  }
}

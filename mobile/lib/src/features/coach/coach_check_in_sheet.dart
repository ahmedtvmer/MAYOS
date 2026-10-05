import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api_client.dart';
import '../../core/app_failure.dart';
import '../../core/connectivity_message.dart';
import '../../core/display_language/copy_context.dart';
import '../../core/display_language/feature_copy_context.dart';
import '../../core/models.dart';
import '../../core/theme/mayos_spacing.dart';
import '../../core/theme/mayos_theme.dart';
import '../../core/theme/mayos_typography.dart';
import '../../core/ui/mayos_button.dart';
import '../../providers.dart';

/// The four channels the log-check-in sheet offers (#120): a call, a message,
/// an in-person meeting, and other. Values come from [CheckIn.channels] — the
/// service names a call `phone` — and their labels from [CheckIn.labelFor],
/// so the sheet never restates the vocabulary.
const List<String> kLogCheckInChannels = <String>[
  'phone',
  'message',
  'in_person',
  'other',
];

/// Opens the header's **Log check-in** sheet (#120): pick a channel, add an
/// optional note, save. The check-in is dated today and goes through the
/// existing `POST /coach/assignments/{id}/check-ins` call; [onSaved] receives
/// the creation so the caller can refresh its page and the roster row.
Future<void> showLogCheckInSheet(
  BuildContext context, {
  required String assignmentId,
  required String playerUsername,
  required ValueChanged<CheckInCreation> onSaved,
}) {
  return showModalBottomSheet<void>(
    context: context,
    isScrollControlled: true,
    showDragHandle: true,
    builder: (BuildContext context) => LogCheckInSheet(
      assignmentId: assignmentId,
      playerUsername: playerUsername,
      onSaved: onSaved,
    ),
  );
}

/// The sheet body. A channel is required (the service rejects a check-in
/// without one), the note is optional, and the date is always today.
class LogCheckInSheet extends ConsumerStatefulWidget {
  const LogCheckInSheet({
    super.key,
    required this.assignmentId,
    required this.playerUsername,
    required this.onSaved,
  });

  final String assignmentId;
  final String playerUsername;
  final ValueChanged<CheckInCreation> onSaved;

  @override
  ConsumerState<LogCheckInSheet> createState() => _LogCheckInSheetState();
}

class _LogCheckInSheetState extends ConsumerState<LogCheckInSheet> {
  final TextEditingController _note = TextEditingController();
  String? _channel;
  bool _saving = false;
  String? _error;
  FailureMessage? _failure;

  @override
  void dispose() {
    _note.dispose();
    super.dispose();
  }

  Future<void> _save() async {
    final String? channel = _channel;
    if (channel == null) {
      setState(() => _error = coachCopyOf(context).pickContactChannel);
      return;
    }
    // The note is optional: a blank one is sent as null, not an empty string.
    final String note = _note.text.trim();
    setState(() {
      _saving = true;
      _error = null;
      _failure = null;
    });
    try {
      final CheckInCreation created =
          await ref.read(apiClientProvider).createCoachCheckIn(
                widget.assignmentId,
                checkedInOn: isoDateOf(DateTime.now()),
                channel: channel,
                note: note.isEmpty ? null : note,
              );
      if (!mounted) return;
      widget.onSaved(created);
      Navigator.of(context).pop();
    } on ApiException catch (error) {
      if (!mounted) return;
      setState(() {
        _saving = false;
        _failure = apiFailureMessage(error);
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    final MayosThemeExtension c = MayosTheme.of(context);
    final copy = coachCopyOf(context);
    final String today = isoDateOf(DateTime.now());
    return Padding(
      padding: EdgeInsetsDirectional.fromSTEB(
        MayosSpacing.lg,
        0,
        MayosSpacing.lg,
        MayosSpacing.lg + MediaQuery.viewInsetsOf(context).bottom,
      ),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: <Widget>[
          Text(
            copy.checkInWithPlayer(widget.playerUsername),
            style:
                MayosTypography.of(context).sectionHeading.copyWith(color: c.textPrimary),
          ),
          const SizedBox(height: MayosSpacing.xxs),
          Text(
            copy.datedToday(today),
            style: MayosTypography.of(context).caption.copyWith(color: c.textSecondary),
          ),
          const SizedBox(height: MayosSpacing.md),
          Wrap(
            spacing: MayosSpacing.sm,
            runSpacing: MayosSpacing.xs,
            children: <Widget>[
              for (final String channel in kLogCheckInChannels)
                ChoiceChip(
                  key: Key('check_in_channel_$channel'),
                  label: Text(copy.checkInChannel(channel)),
                  selected: _channel == channel,
                  onSelected: (bool selected) => setState(() {
                    _channel = selected ? channel : null;
                  }),
                ),
            ],
          ),
          const SizedBox(height: MayosSpacing.md),
          TextField(
            key: const Key('check_in_note_field'),
            controller: _note,
            maxLines: 2,
            decoration: InputDecoration(
              labelText: copy.noteOptional,
              border: const OutlineInputBorder(),
            ),
          ),
          if (_error != null) ...<Widget>[
            const SizedBox(height: MayosSpacing.sm),
            Text(
              _error!,
              style: MayosTypography.of(context).bodySecondary.copyWith(color: c.danger),
            ),
          ],
          if (_failure != null) ...<Widget>[
            const SizedBox(height: MayosSpacing.sm),
            Text(
              displayCopyOf(context).failureMessage(_failure!),
              style: MayosTypography.of(context).bodySecondary.copyWith(color: c.danger),
            ),
          ],
          const SizedBox(height: MayosSpacing.md),
          MayosButton(
            key: const Key('check_in_submit_button'),
            label: copy.saveCheckIn,
            loading: _saving,
            onPressed: _saving ? null : _save,
          ),
        ],
      ),
    );
  }
}

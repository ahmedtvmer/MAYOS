import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api_client.dart';
import '../../core/models.dart';
import '../../core/theme/mayos_spacing.dart';
import '../../core/theme/mayos_theme.dart';
import '../../core/theme/mayos_typography.dart';
import '../../core/ui/mayos_button.dart';
import '../../providers.dart';

/// The channels the log-check-in sheet offers, in display order: the four
/// contact methods a coach actually uses (#120). `call` maps onto the wire's
/// `phone`, the only value the service recognises for a call.
const Map<String, String> kCheckInSheetChannels = <String, String>{
  'phone': 'Call',
  'message': 'Message',
  'in_person': 'In person',
  'other': 'Other',
};

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

  @override
  void dispose() {
    _note.dispose();
    super.dispose();
  }

  Future<void> _save() async {
    final String? channel = _channel;
    if (channel == null) {
      setState(() => _error = 'Pick a contact channel.');
      return;
    }
    setState(() {
      _saving = true;
      _error = null;
    });
    try {
      final CheckInCreation created =
          await ref.read(apiClientProvider).createCoachCheckIn(
                widget.assignmentId,
                checkedInOn: isoDateOf(DateTime.now()),
                channel: channel,
                note: _note.text,
              );
      if (!mounted) return;
      widget.onSaved(created);
      Navigator.of(context).pop();
    } on ApiException catch (error) {
      if (!mounted) return;
      setState(() {
        _saving = false;
        _error = error.message;
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    final MayosThemeExtension c = MayosTheme.of(context);
    final String today = isoDateOf(DateTime.now());
    return Padding(
      padding: EdgeInsets.fromLTRB(
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
            'Log check-in with ${widget.playerUsername}',
            style: MayosTypography.sectionHeading.copyWith(color: c.textPrimary),
          ),
          const SizedBox(height: MayosSpacing.xxs),
          Text(
            'Dated today · $today',
            style: MayosTypography.caption.copyWith(color: c.textSecondary),
          ),
          const SizedBox(height: MayosSpacing.md),
          Wrap(
            spacing: MayosSpacing.sm,
            runSpacing: MayosSpacing.xs,
            children: <Widget>[
              for (final MapEntry<String, String> option
                  in kCheckInSheetChannels.entries)
                ChoiceChip(
                  key: Key('check_in_channel_${option.key}'),
                  label: Text(option.value),
                  selected: _channel == option.key,
                  onSelected: (bool selected) => setState(() {
                    _channel = selected ? option.key : null;
                  }),
                ),
            ],
          ),
          const SizedBox(height: MayosSpacing.md),
          TextField(
            key: const Key('check_in_note_field'),
            controller: _note,
            maxLines: 2,
            decoration: const InputDecoration(
              labelText: 'Note (optional)',
              border: OutlineInputBorder(),
            ),
          ),
          if (_error != null) ...<Widget>[
            const SizedBox(height: MayosSpacing.sm),
            Text(
              _error!,
              style: MayosTypography.bodySecondary.copyWith(color: c.danger),
            ),
          ],
          const SizedBox(height: MayosSpacing.md),
          MayosButton(
            key: const Key('check_in_submit_button'),
            label: 'Save check-in',
            loading: _saving,
            onPressed: _saving ? null : _save,
          ),
        ],
      ),
    );
  }
}

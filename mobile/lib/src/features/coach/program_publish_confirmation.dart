import 'package:flutter/material.dart';

import '../../core/display_language/coach_copy.dart';
import '../../core/display_language/feature_copy_context.dart';
import '../../core/models.dart';

class ProgramPublishConfirmation {
  const ProgramPublishConfirmation({
    required this.title,
    required this.prompt,
    required this.confirmLabel,
    required this.cancelLabel,
    required this.requests,
    this.confirmKey = 'program_publish_confirm',
  });

  final String title;
  final String prompt;
  final String confirmLabel;
  final String cancelLabel;
  final String confirmKey;
  final List<ProgramRequest> requests;
}

Future<List<String>?> showProgramPublishConfirmation(
  BuildContext context,
  ProgramPublishConfirmation confirmation,
) =>
    showDialog<List<String>>(
      context: context,
      builder: (BuildContext context) =>
          _ProgramPublishConfirmationDialog(confirmation: confirmation),
    );

class _ProgramPublishConfirmationDialog extends StatefulWidget {
  const _ProgramPublishConfirmationDialog({required this.confirmation});

  final ProgramPublishConfirmation confirmation;

  @override
  State<_ProgramPublishConfirmationDialog> createState() =>
      _ProgramPublishConfirmationDialogState();
}

class _ProgramPublishConfirmationDialogState
    extends State<_ProgramPublishConfirmationDialog> {
  late final Set<String> _selectedRequestIds = <String>{
    for (final ProgramRequest request in widget.confirmation.requests)
      request.requestId,
  };

  Widget _requestTile(CoachCopy copy, ProgramRequest request) =>
      CheckboxListTile(
        key: Key('publish_resolve_${request.requestId}'),
        contentPadding: EdgeInsets.zero,
        controlAffinity: ListTileControlAffinity.leading,
        value: _selectedRequestIds.contains(request.requestId),
        title: Text(
          '${copy.publishRequestResolveLabel} · '
          '${copy.publishRequestKind(request.kind)}',
        ),
        subtitle: Text(
          copy.publishRequestDetails(
            request.exerciseName ?? request.exerciseId,
            request.createdAt.split('T').first,
          ),
        ),
        onChanged: (bool? selected) => setState(() {
          if (selected == true) {
            _selectedRequestIds.add(request.requestId);
          } else {
            _selectedRequestIds.remove(request.requestId);
          }
        }),
      );

  Widget _content(CoachCopy copy) {
    final List<ProgramRequest> requests = widget.confirmation.requests;
    return SingleChildScrollView(
      child: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          Text(widget.confirmation.prompt),
          if (requests.isNotEmpty) ...<Widget>[
            const SizedBox(height: 12),
            Text(copy.publishRequestsWillBeAddressed),
            for (final ProgramRequest request in requests)
              _requestTile(copy, request),
          ],
        ],
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final ProgramPublishConfirmation confirmation = widget.confirmation;
    final copy = coachCopyOf(context);
    return AlertDialog(
      title: Text(confirmation.title),
      content: _content(copy),
      actions: <Widget>[
        TextButton(
          onPressed: () => Navigator.of(context).pop(),
          child: Text(confirmation.cancelLabel),
        ),
        TextButton(
          key: Key(confirmation.confirmKey),
          onPressed: () => Navigator.of(context).pop(_selectedRequestIds.toList()),
          child: Text(confirmation.confirmLabel),
        ),
      ],
    );
  }
}

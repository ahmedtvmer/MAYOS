import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api_client.dart';
import '../../core/app_failure.dart';
import '../../core/connectivity_message.dart';
import '../../core/display_language/coach_copy.dart';
import '../../core/display_language/copy_context.dart';
import '../../core/display_language/feature_copy_context.dart';
import '../../core/models.dart';
import '../../core/theme/mayos_spacing.dart';
import '../../core/theme/mayos_theme.dart';
import '../../core/theme/mayos_typography.dart';
import '../../core/ui/mayos_button.dart';
import '../../core/ui/mayos_card.dart';
import 'coach_program_draft_screen.dart';
import '../../providers.dart';

/// Bulk-assigns a Program template to several players and optionally publishes
/// every copy (ticket #306). Each selected player receives an independent copy
/// with its own replace/keep decision; results are reported per player.
class CoachTemplateAssignmentScreen extends ConsumerStatefulWidget {
  const CoachTemplateAssignmentScreen({
    super.key,
    required this.templateId,
    required this.templateName,
  });

  final String templateId;
  final String templateName;

  @override
  ConsumerState<CoachTemplateAssignmentScreen> createState() =>
      _CoachTemplateAssignmentScreenState();
}

class _CoachTemplateAssignmentScreenState
    extends ConsumerState<CoachTemplateAssignmentScreen> {
  bool _loading = true;
  bool _assigning = false;
  bool _publishing = false;
  FailureMessage? _failure;
  List<CoachRosterEntry> _players = <CoachRosterEntry>[];
  final Set<String> _selected = <String>{};
  final Map<String, String> _decision = <String, String>{};
  List<String> _assignedIds = <String>[];
  List<Map<String, dynamic>> _assignmentResults = <Map<String, dynamic>>[];
  List<Map<String, dynamic>> _publishResults = <Map<String, dynamic>>[];

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    setState(() {
      _loading = true;
      _failure = null;
    });
    try {
      final List<CoachRosterEntry> players =
          await ref.read(apiClientProvider).coachAssignments();
      if (!mounted) return;
      setState(() {
        _players = players;
        _loading = false;
      });
    } on ApiException catch (error) {
      if (!mounted) return;
      setState(() {
        _loading = false;
        _failure = apiFailureMessage(error);
      });
    }
  }

  String _decisionFor(String assignmentId) =>
      _decision[assignmentId] ?? 'skip';

  Future<void> _assign() async {
    final List<String> targets = _selected.toList(growable: false);
    if (targets.isEmpty) return;
    setState(() {
      _assigning = true;
      _failure = null;
    });
    try {
      final List<Map<String, dynamic>> results = await ref
          .read(apiClientProvider)
          .coachAssignProgramTemplate(
            widget.templateId,
            targets: <Map<String, dynamic>>[
              for (final String assignmentId in targets)
                <String, dynamic>{
                  'assignment_id': assignmentId,
                  'existing_draft': _decisionFor(assignmentId),
                },
            ],
          );
      if (!mounted) return;
      int assigned = 0, replaced = 0, skipped = 0, rejected = 0;
      for (final Map<String, dynamic> result in results) {
        switch (result['status']) {
          case 'assigned':
            assigned += 1;
          case 'replaced':
            replaced += 1;
          case 'skipped':
            skipped += 1;
          default:
            rejected += 1;
        }
      }
      setState(() {
        _assignmentResults = results;
        _publishResults = <Map<String, dynamic>>[];
        _assignedIds = <String>[
          for (final Map<String, dynamic> result in results)
            if (result['status'] == 'assigned' ||
                result['status'] == 'replaced')
              result['assignment_id'] as String,
        ];
      });
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text(
            coachCopyOf(context)
                .templateAssignSummary(assigned, replaced, skipped, rejected),
          ),
        ),
      );
    } on ApiException catch (error) {
      if (mounted) setState(() => _failure = apiFailureMessage(error));
    } finally {
      if (mounted) setState(() => _assigning = false);
    }
  }

  Future<void> _publishAll() async {
    if (_assignedIds.isEmpty) return;
    final CoachCopy copy = coachCopyOf(context);
    final bool? confirmed = await showDialog<bool>(
      context: context,
      builder: (BuildContext context) => AlertDialog(
        content: Text(copy.confirmPublishAll),
        actions: <Widget>[
          TextButton(
            onPressed: () => Navigator.of(context).pop(false),
            child: Text(copy.cancel),
          ),
          TextButton(
            key: const Key('template_publish_all_confirm'),
            onPressed: () => Navigator.of(context).pop(true),
            child: Text(copy.publishAll),
          ),
        ],
      ),
    );
    if (confirmed != true || !mounted) return;
    setState(() {
      _publishing = true;
      _failure = null;
    });
    try {
      final List<Map<String, dynamic>> results = await ref
          .read(apiClientProvider)
          .coachPublishAllProgramTemplate(
            widget.templateId,
            assignmentIds: _assignedIds,
          );
      if (!mounted) return;
      int published = 0, invalid = 0, noDraft = 0, rejected = 0;
      for (final Map<String, dynamic> result in results) {
        switch (result['status']) {
          case 'published':
            published += 1;
          case 'invalid':
            invalid += 1;
          case 'no_draft':
            noDraft += 1;
          default:
            rejected += 1;
        }
      }
      setState(() {
        _publishResults = results;
        _assignedIds = <String>[
          for (final Map<String, dynamic> result in results)
            if (result['status'] != 'published')
              result['assignment_id'] as String,
        ];
      });
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text(
            copy.publishAllSummary(published, invalid, noDraft, rejected),
          ),
        ),
      );
    } on ApiException catch (error) {
      if (mounted) setState(() => _failure = apiFailureMessage(error));
    } finally {
      if (mounted) setState(() => _publishing = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final CoachCopy copy = coachCopyOf(context);
    return Scaffold(
      key: const Key('template_assignment_screen'),
      appBar: AppBar(
        leading: BackButton(onPressed: () => Navigator.of(context).pop()),
        title: Text(copy.assignTemplateTitle(widget.templateName)),
      ),
      body: _loading
          ? const Center(child: CircularProgressIndicator())
          : Center(
              child: ConstrainedBox(
                constraints: const BoxConstraints(maxWidth: 720),
                child: ListView(
                  padding: MayosSpacing.screen,
                  children: <Widget>[
                    Text(
                      copy.assignTemplateLead,
                      style: MayosTypography.of(context).bodySecondary,
                    ),
                    if (_failure != null) ...<Widget>[
                      const SizedBox(height: MayosSpacing.md),
                      Text(
                        displayCopyOf(context).failureMessage(_failure!),
                        style: MayosTypography.of(context)
                            .body
                            .copyWith(color: MayosTheme.of(context).danger),
                      ),
                    ],
                    const SizedBox(height: MayosSpacing.md),
                    if (_players.isEmpty)
                      Text(copy.noPlayersToAssign)
                    else
                      for (final CoachRosterEntry player in _players)
                        _playerCard(player, copy),
                    if (_assignmentResults.isNotEmpty) ...<Widget>[
                      const SizedBox(height: MayosSpacing.md),
                      Text(copy.templateAssignmentResults,
                          style: MayosTypography.of(context).sectionHeading),
                      for (final Map<String, dynamic> result
                          in _assignmentResults)
                        _resultCard(result, copy, publish: false),
                    ],
                    if (_publishResults.isNotEmpty) ...<Widget>[
                      const SizedBox(height: MayosSpacing.md),
                      Text(copy.templatePublishResults,
                          style: MayosTypography.of(context).sectionHeading),
                      for (final Map<String, dynamic> result in _publishResults)
                        _resultCard(result, copy, publish: true),
                    ],
                    const SizedBox(height: MayosSpacing.md),
                    MayosButton(
                      key: const Key('template_assign_submit'),
                      label: copy.assignSelectedPlayers,
                      icon: Icons.playlist_add_check,
                      loading: _assigning,
                      onPressed: _selected.isEmpty || _assigning || _publishing
                          ? null
                          : _assign,
                    ),
                    const SizedBox(height: MayosSpacing.sm),
                    MayosButton(
                      key: const Key('template_publish_all'),
                      label: copy.publishAll,
                      variant: MayosButtonVariant.secondary,
                      icon: Icons.publish,
                      loading: _publishing,
                      onPressed: _assignedIds.isEmpty || _publishing || _assigning
                          ? null
                          : _publishAll,
                    ),
                  ],
                ),
              ),
            ),
    );
  }

  Widget _playerCard(CoachRosterEntry player, CoachCopy copy) {
    final String id = player.assignmentId;
    final bool selected = _selected.contains(id);
    return Padding(
      padding: const EdgeInsets.only(bottom: MayosSpacing.sm),
      child: MayosCard(
        key: Key('template_assign_player_$id'),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: <Widget>[
            CheckboxListTile(
              contentPadding: EdgeInsets.zero,
              value: selected,
              title: Text(
                player.playerUsername,
                style: MayosTypography.of(context).sectionHeading,
              ),
              onChanged: _assigning || _publishing
                  ? null
                  : (bool? value) => setState(() {
                if (value ?? false) {
                  _selected.add(id);
                } else {
                  _selected.remove(id);
                }
              }),
            ),
            if (selected)
              SegmentedButton<String>(
                segments: <ButtonSegment<String>>[
                  ButtonSegment<String>(
                    value: 'replace',
                    label: Text(copy.existingDraftReplace),
                  ),
                  ButtonSegment<String>(
                    value: 'skip',
                    label: Text(copy.existingDraftKeep),
                  ),
                ],
                selected: <String>{_decisionFor(id)},
                onSelectionChanged: _assigning || _publishing
                    ? null
                    : (Set<String> selection) => setState(
                  () => _decision[id] = selection.first,
                ),
              ),
          ],
        ),
      ),
    );
  }

  Widget _resultCard(Map<String, dynamic> result, CoachCopy copy,
      {required bool publish}) {
    final String id = result['assignment_id'] as String? ?? '';
    String playerName = copy.unknownPlayer;
    for (final CoachRosterEntry player in _players) {
      if (player.assignmentId == id) {
        playerName = player.playerUsername;
        break;
      }
    }
    final String status = result['status'] as String? ?? 'rejected';
    final List<dynamic> errors = result['errors'] as List<dynamic>? ??
        const <dynamic>[];
    final int resolved = result['resolved_request_count'] as int? ?? 0;
    final bool canCustomize = status == 'invalid' ||
        result['message_code'] == 'assignment.program_draft_changed.v1';
    final List<Widget> details = <Widget>[
      Text(copy.templatePlayerResult(playerName, status)),
      if (status == 'rejected' || status == 'invalid' || status == 'no_draft')
        Text(_resultMessage(result, errors, copy)),
      if (publish && status == 'published')
        Text(copy.resolvedProgramRequests(resolved)),
      if (canCustomize)
        Align(
          alignment: AlignmentDirectional.centerStart,
          child: TextButton.icon(
            key: Key('template_assignment_customize_$id'),
            onPressed: _assigning || _publishing
                ? null
                : () => Navigator.of(context).push<void>(
                      MaterialPageRoute<void>(
                        builder: (BuildContext context) =>
                            CoachProgramDraftScreen(
                          assignmentId: id,
                          playerUsername: playerName,
                        ),
                      ),
                    ),
            icon: const Icon(Icons.edit_outlined),
            label: Text(copy.customizeDraft),
          ),
        ),
    ];
    return Padding(
      padding: const EdgeInsets.only(bottom: MayosSpacing.xs),
      child: MayosCard(child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: details,
      )),
    );
  }

  String _resultMessage(
      Map<String, dynamic> result, List<dynamic> errors, CoachCopy copy) {
    if (errors.isNotEmpty) {
      return errors.map((dynamic error) {
        final Map<String, dynamic> issue = error as Map<String, dynamic>;
        return copy.programDraftValidationMessage(
            issue['code'] as String? ?? '');
      }).join('\n');
    }
    return copy.templateResultMessage(
      result['message_code'] as String? ?? '',
      result['message_fallback'] as String? ?? '',
    );
  }
}

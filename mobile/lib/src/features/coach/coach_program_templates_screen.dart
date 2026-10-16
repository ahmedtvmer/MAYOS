import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api_client.dart';
import '../../core/app_failure.dart';
import '../../core/connectivity_message.dart';
import '../../core/display_language/coach_copy.dart';
import '../../core/display_language/copy_context.dart';
import '../../core/display_language/feature_copy_context.dart';
import '../../core/theme/mayos_spacing.dart';
import '../../core/theme/mayos_theme.dart';
import '../../core/theme/mayos_typography.dart';
import '../../core/ui/mayos_button.dart';
import '../../core/ui/mayos_card.dart';
import '../../providers.dart';
import 'coach_program_draft_screen.dart';
import 'coach_template_assignment_screen.dart';

/// The Coach-owned Program template library (ticket #305): lists reusable
/// Training program templates and opens them in the editor's template mode,
/// where Save replaces Publish.
class CoachProgramTemplatesScreen extends ConsumerStatefulWidget {
  const CoachProgramTemplatesScreen({super.key});

  @override
  ConsumerState<CoachProgramTemplatesScreen> createState() =>
      _CoachProgramTemplatesScreenState();
}

class _CoachProgramTemplatesScreenState
    extends ConsumerState<CoachProgramTemplatesScreen> {
  bool _loading = true;
  bool _showArchived = false;
  String? _busyTemplateId;
  FailureMessage? _failure;
  List<Map<String, dynamic>> _templates = <Map<String, dynamic>>[];
  List<Map<String, dynamic>> _archived = <Map<String, dynamic>>[];

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
      final ApiClient api = ref.read(apiClientProvider);
      final List<Map<String, dynamic>> active =
          await api.coachListProgramTemplates();
      final List<Map<String, dynamic>> archived =
          await api.coachListProgramTemplates(archived: true);
      if (!mounted) return;
      setState(() {
        _templates = active;
        _archived = archived;
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

  Future<void> _openTemplate(Map<String, dynamic> template) async {
    await Navigator.of(context).push<void>(
      MaterialPageRoute<void>(
        builder: (BuildContext context) => CoachProgramDraftScreen.template(
          templateId: template['template_id'] as String,
          templateName: template['name'] as String,
          templateDescription: template['description'] as String?,
        ),
      ),
    );
    if (mounted) await _load();
  }

  Future<void> _createTemplate() async {
    await Navigator.of(context).push<void>(
      MaterialPageRoute<void>(
        builder: (BuildContext context) =>
            const CoachProgramDraftScreen.newTemplate(),
      ),
    );
    if (mounted) await _load();
  }

  Future<void> _assignTemplate(Map<String, dynamic> template) async {
    await Navigator.of(context).push<void>(
      MaterialPageRoute<void>(
        builder: (BuildContext context) => CoachTemplateAssignmentScreen(
          templateId: template['template_id'] as String,
          templateName: template['name'] as String? ?? '',
        ),
      ),
    );
    if (mounted) await _load();
  }

  Future<void> _duplicateTemplate(Map<String, dynamic> template) async {
    final String id = template['template_id'] as String;
    setState(() {
      _busyTemplateId = id;
      _failure = null;
    });
    bool succeeded = false;
    try {
      final Map<String, dynamic> created = await ref
          .read(apiClientProvider)
          .coachDuplicateProgramTemplate(id);
      if (!mounted) return;
      succeeded = true;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text(
            coachCopyOf(context)
                .templateDuplicated(created['name'] as String? ?? ''),
          ),
        ),
      );
    } on ApiException catch (error) {
      if (mounted) setState(() => _failure = apiFailureMessage(error));
    } finally {
      if (mounted) {
        setState(() => _busyTemplateId = null);
        if (succeeded) await _load();
      }
    }
  }

  Future<void> _setArchived(
    Map<String, dynamic> template,
    bool archived,
  ) async {
    final String id = template['template_id'] as String;
    setState(() {
      _busyTemplateId = id;
      _failure = null;
    });
    final ApiClient api = ref.read(apiClientProvider);
    bool succeeded = false;
    try {
      final CoachCopy copy = coachCopyOf(context);
      if (archived) {
        await api.coachArchiveProgramTemplate(id);
      } else {
        await api.coachUnarchiveProgramTemplate(id);
      }
      if (!mounted) return;
      succeeded = true;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text(archived ? copy.templateArchived : copy.templateUnarchived),
        ),
      );
    } on ApiException catch (error) {
      if (mounted) setState(() => _failure = apiFailureMessage(error));
    } finally {
      if (mounted) {
        setState(() => _busyTemplateId = null);
        if (succeeded) await _load();
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final CoachCopy copy = coachCopyOf(context);
    return Scaffold(
      key: const Key('program_templates_screen'),
      appBar: AppBar(
        leading: BackButton(onPressed: () => Navigator.of(context).pop()),
        title: Text(copy.programTemplates),
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
                      copy.programTemplatesLead,
                      style: MayosTypography.of(context).bodySecondary,
                    ),
                    const SizedBox(height: MayosSpacing.md),
                    MayosButton(
                      key: const Key('program_templates_new'),
                      label: copy.newProgramTemplate,
                      icon: Icons.add,
                      onPressed: _createTemplate,
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
                    if (_templates.isEmpty)
                      Text(copy.noProgramTemplates)
                    else
                      for (final Map<String, dynamic> template in _templates)
                        _templateCard(template, archived: false),
                    const SizedBox(height: MayosSpacing.sm),
                    TextButton(
                      key: const Key('program_templates_show_archived'),
                      onPressed: () =>
                          setState(() => _showArchived = !_showArchived),
                      child: Text(
                        _showArchived
                            ? copy.hideArchivedTemplates
                            : copy.showArchivedTemplates,
                      ),
                    ),
                    if (_showArchived) ...<Widget>[
                      Text(
                        copy.archivedTemplates,
                        style: MayosTypography.of(context).sectionHeading,
                      ),
                      const SizedBox(height: MayosSpacing.sm),
                      if (_archived.isEmpty)
                        Text(copy.noProgramTemplates)
                      else
                        for (final Map<String, dynamic> template in _archived)
                          _templateCard(template, archived: true),
                    ],
                  ],
                ),
              ),
            ),
    );
  }

  Widget _templateCard(
    Map<String, dynamic> template, {
    required bool archived,
  }) {
    final CoachCopy copy = coachCopyOf(context);
    final String id = template['template_id'] as String;
    final String name = template['name'] as String? ?? '';
    final String? description = template['description'] as String?;
    final bool busy = _busyTemplateId == id;
    return Padding(
      padding: const EdgeInsets.only(bottom: MayosSpacing.sm),
      child: MayosCard(
        key: Key('program_template_row_$id'),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: <Widget>[
            Text(name, style: MayosTypography.of(context).sectionHeading),
            if (description != null && description.isNotEmpty) ...<Widget>[
              const SizedBox(height: MayosSpacing.xs),
              Text(
                description,
                style: MayosTypography.of(context).bodySecondary,
              ),
            ],
            const SizedBox(height: MayosSpacing.sm),
            Wrap(
              spacing: MayosSpacing.xs,
              children: <Widget>[
                if (!archived) ...<Widget>[
                  MayosButton(
                    key: Key('program_template_edit_$id'),
                    label: copy.editProgramTemplate,
                    variant: MayosButtonVariant.secondary,
                    expand: false,
                    onPressed: busy ? null : () => _openTemplate(template),
                  ),
                  MayosButton(
                    key: Key('program_template_duplicate_$id'),
                    label: copy.duplicateTemplate,
                    variant: MayosButtonVariant.secondary,
                    expand: false,
                    loading: busy,
                    onPressed: busy ? null : () => _duplicateTemplate(template),
                  ),
                  MayosButton(
                    key: Key('program_template_assign_$id'),
                    label: copy.assignTemplate,
                    variant: MayosButtonVariant.secondary,
                    expand: false,
                    onPressed: busy ? null : () => _assignTemplate(template),
                  ),
                  MayosButton(
                    key: Key('program_template_archive_$id'),
                    label: copy.archiveTemplate,
                    variant: MayosButtonVariant.tertiary,
                    expand: false,
                    onPressed: busy ? null : () => _setArchived(template, true),
                  ),
                ] else
                  MayosButton(
                    key: Key('program_template_unarchive_$id'),
                    label: copy.unarchiveTemplate,
                    variant: MayosButtonVariant.secondary,
                    expand: false,
                    loading: busy,
                    onPressed: busy ? null : () => _setArchived(template, false),
                  ),
              ],
            ),
          ],
        ),
      ),
    );
  }
}

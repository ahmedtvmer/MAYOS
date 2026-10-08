import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api_client.dart';
import '../../core/display_language/coach_copy.dart';
import '../../core/display_language/copy_context.dart';
import '../../core/display_language/feature_copy_context.dart';
import '../../core/models.dart';
import '../../core/connectivity_message.dart';
import '../../core/theme/mayos_spacing.dart';
import '../../core/ui/mayos_button.dart';
import '../../providers.dart';
import 'coach_program_draft_screen.dart';
import 'program_import_files.dart';

class CoachProgramImportScreen extends ConsumerStatefulWidget {
  const CoachProgramImportScreen({
    super.key,
    required this.assignmentId,
    required this.playerUsername,
  });

  final String assignmentId;
  final String playerUsername;

  @override
  ConsumerState<CoachProgramImportScreen> createState() =>
      _CoachProgramImportScreenState();
}

class _CoachProgramImportScreenState
    extends ConsumerState<CoachProgramImportScreen> {
  PlatformFile? _file;
  Map<String, dynamic>? _result;
  List<Map<String, dynamic>> _rows = <Map<String, dynamic>>[];
  String? _selectedTab;
  String? _error;
  bool _busy = false;

  @override
  Widget build(BuildContext context) {
    final CoachCopy copy = coachCopyOf(context);
    return Scaffold(
      appBar: AppBar(title: Text(copy.importFromSpreadsheet)),
      body: SafeArea(
        child: ListView(
          padding: const EdgeInsets.all(MayosSpacing.md),
          children: <Widget>[
            Text(copy.importPrivacyNote),
            const SizedBox(height: MayosSpacing.md),
            MayosButton(
              key: const Key('program_import_pick_file'),
              label: _file?.name ?? copy.chooseSpreadsheet,
              icon: Icons.upload_file,
              variant: MayosButtonVariant.secondary,
              loading: _busy && _result == null,
              onPressed: _busy ? null : _pickFile,
            ),
            if (_result?['requires_tab_choice'] == true) ...<Widget>[
              const SizedBox(height: MayosSpacing.md),
              DropdownButtonFormField<String>(
                key: const Key('program_import_tab_picker'),
                initialValue: _selectedTab,
                decoration: InputDecoration(labelText: copy.chooseSheet),
                items: <DropdownMenuItem<String>>[
                  for (final dynamic tab
                      in _result!['detected_tabs'] as List<dynamic>)
                    DropdownMenuItem<String>(
                      value: tab as String,
                      child: Text(tab),
                    ),
                ],
                onChanged: (String? value) =>
                    setState(() => _selectedTab = value),
              ),
              const SizedBox(height: MayosSpacing.sm),
              MayosButton(
                key: const Key('program_import_read_sheet'),
                label: copy.reviewImport,
                loading: _busy,
                onPressed: _busy || _selectedTab == null
                    ? null
                    : () => _readSelectedFile(sheet: _selectedTab),
              ),
            ],
            if (_result != null) ...<Widget>[
              const SizedBox(height: MayosSpacing.md),
              if ((_result!['weeks_not_imported'] as List<dynamic>? ??
                      const <dynamic>[])
                  .isNotEmpty)
                Text(copy.importedWeeksNote),
              Text(copy.importRowsSummary(_rows.length,
                  _confirmedRows.length)),
              if (_confirmedRows.isEmpty) ...<Widget>[
                const SizedBox(height: MayosSpacing.xs),
                Text(copy.importNoValidRows),
              ],
              const SizedBox(height: MayosSpacing.sm),
              for (final Map<String, dynamic> row in _rows)
                _importRow(context, row),
              const SizedBox(height: MayosSpacing.md),
              MayosButton(
                key: const Key('program_import_create_draft'),
                label: copy.createImportedDraft,
                icon: Icons.edit_note,
                loading: _busy,
                onPressed: _busy || _confirmedRows.isEmpty ? null : _createDraft,
              ),
            ],
            if (_error != null) ...<Widget>[
              const SizedBox(height: MayosSpacing.sm),
              Text(_error!, style: TextStyle(color: Theme.of(context).colorScheme.error)),
            ],
          ],
        ),
      ),
    );
  }

  List<Map<String, dynamic>> get _confirmedRows => _rows
      .where((Map<String, dynamic> row) =>
          row['valid'] == true && row['exercise_id'] is String)
      .map((Map<String, dynamic> row) => <String, dynamic>{
            'source_row': row['source_row'],
            'day': row['day'],
            'day_name': row['day_name'],
            'order': row['order'],
            'exercise_name': row['exercise_name'],
            'exercise_id': row['exercise_id'],
            'sets': row['sets'],
            'reps_min': row['reps_min'],
            'reps_max': row['reps_max'],
            'target_rir': row['target_rir'],
            'rest_seconds': row['rest_seconds'],
            'tempo': row['tempo'],
            'notes': row['notes'],
          })
      .toList(growable: false);

  Widget _importRow(BuildContext context, Map<String, dynamic> row) {
    final CoachCopy copy = coachCopyOf(context);
    final List<dynamic> errors = row['errors'] as List<dynamic>? ?? <dynamic>[];
    final List<dynamic> warnings =
        row['warnings'] as List<dynamic>? ?? <dynamic>[];
    final List<dynamic> suggestions =
        row['suggestions'] as List<dynamic>? ?? <dynamic>[];
    final String name = row['exercise_name'] as String? ?? '';
    final String? selectedId = row['exercise_id'] as String?;
    return Card(
      key: Key('program_import_row_${row['source_row']}'),
      child: Padding(
        padding: const EdgeInsets.all(MayosSpacing.sm),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: <Widget>[
            Text('${copy.rowLabel(row['source_row'] as int)} · $name'),
            Text(copy.importPrescription(
              row['day_name'] as String? ?? '',
              row['sets'] as int? ?? 0,
              row['reps_min'] as int? ?? 0,
              row['reps_max'] as int? ?? 0,
              (row['target_rir'] as num?)?.toDouble() ?? 0,
            )),
            if (selectedId == null && suggestions.isNotEmpty)
              DropdownButtonFormField<String>(
                key: Key('program_import_match_${row['source_row']}'),
                initialValue: null,
                decoration: InputDecoration(labelText: copy.unresolvedExercise),
                items: <DropdownMenuItem<String>>[
                  for (final dynamic raw in suggestions)
                    DropdownMenuItem<String>(
                      value: (raw as Map<String, dynamic>)['exercise_id'] as String,
                      child: Text(raw['name'] as String),
                    ),
                ],
                onChanged: (String? id) => _selectExercise(row, id),
              ),
            if (selectedId == null && name.isNotEmpty)
              TextButton.icon(
                key: Key('program_import_create_exercise_${row['source_row']}'),
                onPressed: _busy ? null : () => _createCoachExercise(row),
                icon: const Icon(Icons.add),
                label: Text(copy.createAsCoachExercise),
              ),
            for (final dynamic raw in errors)
              Text(copy.programImportRowMessage(
                raw['code'] as String,
                raw['source_row'] as int,
                raw['column'] as String,
              )),
            for (final dynamic raw in warnings)
              Text(copy.programImportRowMessage(
                raw['code'] as String,
                raw['source_row'] as int,
                raw['column'] as String,
              )),
          ],
        ),
      ),
    );
  }

  Future<void> _pickFile() async {
    final PlatformFile? selected = await ref.read(programSpreadsheetPickerProvider)();
    if (!mounted || selected == null) return;
    setState(() {
      _file = selected;
      _result = null;
      _rows = <Map<String, dynamic>>[];
      _selectedTab = null;
      _error = null;
    });
    if (selected.bytes == null) {
      setState(() => _error = coachCopyOf(context).importCreateFailure);
      return;
    }
    await _readSelectedFile();
  }

  Future<void> _readSelectedFile({String? sheet}) async {
    final PlatformFile? file = _file;
    if (file?.bytes == null) return;
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      final Map<String, dynamic> result = await ref.read(apiClientProvider)
          .coachImportProgramSheet(
            widget.assignmentId,
            bytes: file!.bytes!,
            fileName: file.name,
            sheet: sheet,
          );
      if (!mounted) return;
      setState(() {
        _result = result;
        _rows = (result['rows'] as List<dynamic>? ?? <dynamic>[])
            .map((dynamic row) => Map<String, dynamic>.from(row as Map))
            .toList();
        _selectedTab = result['selected_tab'] as String? ?? _selectedTab;
      });
    } on ApiException catch (error) {
      if (mounted) setState(() => _error = _displayApiFailure(error));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  void _selectExercise(Map<String, dynamic> row, String? exerciseId) {
    if (exerciseId == null) return;
    final List<dynamic> suggestions = row['suggestions'] as List<dynamic>;
    final Map<String, dynamic> match = suggestions
        .cast<Map<String, dynamic>>()
        .firstWhere((Map<String, dynamic> candidate) =>
            candidate['exercise_id'] == exerciseId);
    setState(() {
      row['exercise_id'] = exerciseId;
      row['exercise_name'] = match['name'];
      row['resolution'] = 'confirmed';
      row['warnings'] = _withoutExerciseWarnings(row);
    });
  }

  Future<void> _createCoachExercise(Map<String, dynamic> row) async {
    setState(() => _busy = true);
    try {
      final ExerciseCatalogEntry exercise = await ref.read(apiClientProvider)
          .coachCreateExercise(CoachExerciseCreateRequest(
            name: row['exercise_name'] as String,
          ));
      if (mounted) {
        setState(() {
          row['exercise_id'] = exercise.id;
          row['exercise_name'] = exercise.name;
          row['resolution'] = 'confirmed';
          row['warnings'] = _withoutExerciseWarnings(row);
        });
      }
    } on ApiException catch (error) {
      if (mounted) setState(() => _error = _displayApiFailure(error));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  List<dynamic> _withoutExerciseWarnings(Map<String, dynamic> row) =>
      (row['warnings'] as List<dynamic>? ?? <dynamic>[])
          .where((dynamic warning) =>
              warning['code'] != 'program_import.exercise_unresolved.v1' &&
              warning['code'] != 'program_import.exercise_ambiguous.v1')
          .toList();

  Future<void> _createDraft() async {
    bool replace = _result?['draft_exists'] == true;
    if (replace && !await _confirmReplacement()) return;
    setState(() => _busy = true);
    try {
      while (true) {
        try {
          await ref.read(apiClientProvider).coachCreateImportedProgramDraft(
                widget.assignmentId,
                programName: _programNameFromFile(_file?.name),
                rows: _confirmedRows,
                replace: replace,
              );
          break;
        } on ApiException catch (error) {
          if (error.statusCode != 409 || replace || !await _confirmReplacement()) {
            rethrow;
          }
          replace = true;
        }
      }
      if (!mounted) return;
      await Navigator.of(context).pushReplacement<void, void>(
        MaterialPageRoute<void>(
          builder: (BuildContext context) => CoachProgramDraftScreen(
            assignmentId: widget.assignmentId,
            playerUsername: widget.playerUsername,
          ),
        ),
      );
    } on ApiException catch (error) {
      if (mounted) setState(() => _error = _displayApiFailure(error));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<bool> _confirmReplacement() async {
    final CoachCopy copy = coachCopyOf(context);
    return await showDialog<bool>(
          context: context,
          builder: (BuildContext context) => AlertDialog(
            title: Text(copy.importReplaceTitle),
            content: Text(copy.importReplacePrompt),
            actions: <Widget>[
              TextButton(
                onPressed: () => Navigator.pop(context, false),
                child: Text(copy.importCancelled),
              ),
              FilledButton(
                onPressed: () => Navigator.pop(context, true),
                child: Text(copy.importReplaceAction),
              ),
            ],
          ),
        ) ??
        false;
  }

  String _displayApiFailure(ApiException error) {
    final CoachCopy copy = coachCopyOf(context);
    if (error.statusCode == 413) return copy.programImportError(error.messageCode);
    if (error.messageCode?.startsWith('program_import.') == true) {
      return copy.programImportError(error.messageCode);
    }
    return displayCopyOf(context).failureMessage(apiFailureMessage(error));
  }

  String? _programNameFromFile(String? fileName) {
    if (fileName == null || fileName.isEmpty) return null;
    final int dot = fileName.lastIndexOf('.');
    final String name = dot > 0 ? fileName.substring(0, dot) : fileName;
    return name.isEmpty ? null : (name.length > 120 ? name.substring(0, 120) : name);
  }
}

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
import '../../core/ui/is_desktop_layout.dart';
import '../../core/ui/mayos_text_field.dart';
import '../../providers.dart';
import 'coach_program_draft_screen.dart';
import 'program_import_files.dart';

enum _ProgramImportInputMode { file, paste }

class CoachProgramImportScreen extends ConsumerStatefulWidget {
  const CoachProgramImportScreen({
    super.key,
    required this.assignmentId,
    required this.playerUsername,
    this.initialText,
  });

  final String assignmentId;
  final String playerUsername;
  final String? initialText;

  @override
  ConsumerState<CoachProgramImportScreen> createState() =>
      _CoachProgramImportScreenState();
}

class _CoachProgramImportScreenState
    extends ConsumerState<CoachProgramImportScreen> {
  static const int _textImportLimit = 20000;

  PlatformFile? _file;
  final TextEditingController _pasteController = TextEditingController();
  String _lastPasteText = '';
  bool _textAvailable = false;
  bool _textCapabilityLoaded = false;
  _ProgramImportInputMode _inputMode = _ProgramImportInputMode.file;
  Map<String, dynamic>? _result;
  List<Map<String, dynamic>> _allRows = <Map<String, dynamic>>[];
  String? _selectedTab;
  String? _selectedWeek;
  String? _error;
  bool _busy = false;
  bool _layoutConfirmed = false;
  bool _layoutRejected = false;

  @override
  void initState() {
    super.initState();
    _pasteController.addListener(_pasteChanged);
    if (widget.initialText != null) {
      _inputMode = _ProgramImportInputMode.paste;
      _pasteController.text = widget.initialText!;
      _lastPasteText = widget.initialText!;
    }
    _loadTextCapability();
  }

  @override
  void dispose() {
    _pasteController.removeListener(_pasteChanged);
    _pasteController.dispose();
    super.dispose();
  }

  void _pasteChanged() {
    final String text = _pasteController.text;
    if (text == _lastPasteText) return;
    _lastPasteText = text;
    if (!mounted) return;
    setState(() {
      _result = null;
      _error = null;
    });
  }

  Future<void> _loadTextCapability() async {
    try {
      final ProgramImportCapabilities capabilities = await ref
          .read(apiClientProvider)
          .coachProgramImportCapabilities();
      if (mounted) {
        setState(() {
          _textAvailable = capabilities.textAvailable;
          _textCapabilityLoaded = true;
        });
      }
    } on ApiException {
      // Text input stays hidden if the capability service is unavailable.
      if (mounted) {
        setState(() => _textCapabilityLoaded = true);
      }
    }
  }

  int get _normalizedPasteLength {
    final String normalized =
        _pasteController.text.replaceAll('\r\n', '\n').replaceAll('\r', '\n');
    return normalized.runes.length;
  }

  bool get _pasteCanSubmit =>
      _pasteController.text.trim().isNotEmpty &&
      _normalizedPasteLength <= _textImportLimit;

  void _selectInputMode(_ProgramImportInputMode mode) {
    if (mode == _inputMode) return;
    setState(() {
      _inputMode = mode;
      _result = null;
      _allRows = <Map<String, dynamic>>[];
      _selectedTab = null;
      _selectedWeek = null;
      _error = null;
      _layoutConfirmed = false;
      _layoutRejected = false;
    });
  }

  List<String> get _detectedWeeks =>
      (_result?['detected_weeks'] as List<dynamic>? ?? const <dynamic>[])
          .map((dynamic week) => week.toString())
          .toList(growable: false);

  List<Map<String, dynamic>> get _rows {
    if (_result?['import_mode'] == 'template') return _allRows;
    if (_selectedWeek == null || _detectedWeeks.isEmpty) return _allRows;
    return _allRows
        .where((Map<String, dynamic> row) => row['week'] == _selectedWeek)
        .toList(growable: false);
  }

  bool get _isTextImport => _result?['import_mode'] == 'text';

  List<String> get _weeksNotImported =>
      _detectedWeeks.where((String week) => week != _selectedWeek).toList();

  @override
  Widget build(BuildContext context) {
    final CoachCopy copy = coachCopyOf(context);
    final bool desktop = isDesktopLayout(context);
    return Scaffold(
      key: const Key('coach_program_import_screen'),
      appBar: AppBar(title: Text(copy.programImportTitle)),
      bottomNavigationBar: desktop ? null : _phoneBottomAction(context),
      body: SafeArea(
        child: ListView(
          padding: EdgeInsetsDirectional.fromSTEB(
            MayosSpacing.md,
            MayosSpacing.md,
            MayosSpacing.md,
            // Keep the final row clear of the pinned action and shell tabs.
            isDesktopLayout(context) ? MayosSpacing.md : MayosSpacing.xxl,
          ),
          children: <Widget>[
            Text(copy.importPrivacyNote),
            const SizedBox(height: MayosSpacing.md),
            if (widget.initialText != null &&
                _textCapabilityLoaded &&
                !_textAvailable)
              Text(copy.textImportUnavailable),
            if (_textAvailable) ...<Widget>[
              SegmentedButton<_ProgramImportInputMode>(
                key: const Key('program_import_input_mode'),
                segments: <ButtonSegment<_ProgramImportInputMode>>[
                  ButtonSegment<_ProgramImportInputMode>(
                    value: _ProgramImportInputMode.file,
                    label: Text(copy.uploadProgramFile),
                  ),
                  ButtonSegment<_ProgramImportInputMode>(
                    value: _ProgramImportInputMode.paste,
                    label: Text(copy.pasteProgram),
                  ),
                ],
                selected: <_ProgramImportInputMode>{_inputMode},
                onSelectionChanged: _busy
                    ? null
                    : (Set<_ProgramImportInputMode> selection) =>
                        _selectInputMode(selection.first),
              ),
              const SizedBox(height: MayosSpacing.md),
            ],
            if (_inputMode == _ProgramImportInputMode.file || !_textAvailable)
              MayosButton(
                key: const Key('program_import_pick_file'),
                label: _file?.name ??
                    (_textAvailable
                        ? copy.chooseProgramFileWithText
                        : copy.chooseSpreadsheet),
                icon: Icons.upload_file,
                variant: MayosButtonVariant.secondary,
                loading: _busy && _result == null,
                onPressed: _busy ? null : _pickFile,
              ),
            if (_inputMode == _ProgramImportInputMode.paste && _textAvailable) ...<Widget>[
              MayosTextField(
                key: const Key('program_import_paste_field'),
                fieldKey: const Key('program_import_paste_input'),
                controller: _pasteController,
                label: copy.pasteProgram,
                helperText: copy.pasteOnlyProgramReminder,
                minLines: 6,
                maxLines: 10,
                keyboardType: TextInputType.multiline,
                textInputAction: TextInputAction.newline,
              ),
              const SizedBox(height: MayosSpacing.xs),
              Text(copy.programImportCharacterCount(
                _normalizedPasteLength,
                _textImportLimit,
              )),
              if (_normalizedPasteLength > _textImportLimit)
                Text(
                  copy.programImportOverLimit(_textImportLimit),
                  style: TextStyle(color: Theme.of(context).colorScheme.error),
                ),
              const SizedBox(height: MayosSpacing.sm),
              if (_result == null && isDesktopLayout(context))
                MayosButton(
                  key: const Key('program_import_submit_paste'),
                  label: copy.reviewImport,
                  icon: Icons.rate_review,
                  loading: _busy,
                  onPressed: _busy || !_pasteCanSubmit ? null : _readPastedText,
                ),
            ],
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
              if (_result?['confirm_layout'] == true)
                _layoutConfirmation(context),
              if (!_layoutRejected &&
                  (_result?['requires_tab_choice'] != true) &&
                  _layoutCanContinue)
                _importReview(context),
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

  bool get _layoutCanContinue =>
      _result?['confirm_layout'] != true || _layoutConfirmed;

  Widget _importReview(BuildContext context) {
    final CoachCopy copy = coachCopyOf(context);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: <Widget>[
        if (_detectedWeeks.isNotEmpty &&
            _result?['import_mode'] != 'template')
          DropdownButtonFormField<String>(
            key: const Key('program_import_week_picker'),
            initialValue: _selectedWeek,
            decoration: InputDecoration(labelText: copy.chooseWeek),
            items: <DropdownMenuItem<String>>[
              for (final String week in _detectedWeeks)
                DropdownMenuItem<String>(value: week, child: Text(week)),
            ],
            onChanged: _busy
                ? null
                : (String? week) {
                    if (week == null) return;
                    setState(() => _selectedWeek = week);
                  },
          ),
        if (_detectedWeeks.isNotEmpty &&
            _result?['import_mode'] == 'template')
          Text(copy.importWeeksIncluded(_detectedWeeks)),
        if (_detectedWeeks.isNotEmpty &&
            _result?['import_mode'] != 'template')
          Text(copy.weeksNotImported(_weeksNotImported, _selectedWeek)),
        Text(copy.importRowsSummary(_rows.length, _confirmedRows.length)),
        if (_confirmedRows.isEmpty) ...<Widget>[
          const SizedBox(height: MayosSpacing.xs),
          Text(copy.importNoValidRows),
        ],
        const SizedBox(height: MayosSpacing.sm),
        for (final Map<String, dynamic> row in _rows)
          _importRow(context, row),
        const SizedBox(height: MayosSpacing.md),
        if (isDesktopLayout(context))
          MayosButton(
            key: const Key('program_import_create_draft'),
            label: copy.createImportedDraft,
            icon: Icons.edit_note,
            loading: _busy,
            onPressed: _busy || _confirmedRows.isEmpty ? null : _createDraft,
          ),
      ],
    );
  }

  Widget? _phoneBottomAction(BuildContext context) {
    final CoachCopy copy = coachCopyOf(context);
    final Widget? action;
    if (_inputMode == _ProgramImportInputMode.paste &&
        _result == null &&
        _textAvailable) {
      action = MayosButton(
        key: const Key('program_import_submit_paste'),
        label: copy.reviewImport,
        icon: Icons.rate_review,
        loading: _busy,
        onPressed: _busy || !_pasteCanSubmit ? null : _readPastedText,
      );
    } else if (_result?['confirm_layout'] == true &&
        !_layoutConfirmed &&
        !_layoutRejected) {
      action = Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: <Widget>[
          OutlinedButton(
            key: const Key('program_import_layout_not_right'),
            onPressed: () => setState(() => _layoutRejected = true),
            child: Text(copy.layoutNotRight),
          ),
          const SizedBox(height: MayosSpacing.xs),
          FilledButton(
            key: const Key('program_import_layout_confirm'),
            onPressed: () => setState(() => _layoutConfirmed = true),
            child: Text(copy.confirmLayoutAndContinue),
          ),
        ],
      );
    } else if (_result != null && _layoutCanContinue && !_layoutRejected) {
      action = MayosButton(
        key: const Key('program_import_create_draft'),
        label: copy.createImportedDraft,
        icon: Icons.edit_note,
        loading: _busy,
        onPressed: _busy || _confirmedRows.isEmpty ? null : _createDraft,
      );
    } else {
      return null;
    }
    return SafeArea(
      top: false,
      child: Padding(
        padding: const EdgeInsets.all(MayosSpacing.md),
        child: action,
      ),
    );
  }

  Widget _layoutConfirmation(BuildContext context) {
    final CoachCopy copy = coachCopyOf(context);
    final List<String> days = <String>[];
    for (final dynamic raw in _result?['layout_days'] as List<dynamic>? ??
        const <dynamic>[]) {
      if (raw is Map<String, dynamic>) {
        final String name = raw['name']?.toString() ?? '';
        if (name.isNotEmpty) days.add(name);
      }
    }
    final Map<String, List<int>> rowsByWeek = <String, List<int>>{};
    final List<int> unassigned = <int>[];
    for (final Map<String, dynamic> row in _allRows) {
      final String? week = row['week'] as String?;
      final int sourceRow = row['source_row'] as int;
      if (week == null) {
        unassigned.add(sourceRow);
      } else {
        rowsByWeek.putIfAbsent(week, () => <int>[]).add(sourceRow);
      }
    }
    return Card(
      key: const Key('program_import_layout_confirmation'),
      child: Padding(
        padding: const EdgeInsets.all(MayosSpacing.md),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: <Widget>[
            Text(copy.importLayoutConfirmTitle,
                style: Theme.of(context).textTheme.titleMedium),
            const SizedBox(height: MayosSpacing.xs),
            Text(copy.importLayoutNeedsConfirmation),
            const SizedBox(height: MayosSpacing.xs),
            Text(copy.importLayoutSummary(days, _detectedWeeks, rowsByWeek, unassigned)),
            if (_layoutRejected) ...<Widget>[
              const SizedBox(height: MayosSpacing.xs),
              Text(copy.layoutNotRightGuidance),
              if ((_result?['detected_tabs'] as List<dynamic>? ??
                      const <dynamic>[])
                  .length >
                  1) ...<Widget>[
                DropdownButtonFormField<String>(
                  key: const Key('program_import_layout_tab_picker'),
                  initialValue: _selectedTab,
                  decoration: InputDecoration(labelText: copy.chooseAnotherSheet),
                  items: <DropdownMenuItem<String>>[
                    for (final dynamic tab
                        in _result!['detected_tabs'] as List<dynamic>)
                      DropdownMenuItem<String>(
                        value: tab as String,
                        child: Text(tab),
                      ),
                  ],
                  onChanged: (String? tab) => setState(() => _selectedTab = tab),
                ),
                MayosButton(
                  key: const Key('program_import_read_another_sheet'),
                  label: copy.readAnotherSheet,
                  loading: _busy,
                  onPressed: _busy || _selectedTab == null
                      ? null
                      : () => _readSelectedFile(sheet: _selectedTab),
                ),
              ],
            ] else if (!_layoutConfirmed && isDesktopLayout(context)) ...<Widget>[
              const SizedBox(height: MayosSpacing.sm),
              Wrap(
                spacing: MayosSpacing.sm,
                children: <Widget>[
                  OutlinedButton(
                    key: const Key('program_import_layout_not_right'),
                    onPressed: () => setState(() => _layoutRejected = true),
                    child: Text(copy.layoutNotRight),
                  ),
                  FilledButton(
                    key: const Key('program_import_layout_confirm'),
                    onPressed: () => setState(() => _layoutConfirmed = true),
                    child: Text(copy.confirmLayoutAndContinue),
                  ),
                ],
              ),
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
            'week_order': row['week_order'] ?? 1,
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
            Text('${_rowPositionLabel(copy, row)} · $name'),
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
              Text(_importPositionMessage(
                copy,
                Map<String, dynamic>.from(raw as Map),
              )),
            for (final dynamic raw in warnings)
              Text(_importPositionMessage(
                copy,
                Map<String, dynamic>.from(raw as Map),
              )),
          ],
        ),
      ),
    );
  }

  Future<void> _pickFile() async {
    final PlatformFile? selected = await ref
        .read(programSpreadsheetPickerProvider)(
          mode: _textAvailable
              ? ProgramImportPickerMode.allSupported
              : ProgramImportPickerMode.spreadsheetsOnly,
        );
    if (!mounted || selected == null) return;
    setState(() {
      _inputMode = _ProgramImportInputMode.file;
      _file = selected;
      _result = null;
      _allRows = <Map<String, dynamic>>[];
      _selectedTab = null;
      _selectedWeek = null;
      _error = null;
      _layoutConfirmed = false;
      _layoutRejected = false;
    });
    if (selected.bytes == null) {
      setState(() => _error = coachCopyOf(context).importCreateFailure);
      return;
    }
    await _readSelectedFile();
  }

  String _rowPositionLabel(CoachCopy copy, Map<String, dynamic> row) =>
      _isTextImport
          ? copy.lineLabel(row['source_row'] as int)
          : copy.rowLabel(row['source_row'] as int);

  String _importPositionMessage(
      CoachCopy copy, Map<String, dynamic> message) =>
      _isTextImport
          ? copy.programImportLineMessage(
              message['code'] as String,
              message['source_row'] as int,
              message['column'] as String,
            )
          : copy.programImportRowMessage(
              message['code'] as String,
              message['source_row'] as int,
              message['column'] as String,
            );

  Future<void> _readPastedText() async {
    if (!_pasteCanSubmit) return;
    setState(() {
      _busy = true;
      _error = null;
      _file = null;
    });
    try {
      final Map<String, dynamic> result = await ref.read(apiClientProvider)
          .coachImportProgramText(
            widget.assignmentId,
            text: _pasteController.text,
          );
      if (!mounted) return;
      _setImportResult(result);
    } on ApiException catch (error) {
      if (mounted) setState(() => _error = _displayApiFailure(error));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  void _setImportResult(Map<String, dynamic> result) {
    setState(() {
      _result = result;
      _allRows = (result['rows'] as List<dynamic>? ?? <dynamic>[])
          .map((dynamic row) => Map<String, dynamic>.from(row as Map))
          .toList();
      _selectedTab = result['selected_tab'] as String? ?? _selectedTab;
      _selectedWeek = result['selected_week'] as String? ?? _selectedWeek;
      _layoutConfirmed = result['confirm_layout'] != true;
      _layoutRejected = false;
    });
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
            sheet: file.name.toLowerCase().endsWith('.xlsx')
                ? (sheet ?? _selectedTab)
                : null,
          );
      if (!mounted) return;
      _setImportResult(result);
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
    if (!_layoutCanContinue || _layoutRejected) return;
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
    if (error.statusCode == 413) {
      return copy.programImportError(error.messageCode, messageParams: error.messageParams);
    }
    if (error.messageCode?.startsWith('program_import.') == true) {
      return copy.programImportError(error.messageCode, messageParams: error.messageParams);
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

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api_client.dart';
import '../../core/app_failure.dart';
import '../../core/connectivity_message.dart';
import '../../core/display_language/copy_context.dart';
import '../../core/display_language/controller.dart';
import '../../core/display_language/settings_copy.dart';
import '../../providers.dart';

class AssistantPreferencesScreen extends ConsumerStatefulWidget {
  const AssistantPreferencesScreen({super.key});

  @override
  ConsumerState<AssistantPreferencesScreen> createState() =>
      _AssistantPreferencesScreenState();
}

class _AssistantPreferencesScreenState
    extends ConsumerState<AssistantPreferencesScreen> {
  late Future<List<Map<String, dynamic>>> _preferences;
  bool _writing = false;
  FailureMessage? _writeFailure;

  SettingsCopy get _copy => SettingsCopy(ref.read(displayLanguageProvider));

  @override
  void initState() {
    super.initState();
    _preferences = ref.read(apiClientProvider).assistantPreferences();
  }

  void _reload() {
    if (!mounted) return;
    setState(() {
      _preferences = ref.read(apiClientProvider).assistantPreferences();
      _writeFailure = null;
    });
  }

  Future<FailureMessage?> _update(String id, String text) async {
    if (_writing) return null;
    setState(() {
      _writing = true;
      _writeFailure = null;
    });
    try {
      await ref.read(apiClientProvider).updateAssistantPreference(id, text);
      if (!mounted) return null;
      _reload();
      return null;
    } on ApiException catch (error) {
      if (!mounted) return null;
      return apiFailureMessage(error);
    } finally {
      if (mounted) {
        setState(() => _writing = false);
      }
    }
  }

  Future<void> _delete(String id) async {
    if (_writing) return;
    setState(() {
      _writing = true;
      _writeFailure = null;
    });
    try {
      await ref.read(apiClientProvider).deleteAssistantPreference(id);
      if (!mounted) return;
      _reload();
    } on ApiException catch (error) {
      if (!mounted) return;
      setState(() => _writeFailure = apiFailureMessage(error));
    } finally {
      if (mounted) {
        setState(() => _writing = false);
      }
    }
  }

  Future<void> _edit(Map<String, dynamic> preference) async {
    if (_writing) return;
    await showDialog<void>(
      context: context,
      builder: (BuildContext context) => _AssistantPreferenceEditDialog(
        initialText: preference['text'] as String? ?? '',
        copy: _copy,
        onSave: (String text) => _update(preference['id'] as String, text),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    ref.watch(displayLanguageProvider);
    return Scaffold(
      body: FutureBuilder<List<Map<String, dynamic>>>(
        future: _preferences,
        builder: _buildPreferences,
      ),
    );
  }

  Widget _buildPreferences(
    BuildContext context,
    AsyncSnapshot<List<Map<String, dynamic>>> snapshot,
  ) {
    if (snapshot.connectionState != ConnectionState.done) {
      return const Center(child: CircularProgressIndicator());
    }
    if (snapshot.hasError) {
      return Center(child: Text(_copy.assistantPreferencesLoadFailed));
    }
    final List<Map<String, dynamic>> preferences =
        snapshot.data ?? <Map<String, dynamic>>[];
    return preferences.isEmpty
        ? Center(child: Text(_copy.noAssistantPreferences))
        : _preferenceList(preferences);
  }

  Widget _preferenceList(List<Map<String, dynamic>> preferences) => ListView(
        padding: const EdgeInsets.all(16),
        children: <Widget>[
          Text(_copy.assistantPreferencesLead),
          if (_writeFailure != null) ...<Widget>[
            const SizedBox(height: 8),
            Text(
              displayCopyOf(context).failureMessage(_writeFailure!),
              key: const Key('assistant-preference-write-error'),
            ),
          ],
          const SizedBox(height: 12),
          for (final Map<String, dynamic> preference in preferences)
            _preferenceTile(preference),
        ],
      );

  Widget _preferenceTile(Map<String, dynamic> preference) => Card(
        child: ListTile(
          title: Text(preference['text'] as String? ?? ''),
          trailing: Wrap(
            children: <Widget>[
              IconButton(
                tooltip: _copy.editPreference,
                icon: const Icon(Icons.edit_outlined),
                onPressed: _writing ? null : () => _edit(preference),
              ),
              IconButton(
                tooltip: _copy.deletePreference,
                icon: const Icon(Icons.delete_outline),
                onPressed:
                    _writing ? null : () => _delete(preference['id'] as String),
              ),
            ],
          ),
        ),
      );
}

class _AssistantPreferenceEditDialog extends StatefulWidget {
  const _AssistantPreferenceEditDialog({
    required this.initialText,
    required this.copy,
    required this.onSave,
  });

  final String initialText;
  final SettingsCopy copy;
  final Future<FailureMessage?> Function(String text) onSave;

  @override
  State<_AssistantPreferenceEditDialog> createState() =>
      _AssistantPreferenceEditDialogState();
}

class _AssistantPreferenceEditDialogState
    extends State<_AssistantPreferenceEditDialog> {
  late final TextEditingController _controller =
      TextEditingController(text: widget.initialText);
  bool _saving = false;
  FailureMessage? _failure;

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  Future<void> _save() async {
    if (_saving) return;
    final String text = _controller.text.trim();
    if (text.isEmpty) return;
    setState(() {
      _saving = true;
      _failure = null;
    });
    final FailureMessage? failure = await widget.onSave(text);
    if (!mounted) return;
    if (failure != null) {
      setState(() {
        _saving = false;
        _failure = failure;
      });
      return;
    }
    Navigator.of(context).pop();
  }

  @override
  Widget build(BuildContext context) => AlertDialog(
        title: Text(widget.copy.editPreference),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          children: <Widget>[
            TextField(
              controller: _controller,
              maxLength: 200,
              maxLines: 3,
              autofocus: true,
            ),
            if (_failure != null)
              Align(
                alignment: AlignmentDirectional.centerStart,
                child: Text(
                  displayCopyOf(context).failureMessage(_failure!),
                  key: const Key('assistant-preference-edit-error'),
                ),
              ),
          ],
        ),
        actions: <Widget>[
          TextButton(
            onPressed: _saving ? null : () => Navigator.of(context).pop(),
            child: Text(widget.copy.cancel),
          ),
          FilledButton(
            onPressed: _saving ? null : _save,
            child: _saving
                ? const SizedBox.square(
                    dimension: 18,
                    child: CircularProgressIndicator(strokeWidth: 2),
                  )
                : Text(widget.copy.savePreference),
          ),
        ],
      );
}

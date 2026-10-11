import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api_client.dart';
import '../../core/app_failure.dart';
import '../../core/connectivity_message.dart';
import '../../core/display_language/catalog.dart';
import '../../core/display_language/controller.dart';
import '../../core/display_language/settings_copy.dart';
import '../../core/models.dart';
import '../../core/theme/mayos_spacing.dart';
import '../../core/theme/mayos_theme.dart';
import '../../core/ui/mayos_button.dart';
import '../../core/ui/mayos_card.dart';
import '../../core/ui/mayos_choice_card.dart';
import '../../core/ui/mayos_section_header.dart';
import '../../core/ui/mayos_text_field.dart';
import '../../providers.dart';

enum _PersonalizationStatus {
  loading,
  loadFailed,
  ready,
  saving,
  saveSucceeded,
  saveFailed,
}

class _AssistantStylePreset {
  const _AssistantStylePreset(this.key);

  final String key;
}

const List<_AssistantStylePreset> _assistantStylePresets =
    <_AssistantStylePreset>[
  _AssistantStylePreset(defaultAssistantStyle),
  _AssistantStylePreset('encouraging'),
  _AssistantStylePreset('scientific'),
  _AssistantStylePreset('tough_love'),
  _AssistantStylePreset('concise'),
];

class PersonalizationScreen extends ConsumerStatefulWidget {
  const PersonalizationScreen({super.key});

  @override
  ConsumerState<PersonalizationScreen> createState() =>
      _PersonalizationScreenState();
}

class _PersonalizationScreenState extends ConsumerState<PersonalizationScreen> {
  final TextEditingController _instructions = TextEditingController();
  final TextEditingController _preferredName = TextEditingController();

  SettingsCopy get _copy => SettingsCopy(ref.read(displayLanguageProvider));

  String _style = defaultAssistantStyle;
  _PersonalizationStatus _status = _PersonalizationStatus.loading;
  String? _message;
  FailureMessage? _failure;
  bool _preferredNameSaving = false;
  bool _preferredNameSaveFailed = false;
  String? _preferredNameMessage;
  String? _preferredNameError;
  FailureMessage? _preferredNameFailure;

  bool get _savingSettings =>
      _preferredNameSaving || _status == _PersonalizationStatus.saving;

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void dispose() {
    _instructions.dispose();
    _preferredName.dispose();
    super.dispose();
  }

  Future<void> _load() async {
    setState(() {
      _status = _PersonalizationStatus.loading;
      _message = null;
      _failure = null;
    });
    try {
      final PlayerProfile profile = await ref.read(apiClientProvider).profile();
      if (!mounted) return;
      _applyLoadedProfile(profile);
    } on ApiException catch (error) {
      if (!mounted) return;
      _showLoadFailure(error);
    }
  }

  void _applyLoadedProfile(PlayerProfile profile) {
    final bool knownTone = _assistantStylePresets.any(
      (_AssistantStylePreset preset) => preset.key == profile.assistantStyle,
    );
    setState(() {
      _style = knownTone ? profile.assistantStyle : defaultAssistantStyle;
      _instructions.text = profile.assistantInstructions;
      _preferredName.text = profile.preferredName ?? '';
      _status = _PersonalizationStatus.ready;
    });
  }

  void _showLoadFailure(ApiException error) {
    setState(() {
      _status = _PersonalizationStatus.loadFailed;
      _failure = apiFailureMessage(error);
    });
  }

  Future<void> _save() async {
    setState(() {
      _status = _PersonalizationStatus.saving;
      _message = null;
      _failure = null;
    });
    try {
      final PlayerProfile profile = await ref
          .read(apiClientProvider)
          .updateAssistantStyle(
              style: _style, instructions: _instructions.text);
      if (!mounted) return;
      _showSaveSuccess(profile);
    } on ApiException catch (error) {
      if (!mounted) return;
      _showSaveFailure(error);
    }
  }

  Future<void> _savePreferredName(String? preferredName) async {
    final String? validation = preferredName == null
        ? null
        : _validatePreferredName(preferredName);
    if (validation != null) {
      _showPreferredNameValidationError(validation);
      return;
    }
    _startPreferredNameSave();
    try {
      final ProfileUpdateResult update = await ref
          .read(apiClientProvider)
          .updatePreferredName(preferredName);
      if (!mounted) return;
      _showPreferredNameSaved(update.profile, preferredName);
    } on ApiException catch (error) {
      if (!mounted) return;
      _showPreferredNameSaveFailure(error);
    }
  }

  void _showPreferredNameValidationError(String validation) {
    setState(() {
      _preferredNameError = validation;
      _preferredNameMessage = null;
      _preferredNameSaveFailed = true;
      _preferredNameFailure = null;
    });
  }

  void _startPreferredNameSave() {
    setState(() {
      _preferredNameSaving = true;
      _preferredNameError = null;
      _preferredNameMessage = null;
      _preferredNameSaveFailed = false;
      _preferredNameFailure = null;
    });
  }

  void _showPreferredNameSaved(
    PlayerProfile? profile,
    String? preferredName,
  ) {
    setState(() {
      _preferredName.text = profile?.preferredName ?? '';
      _preferredNameSaving = false;
      _preferredNameMessage = preferredName == null
          ? _copy.preferredNameCleared
          : _copy.preferredNameSaved;
      _preferredNameFailure = null;
    });
  }

  void _showPreferredNameSaveFailure(ApiException error) {
    setState(() {
      _preferredNameSaving = false;
      _preferredNameSaveFailed = true;
      _preferredNameMessage =
          error.statusCode == 422 ? _copy.preferredNameInvalid : null;
      _preferredNameFailure =
          error.statusCode == 422 ? null : mutationFailureMessage(error);
    });
  }

  String? _validatePreferredName(String preferredName) {
    if (preferredName.trim().isEmpty) return _copy.preferredNameRequired;
    if (preferredName.runes.length > 60) return _copy.preferredNameTooLong;
    if (RegExp(r'[\x00-\x1F\x7F-\x9F\u2028\u2029]')
        .hasMatch(preferredName)) {
      return _copy.preferredNameInvalid;
    }
    return null;
  }

  void _showSaveSuccess(PlayerProfile profile) {
    setState(() {
      _style = profile.assistantStyle;
      _instructions.text = profile.assistantInstructions;
      _status = _PersonalizationStatus.saveSucceeded;
      _message = _copy.styleSaved;
      _failure = null;
    });
  }

  void _showSaveFailure(ApiException error) {
    setState(() {
      _status = _PersonalizationStatus.saveFailed;
      _failure = mutationFailureMessage(error);
    });
  }

  @override
  Widget build(BuildContext context) {
    ref.watch(displayLanguageProvider);
    if (_status == _PersonalizationStatus.loading) {
      return const Center(child: CircularProgressIndicator());
    }
    if (_status == _PersonalizationStatus.loadFailed) {
      return ListView(
        padding: MayosSpacing.screen,
        children: <Widget>[_buildLoadFailure()],
      );
    }
    return ListView(
      padding: MayosSpacing.screen,
      children: <Widget>[_buildEditor()],
    );
  }

  Widget _buildEditor() => Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: <Widget>[
          _buildIntroduction(),
          const SizedBox(height: MayosSpacing.sm),
          _buildPreferredNameCard(),
          const SizedBox(height: MayosSpacing.xl),
          ..._buildPresetCards(),
          _buildInstructionsCard(),
        ],
      );

  Widget _buildLoadFailure() => Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        mainAxisSize: MainAxisSize.min,
        children: <Widget>[
          Text(_failure == null
              ? _message ?? _copy.styleLoadFailed
              : MayosCopy(ref.read(displayLanguageProvider))
                  .failureMessage(_failure!)),
          const SizedBox(height: MayosSpacing.md),
          MayosButton(
            label: _copy.retry,
            variant: MayosButtonVariant.secondary,
            onPressed: _load,
          ),
        ],
      );

  Widget _buildIntroduction() => MayosSectionHeader(
        title: _copy.assistantStyle,
        subtitle: _copy.styleLead,
      );

  Widget _buildPreferredNameCard() => MayosCard(
        padding: const EdgeInsets.all(MayosSpacing.md),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: <Widget>[
            _buildPreferredNameHeading(),
            const SizedBox(height: MayosSpacing.md),
            _buildPreferredNameField(),
            const SizedBox(height: MayosSpacing.md),
            _buildPreferredNameNotice(),
            _buildPreferredNameActions(),
          ],
        ),
      );

  Widget _buildPreferredNameHeading() => Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          Text(
            _copy.preferredName,
            style: Theme.of(context).textTheme.titleMedium,
          ),
          const SizedBox(height: MayosSpacing.xs),
          Text(
            _copy.preferredNameLead,
            style: Theme.of(context).textTheme.bodySmall,
          ),
        ],
      );

  Widget _buildPreferredNameField() => MayosTextField(
        fieldKey: const Key('preferred_name_field'),
        controller: _preferredName,
        label: _copy.preferredName,
        hint: _copy.preferredNameHint,
        errorText: _preferredNameError,
        maxLength: 60,
        enabled: !_savingSettings,
        textInputAction: TextInputAction.done,
        onChanged: (_) => setState(() {
          _preferredNameError = null;
          _preferredNameMessage = null;
          _preferredNameSaveFailed = false;
          _preferredNameFailure = null;
        }),
      );

  Widget _buildPreferredNameActions() => Column(
        children: <Widget>[
          MayosButton(
            key: const Key('preferred_name_save'),
            label: _copy.savePreferredName,
            loading: _preferredNameSaving,
            onPressed: _savingSettings
                ? null
                : () => _savePreferredName(_preferredName.text),
          ),
          MayosButton(
            key: const Key('preferred_name_clear'),
            label: _copy.clearPreferredName,
            variant: MayosButtonVariant.tertiary,
            onPressed: _savingSettings || _preferredName.text.isEmpty
                ? null
                : () => _savePreferredName(null),
          ),
        ],
      );

  Widget _buildPreferredNameNotice() {
    final String? message = _preferredNameMessage ??
        (_preferredNameFailure == null
            ? null
            : MayosCopy(ref.read(displayLanguageProvider))
                .failureMessage(_preferredNameFailure!));
    if (message == null) return const SizedBox.shrink();
    final MayosThemeExtension colors = MayosTheme.of(context);
    return Padding(
      padding: const EdgeInsets.only(bottom: MayosSpacing.sm),
      child: Text(
        message,
        style: Theme.of(context).textTheme.bodySmall?.copyWith(
              color: _preferredNameSaveFailed ? colors.danger : colors.success,
            ),
      ),
    );
  }

  List<Widget> _buildPresetCards() => <Widget>[
        for (final _AssistantStylePreset preset
            in _assistantStylePresets) ...<Widget>[
          MayosChoiceCard(
            key: Key('assistant_style_${preset.key}'),
            title: _copy.stylePresetLabel(preset.key),
            subtitle: _copy.stylePresetDescription(preset.key),
            selected: _style == preset.key,
            onTap: _savingSettings
                ? null
                : () => setState(() => _style = preset.key),
          ),
          const SizedBox(height: MayosSpacing.sm),
        ],
      ];

  Widget _buildInstructionsCard() => MayosCard(
        padding: const EdgeInsets.all(MayosSpacing.md),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: <Widget>[
            _buildInstructionsField(),
            const SizedBox(height: MayosSpacing.md),
            _buildNotice(),
            MayosButton(
              key: const Key('assistant_style_save'),
              label: _copy.saveStyle,
              loading: _status == _PersonalizationStatus.saving,
              onPressed: _savingSettings ? null : _save,
            ),
          ],
        ),
      );

  Widget _buildInstructionsField() => MayosTextField(
        fieldKey: const Key('assistant_style_instructions'),
        controller: _instructions,
        label: _copy.optionalInstructions,
        hint: _copy.instructionsExample,
        helperText: _copy.wordingOnly,
        maxLength: maxAssistantStyleInstructions,
        maxLines: 4,
        minLines: 3,
        enabled: !_savingSettings,
        textInputAction: TextInputAction.newline,
        onChanged: (_) => setState(() {}),
      );

  Widget _buildNotice() {
    final String? message = _message ??
        (_failure == null
            ? null
            : MayosCopy(ref.read(displayLanguageProvider))
                .failureMessage(_failure!));
    if (message == null) return const SizedBox.shrink();
    final MayosThemeExtension colors = MayosTheme.of(context);
    final bool isError = _status == _PersonalizationStatus.saveFailed;
    return Padding(
      padding: const EdgeInsets.only(bottom: MayosSpacing.sm),
      child: Text(
        message,
        style: Theme.of(context).textTheme.bodySmall?.copyWith(
              color: isError ? colors.danger : colors.success,
            ),
      ),
    );
  }
}

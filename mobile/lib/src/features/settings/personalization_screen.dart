import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api_client.dart';
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

  SettingsCopy get _copy => SettingsCopy(ref.read(displayLanguageProvider));

  String _style = defaultAssistantStyle;
  _PersonalizationStatus _status = _PersonalizationStatus.loading;
  String? _message;

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void dispose() {
    _instructions.dispose();
    super.dispose();
  }

  Future<void> _load() async {
    setState(() {
      _status = _PersonalizationStatus.loading;
      _message = null;
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
      _status = _PersonalizationStatus.ready;
    });
  }

  void _showLoadFailure(ApiException error) {
    setState(() {
      _status = _PersonalizationStatus.loadFailed;
      _message = MayosCopy(ref.read(displayLanguageProvider))
          .failureMessage(apiFailureMessage(error));
    });
  }

  Future<void> _save() async {
    setState(() {
      _status = _PersonalizationStatus.saving;
      _message = null;
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

  void _showSaveSuccess(PlayerProfile profile) {
    setState(() {
      _style = profile.assistantStyle;
      _instructions.text = profile.assistantInstructions;
      _status = _PersonalizationStatus.saveSucceeded;
      _message = _copy.styleSaved;
    });
  }

  void _showSaveFailure(ApiException error) {
    setState(() {
      _status = _PersonalizationStatus.saveFailed;
      _message = MayosCopy(ref.read(displayLanguageProvider))
          .failureMessage(mutationFailureMessage(error));
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
          ..._buildPresetCards(),
          _buildInstructionsCard(),
        ],
      );

  Widget _buildLoadFailure() => Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        mainAxisSize: MainAxisSize.min,
        children: <Widget>[
          Text(_message ?? _copy.styleLoadFailed),
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

  List<Widget> _buildPresetCards() => <Widget>[
        for (final _AssistantStylePreset preset
            in _assistantStylePresets) ...<Widget>[
          MayosChoiceCard(
            key: Key('assistant_style_${preset.key}'),
            title: _copy.stylePresetLabel(preset.key),
            subtitle: _copy.stylePresetDescription(preset.key),
            selected: _style == preset.key,
            onTap: _status == _PersonalizationStatus.saving
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
              onPressed:
                  _status == _PersonalizationStatus.saving ? null : _save,
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
        enabled: _status != _PersonalizationStatus.saving,
        textInputAction: TextInputAction.newline,
        onChanged: (_) => setState(() {}),
      );

  Widget _buildNotice() {
    final String? message = _message;
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

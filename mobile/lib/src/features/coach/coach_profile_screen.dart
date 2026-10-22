import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter/services.dart';

import '../../core/api_client.dart';
import '../../core/app_failure.dart';
import '../../core/connectivity_message.dart';
import '../../core/display_language/coach_copy.dart';
import '../../core/display_language/copy_context.dart';
import '../../core/display_language/controller.dart';
import '../../core/display_language/feature_copy_context.dart';
import '../../core/display_language/message_resolver.dart';
import '../../core/models.dart';
import '../../core/theme/myos_spacing.dart';
import '../../core/theme/myos_theme.dart';
import '../../core/theme/myos_typography.dart';
import '../../core/ui/myos_button.dart';
import '../../core/ui/myos_card.dart';
import '../../core/ui/first_strong_direction.dart';
import '../../core/ui/is_desktop_layout.dart';
import '../../providers.dart';
import 'coach_program_templates_screen.dart';

/// Coach profile tab of the Coach mode shell (#119): display name, bio,
/// specialization, capacity, the player invite, assignment notices, and the
/// resolved alerts.
///
/// Only reachable when the account holds the coach capability.
class CoachProfileScreen extends ConsumerStatefulWidget {
  const CoachProfileScreen({super.key});

  @override
  ConsumerState<CoachProfileScreen> createState() => _CoachProfileScreenState();
}

class _CoachProfileScreenState extends ConsumerState<CoachProfileScreen> {
  static const int _maxDisplayName = 60;
  static const int _maxBio = 1000;
  static const int _maxSpecialization = 200;
  static const int _minCapacity = 1;
  static const int _maxCapacity = 200;

  final GlobalKey<FormState> _formKey = GlobalKey<FormState>();
  final TextEditingController _displayName = TextEditingController();
  final TextEditingController _bio = TextEditingController();
  final TextEditingController _specialization = TextEditingController();
  final TextEditingController _capacity = TextEditingController();

  bool _loading = true;
  bool _saving = false;
  bool _savingStallThreshold = false;
  bool _issuing = false;
  int _stallThresholdWeeks = 3;
  FailureMessage? _loadError;
  FailureMessage? _saveError;
  AssignmentInvite? _invite;
  List<AssignmentNotice> _notices = <AssignmentNotice>[];
  List<CoachAlert> _resolvedAlerts = <CoachAlert>[];

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void dispose() {
    _displayName.dispose();
    _bio.dispose();
    _specialization.dispose();
    _capacity.dispose();
    super.dispose();
  }

  Future<void> _load() async {
    setState(() {
      _loading = true;
      _loadError = null;
    });
    try {
      final CoachProfile profile =
          await ref.read(apiClientProvider).coachProfile();
      if (!mounted) return;
      _applyProfile(profile);
      setState(() => _loading = false);
      await _loadStallThreshold();
      await _loadExtras();
    } on ApiException catch (error) {
      if (!mounted) return;
      setState(() {
        _loading = false;
        _loadError = apiFailureMessage(error);
      });
    }
  }

  void _applyProfile(CoachProfile profile) {
    _displayName.text = profile.displayName;
    _bio.text = profile.bio;
    _specialization.text = profile.specialization;
    _capacity.text = profile.capacity.toString();
  }

  Future<void> _loadStallThreshold() async {
    try {
      final CoachSettings settings =
          await ref.read(apiClientProvider).coachSettings();
      if (mounted) {
        setState(() => _stallThresholdWeeks = settings.stallThresholdWeeks);
      }
    } on ApiException {
      // The default threshold remains usable if settings cannot be loaded.
    }
  }

  /// Invite, notices, and resolved alerts are secondary sections: a failure
  /// here leaves the profile form usable.
  Future<void> _loadExtras() async {
    try {
      final List<AssignmentNotice> notices =
          await ref.read(apiClientProvider).coachNotices();
      if (mounted) {
        setState(() => _notices = notices);
      }
    } on ApiException {
      // Non-fatal: the section simply stays empty.
    }
    try {
      final List<CoachAlert> resolved = await ref
          .read(apiClientProvider)
          .coachAlerts(states: const <String>['resolved']);
      if (mounted) {
        setState(() => _resolvedAlerts = resolved);
      }
    } on ApiException {
      // Non-fatal: the section simply stays empty.
    }
  }

  Future<void> _issue() async {
    setState(() {
      _issuing = true;
    });
    try {
      final AssignmentInvite invite =
          await ref.read(apiClientProvider).issueAssignmentInvite();
      if (!mounted) return;
      setState(() {
        _issuing = false;
        _invite = invite;
      });
    } on ApiException catch (error) {
      if (!mounted) return;
      setState(() {
        _issuing = false;
        _saveError = apiFailureMessage(error);
      });
    }
  }

  void _shareInvite(AssignmentInvite invite) {
    unawaited(Clipboard.setData(ClipboardData(text: invite.token)));
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(content: Text(coachCopyOf(context).inviteCopied)),
    );
  }

  Future<void> _markRead() async {
    try {
      await ref.read(apiClientProvider).markCoachNoticesRead();
      if (!mounted) return;
      final List<AssignmentNotice> notices =
          await ref.read(apiClientProvider).coachNotices();
      if (!mounted) return;
      setState(() => _notices = notices);
    } on ApiException catch (error) {
      if (!mounted) return;
      setState(() => _saveError = apiFailureMessage(error));
    }
  }

  Future<void> _save() async {
    setState(() => _saveError = null);
    if (!_formKey.currentState!.validate()) {
      return;
    }
    setState(() => _saving = true);
    try {
      await ref.read(apiClientProvider).updateCoachProfile(
            displayName: _displayName.text.trim(),
            bio: _bio.text,
            specialization: _specialization.text,
            capacity: int.parse(_capacity.text.trim()),
          );
      if (!mounted) return;
      setState(() => _saving = false);
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text(coachCopyOf(context).coachProfileSaved)),
      );
    } on ApiException catch (error) {
      if (!mounted) return;
      setState(() {
        _saving = false;
        _saveError = apiFailureMessage(error);
      });
    }
  }

  Future<void> _saveStallThreshold(int? weeks) async {
    if (weeks == null || weeks == _stallThresholdWeeks) return;
    setState(() {
      _savingStallThreshold = true;
      _saveError = null;
    });
    try {
      final CoachSettings settings = await ref
          .read(apiClientProvider)
          .updateCoachSettings(stallThresholdWeeks: weeks);
      if (!mounted) return;
      _showSavedStallThreshold(settings);
    } on ApiException catch (error) {
      if (!mounted) return;
      _showStallThresholdSaveError(error);
    }
  }

  void _showSavedStallThreshold(CoachSettings settings) {
    setState(() {
      _stallThresholdWeeks = settings.stallThresholdWeeks;
      _savingStallThreshold = false;
    });
    ref.read(coachRosterRevisionProvider.notifier).state++;
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(content: Text(coachCopyOf(context).stallThresholdSaved)),
    );
  }

  void _showStallThresholdSaveError(ApiException error) {
    setState(() {
      _savingStallThreshold = false;
      _saveError = apiFailureMessage(error);
    });
  }

  String? _validateDisplayName(String? value) {
    final copy = coachCopyOf(context);
    final String trimmed = (value ?? '').trim();
    if (trimmed.isEmpty) {
      return copy.enterDisplayName;
    }
    if (trimmed.length > _maxDisplayName) {
      return copy.displayNameMax(_maxDisplayName);
    }
    return null;
  }

  String? _validateCapacity(String? value) {
    final copy = coachCopyOf(context);
    final int? parsed = int.tryParse((value ?? '').trim());
    if (parsed == null) {
      return copy.enterWholeNumber;
    }
    if (parsed < _minCapacity || parsed > _maxCapacity) {
      return copy.capacityMustBe(_minCapacity, _maxCapacity);
    }
    return null;
  }

  @override
  Widget build(BuildContext context) {
    ref.watch(displayLanguageProvider);
    final copy = coachCopyOf(context);
    if (_loading) {
      return const Center(child: CircularProgressIndicator());
    }
    if (_loadError != null) {
      return Center(
        child: Padding(
          padding: const EdgeInsets.all(MyosSpacing.xl),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: <Widget>[
              Text(displayCopyOf(context).failureMessage(_loadError!),
                  textAlign: TextAlign.center),
              const SizedBox(height: MyosSpacing.md),
              MyosButton(
                label: copy.retry,
                variant: MyosButtonVariant.secondary,
                expand: false,
                onPressed: _load,
              ),
            ],
          ),
        ),
      );
    }
    final MyosThemeExtension c = MyosTheme.of(context);
    return Form(
      key: _formKey,
      child: ListView(
        padding: MyosSpacing.screen,
        children: <Widget>[
          Text(
            copy.profileTitle,
            style: MyosTypography.of(context).pageHeading.copyWith(color: c.textPrimary),
          ),
          const SizedBox(height: MyosSpacing.xxs),
          Text(
            copy.profileLead,
            style:
                MyosTypography.of(context).bodySecondary.copyWith(color: c.textSecondary),
          ),
          const SizedBox(height: MyosSpacing.md),
          TextFormField(
            controller: _displayName,
            maxLength: _maxDisplayName,
            decoration: InputDecoration(
              labelText: copy.displayName,
              border: const OutlineInputBorder(),
            ),
            validator: _validateDisplayName,
          ),
          const SizedBox(height: MyosSpacing.sm),
          TextFormField(
            controller: _specialization,
            maxLength: _maxSpecialization,
            decoration: InputDecoration(
              labelText: copy.specialization,
              hintText: copy.specializationHint,
              border: const OutlineInputBorder(),
            ),
          ),
          const SizedBox(height: MyosSpacing.sm),
          TextFormField(
            controller: _bio,
            maxLength: _maxBio,
            maxLines: 4,
            decoration: InputDecoration(
              labelText: copy.bio,
              border: const OutlineInputBorder(),
            ),
          ),
          const SizedBox(height: MyosSpacing.sm),
          TextFormField(
            controller: _capacity,
            keyboardType: TextInputType.number,
            textDirection: TextDirection.ltr,
            decoration: InputDecoration(
              labelText: copy.rosterCapacity,
              helperText: copy.capacityRange(_minCapacity, _maxCapacity),
              border: const OutlineInputBorder(),
            ),
            validator: _validateCapacity,
          ),
          if (_saveError != null) ...<Widget>[
            const SizedBox(height: MyosSpacing.sm),
            Text(
              displayCopyOf(context).failureMessage(_saveError!),
              style: MyosTypography.of(context).bodySecondary.copyWith(color: c.danger),
            ),
          ],
          const SizedBox(height: MyosSpacing.lg),
          MyosButton(
            label: copy.saveProfile,
            loading: _saving,
            onPressed: _saving ? null : _save,
          ),
          const SizedBox(height: MyosSpacing.xl),
          _inviteCard(context),
          const SizedBox(height: MyosSpacing.sm),
          _noticesCard(context),
          const SizedBox(height: MyosSpacing.sm),
          _resolvedAlertsCard(context),
          const SizedBox(height: MyosSpacing.sm),
          _coachSettingsCard(context),
          const SizedBox(height: MyosSpacing.xl),
        ],
      ),
    );
  }

  Widget _coachSettingsCard(BuildContext context) {
    final MyosThemeExtension c = MyosTheme.of(context);
    final copy = coachCopyOf(context);
    return MyosCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          _coachSettingsHeading(context, c, copy),
          const SizedBox(height: MyosSpacing.sm),
          _stallThresholdSelector(copy),
          _stallThresholdStatus(context, c),
          const SizedBox(height: MyosSpacing.sm),
          MyosButton(
            key: const Key('coach_program_templates_open'),
            label: copy.programTemplates,
            variant: MyosButtonVariant.secondary,
            icon: Icons.library_books_outlined,
            onPressed: _openProgramTemplates,
          ),
        ],
      ),
    );
  }

  Future<void> _openProgramTemplates() => Navigator.of(context).push<void>(
        MaterialPageRoute<void>(
          builder: (BuildContext context) =>
              const CoachProgramTemplatesScreen(),
        ),
      );

  Widget _coachSettingsHeading(
    BuildContext context,
    MyosThemeExtension colors,
    CoachCopy copy,
  ) => Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          Text(
            copy.coachSettings,
            style: MyosTypography.of(context)
                .sectionHeading
                .copyWith(color: colors.textPrimary),
          ),
          const SizedBox(height: MyosSpacing.xs),
          Text(
            copy.stallThresholdDescription,
            style: MyosTypography.of(context)
                .bodySecondary
                .copyWith(color: colors.textSecondary),
          ),
        ],
      );

  Widget _stallThresholdSelector(CoachCopy copy) => DropdownButtonFormField<int>(
        key: const Key('coach_stall_threshold'),
        initialValue: _stallThresholdWeeks,
        decoration: InputDecoration(
          labelText: copy.stallThreshold,
          border: const OutlineInputBorder(),
        ),
        items: <DropdownMenuItem<int>>[
          for (int weeks = 1; weeks <= 12; weeks++)
            DropdownMenuItem<int>(
              value: weeks,
              child: Text(copy.stallThresholdOption(weeks)),
            ),
        ],
        onChanged: _savingStallThreshold ? null : _saveStallThreshold,
      );

  Widget _stallThresholdStatus(
    BuildContext context,
    MyosThemeExtension colors,
  ) {
    if (_savingStallThreshold) {
      return const Padding(
        padding: EdgeInsets.only(top: MyosSpacing.xs),
        child: LinearProgressIndicator(),
      );
    }
    if (_saveError == null) return const SizedBox.shrink();
    return Padding(
      padding: const EdgeInsets.only(top: MyosSpacing.xs),
      child: Text(
        displayCopyOf(context).failureMessage(_saveError!),
        style: MyosTypography.of(context)
            .bodySecondary
            .copyWith(color: colors.danger),
      ),
    );
  }

  Widget _inviteCard(BuildContext context) {
    final MyosThemeExtension c = MyosTheme.of(context);
    final AssignmentInvite? invite = _invite;
    return MyosCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          Text(coachCopyOf(context).invitePlayer,
              style: MyosTypography.of(context).sectionHeading
                  .copyWith(color: c.textPrimary)),
          const SizedBox(height: MyosSpacing.xs),
          Text(
            coachCopyOf(context).inviteExplanation,
            style:
                MyosTypography.of(context).bodySecondary.copyWith(color: c.textSecondary),
          ),
          const SizedBox(height: MyosSpacing.sm),
          MyosButton(
            key: const Key('coach_create_player_invite'),
            label: coachCopyOf(context).createPlayerInvite,
            icon: Icons.add,
            loading: _issuing,
            onPressed: _issuing ? null : _issue,
          ),
          if (invite != null) ...<Widget>[
            const SizedBox(height: MyosSpacing.md),
            SelectableText(
              invite.token,
              textDirection: TextDirection.ltr,
              style: MyosTypography.of(context).numeric.copyWith(color: c.textPrimary),
            ),
            if (!isDesktopLayout(context)) ...<Widget>[
              const SizedBox(height: MyosSpacing.xs),
              MyosButton(
                key: const Key('coach_invite_share'),
                label: coachCopyOf(context).copyInviteCode,
                variant: MyosButtonVariant.secondary,
                icon: Icons.copy_outlined,
                onPressed: () => _shareInvite(invite),
              ),
            ],
            const SizedBox(height: MyosSpacing.xxs),
            Text(coachCopyOf(context).inviteExpires(invite.expiresAt),
                style: MyosTypography.of(context).caption.copyWith(color: c.textMuted)),
            Text(
                coachCopyOf(context)
                    .rosterSlotsFree(invite.remaining, invite.capacity),
                style: MyosTypography.of(context).caption.copyWith(color: c.textMuted)),
          ],
        ],
      ),
    );
  }

  Widget _noticesCard(BuildContext context) {
    if (_notices.isEmpty) {
      return const SizedBox.shrink();
    }
    final MyosThemeExtension c = MyosTheme.of(context);
    final int unread =
        _notices.where((AssignmentNotice n) => n.isUnread).length;
    return MyosCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          Row(
            children: <Widget>[
              Expanded(
                child: Text(coachCopyOf(context).notices,
                    style: MyosTypography.of(context).sectionHeading
                        .copyWith(color: c.textPrimary)),
              ),
              if (unread > 0)
                MyosButton(
                  label: coachCopyOf(context).markAllRead,
                  variant: MyosButtonVariant.tertiary,
                  expand: false,
                  onPressed: _markRead,
                ),
            ],
          ),
          for (final AssignmentNotice notice in _notices)
            ListTile(
              dense: true,
              contentPadding: EdgeInsets.zero,
              leading: Icon(
                notice.isUnread
                    ? Icons.notifications_active
                    : Icons.notifications_none,
                color: notice.isUnread ? c.accent : c.textMuted,
              ),
              title: Builder(
                builder: (BuildContext context) {
                  final String message = resolveAssignmentNoticeMessage(
                    notice,
                    displayCopyOf(context).languageCode,
                  );
                  return FirstStrongDirection(
                    text: message,
                    child: Text(message),
                  );
                },
              ),
              subtitle:
                  Text(notice.createdAt, textDirection: TextDirection.ltr),
            ),
        ],
      ),
    );
  }

  Widget _resolvedAlertsCard(BuildContext context) {
    if (_resolvedAlerts.isEmpty) {
      return const SizedBox.shrink();
    }
    final MyosThemeExtension c = MyosTheme.of(context);
    final String languageCode = displayCopyOf(context).languageCode;
    return MyosCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          Text(coachCopyOf(context).resolvedAlerts,
              style: MyosTypography.of(context).sectionHeading
                  .copyWith(color: c.textPrimary)),
          for (final CoachAlert alert in _resolvedAlerts)
            _resolvedAlertTile(context, alert, languageCode, c),
        ],
      ),
    );
  }

  Widget _resolvedAlertTile(
    BuildContext context,
    CoachAlert alert,
    String languageCode,
    MyosThemeExtension colors,
  ) {
    final String description =
        resolveCoachAlertDescription(alert, languageCode);
    final String text = '${alert.playerUsername} · $description';
    return ListTile(
      dense: true,
      contentPadding: EdgeInsets.zero,
      leading: Icon(Icons.check_circle_outline, color: colors.success),
      title: FirstStrongDirection(
        text: text,
        child: Text(text),
      ),
      subtitle: alert.resolvedBy == null
          ? null
          : Text(coachCopyOf(context).resolvedBy(alert.resolvedBy!),
              style:
                  MyosTypography.of(context).caption.copyWith(color: colors.textMuted)),
    );
  }
}

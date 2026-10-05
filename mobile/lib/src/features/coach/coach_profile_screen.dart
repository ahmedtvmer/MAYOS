import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api_client.dart';
import '../../core/app_failure.dart';
import '../../core/connectivity_message.dart';
import '../../core/display_language/copy_context.dart';
import '../../core/display_language/controller.dart';
import '../../core/display_language/feature_copy_context.dart';
import '../../core/display_language/message_resolver.dart';
import '../../core/models.dart';
import '../../core/theme/mayos_spacing.dart';
import '../../core/theme/mayos_theme.dart';
import '../../core/theme/mayos_typography.dart';
import '../../core/ui/mayos_button.dart';
import '../../core/ui/mayos_card.dart';
import '../../core/ui/first_strong_direction.dart';
import '../../providers.dart';

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
  bool _issuing = false;
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
      _displayName.text = profile.displayName;
      _bio.text = profile.bio;
      _specialization.text = profile.specialization;
      _capacity.text = profile.capacity.toString();
      setState(() => _loading = false);
      await _loadExtras();
    } on ApiException catch (error) {
      if (!mounted) return;
      setState(() {
        _loading = false;
        _loadError = apiFailureMessage(error);
      });
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
          padding: const EdgeInsets.all(MayosSpacing.xl),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: <Widget>[
              Text(displayCopyOf(context).failureMessage(_loadError!),
                  textAlign: TextAlign.center),
              const SizedBox(height: MayosSpacing.md),
              MayosButton(
                label: copy.retry,
                variant: MayosButtonVariant.secondary,
                expand: false,
                onPressed: _load,
              ),
            ],
          ),
        ),
      );
    }
    final MayosThemeExtension c = MayosTheme.of(context);
    return Form(
      key: _formKey,
      child: ListView(
        padding: MayosSpacing.screen,
        children: <Widget>[
          Text(
            copy.profileTitle,
            style: MayosTypography.of(context).pageHeading.copyWith(color: c.textPrimary),
          ),
          const SizedBox(height: MayosSpacing.xxs),
          Text(
            copy.profileLead,
            style:
                MayosTypography.of(context).bodySecondary.copyWith(color: c.textSecondary),
          ),
          const SizedBox(height: MayosSpacing.md),
          TextFormField(
            controller: _displayName,
            maxLength: _maxDisplayName,
            decoration: InputDecoration(
              labelText: copy.displayName,
              border: const OutlineInputBorder(),
            ),
            validator: _validateDisplayName,
          ),
          const SizedBox(height: MayosSpacing.sm),
          TextFormField(
            controller: _specialization,
            maxLength: _maxSpecialization,
            decoration: InputDecoration(
              labelText: copy.specialization,
              hintText: copy.specializationHint,
              border: const OutlineInputBorder(),
            ),
          ),
          const SizedBox(height: MayosSpacing.sm),
          TextFormField(
            controller: _bio,
            maxLength: _maxBio,
            maxLines: 4,
            decoration: InputDecoration(
              labelText: copy.bio,
              border: const OutlineInputBorder(),
            ),
          ),
          const SizedBox(height: MayosSpacing.sm),
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
            const SizedBox(height: MayosSpacing.sm),
            Text(
              displayCopyOf(context).failureMessage(_saveError!),
              style: MayosTypography.of(context).bodySecondary.copyWith(color: c.danger),
            ),
          ],
          const SizedBox(height: MayosSpacing.lg),
          MayosButton(
            label: copy.saveProfile,
            loading: _saving,
            onPressed: _saving ? null : _save,
          ),
          const SizedBox(height: MayosSpacing.xl),
          _inviteCard(context),
          const SizedBox(height: MayosSpacing.sm),
          _noticesCard(context),
          const SizedBox(height: MayosSpacing.sm),
          _resolvedAlertsCard(context),
          const SizedBox(height: MayosSpacing.xl),
        ],
      ),
    );
  }

  Widget _inviteCard(BuildContext context) {
    final MayosThemeExtension c = MayosTheme.of(context);
    final AssignmentInvite? invite = _invite;
    return MayosCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          Text(coachCopyOf(context).invitePlayer,
              style: MayosTypography.of(context).sectionHeading
                  .copyWith(color: c.textPrimary)),
          const SizedBox(height: MayosSpacing.xs),
          Text(
            coachCopyOf(context).inviteExplanation,
            style:
                MayosTypography.of(context).bodySecondary.copyWith(color: c.textSecondary),
          ),
          const SizedBox(height: MayosSpacing.sm),
          MayosButton(
            label: coachCopyOf(context).createPlayerInvite,
            icon: Icons.add,
            loading: _issuing,
            onPressed: _issuing ? null : _issue,
          ),
          if (invite != null) ...<Widget>[
            const SizedBox(height: MayosSpacing.md),
            SelectableText(
              invite.token,
              textDirection: TextDirection.ltr,
              style: MayosTypography.of(context).numeric.copyWith(color: c.textPrimary),
            ),
            const SizedBox(height: MayosSpacing.xxs),
            Text(coachCopyOf(context).inviteExpires(invite.expiresAt),
                style: MayosTypography.of(context).caption.copyWith(color: c.textMuted)),
            Text(
                coachCopyOf(context)
                    .rosterSlotsFree(invite.remaining, invite.capacity),
                style: MayosTypography.of(context).caption.copyWith(color: c.textMuted)),
          ],
        ],
      ),
    );
  }

  Widget _noticesCard(BuildContext context) {
    if (_notices.isEmpty) {
      return const SizedBox.shrink();
    }
    final MayosThemeExtension c = MayosTheme.of(context);
    final int unread =
        _notices.where((AssignmentNotice n) => n.isUnread).length;
    return MayosCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          Row(
            children: <Widget>[
              Expanded(
                child: Text(coachCopyOf(context).notices,
                    style: MayosTypography.of(context).sectionHeading
                        .copyWith(color: c.textPrimary)),
              ),
              if (unread > 0)
                MayosButton(
                  label: coachCopyOf(context).markAllRead,
                  variant: MayosButtonVariant.tertiary,
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
              title: FirstStrongDirection(
                text: notice.message,
                child: Text(notice.message),
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
    final MayosThemeExtension c = MayosTheme.of(context);
    final String languageCode = displayCopyOf(context).languageCode;
    return MayosCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          Text(coachCopyOf(context).resolvedAlerts,
              style: MayosTypography.of(context).sectionHeading
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
    MayosThemeExtension colors,
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
                  MayosTypography.of(context).caption.copyWith(color: colors.textMuted)),
    );
  }
}

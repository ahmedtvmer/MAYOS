import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api_client.dart';
import '../../core/models.dart';
import '../../core/theme/mayos_spacing.dart';
import '../../core/theme/mayos_theme.dart';
import '../../core/theme/mayos_typography.dart';
import '../../core/ui/mayos_button.dart';
import '../../core/ui/mayos_card.dart';
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
  String? _loadError;
  String? _saveError;
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
        _loadError = error.message;
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
        _saveError = error.message;
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
      setState(() => _saveError = error.message);
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
        const SnackBar(content: Text('Coach profile saved.')),
      );
    } on ApiException catch (error) {
      if (!mounted) return;
      setState(() {
        _saving = false;
        _saveError = error.message;
      });
    }
  }

  String? _validateDisplayName(String? value) {
    final String trimmed = (value ?? '').trim();
    if (trimmed.isEmpty) {
      return 'Enter a display name.';
    }
    if (trimmed.length > _maxDisplayName) {
      return 'Display name must be at most $_maxDisplayName characters.';
    }
    return null;
  }

  String? _validateCapacity(String? value) {
    final int? parsed = int.tryParse((value ?? '').trim());
    if (parsed == null) {
      return 'Enter a whole number.';
    }
    if (parsed < _minCapacity || parsed > _maxCapacity) {
      return 'Capacity must be between $_minCapacity and $_maxCapacity.';
    }
    return null;
  }

  @override
  Widget build(BuildContext context) {
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
              Text(_loadError!, textAlign: TextAlign.center),
              const SizedBox(height: MayosSpacing.md),
              MayosButton(
                label: 'Retry',
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
            'Coach profile',
            style: MayosTypography.pageHeading.copyWith(color: c.textPrimary),
          ),
          const SizedBox(height: MayosSpacing.xxs),
          Text(
            'These details describe you as a coach.',
            style:
                MayosTypography.bodySecondary.copyWith(color: c.textSecondary),
          ),
          const SizedBox(height: MayosSpacing.md),
          TextFormField(
            controller: _displayName,
            maxLength: _maxDisplayName,
            decoration: const InputDecoration(
              labelText: 'Display name',
              border: OutlineInputBorder(),
            ),
            validator: _validateDisplayName,
          ),
          const SizedBox(height: MayosSpacing.sm),
          TextFormField(
            controller: _specialization,
            maxLength: _maxSpecialization,
            decoration: const InputDecoration(
              labelText: 'Specialization',
              hintText: 'e.g. Powerlifting, Hypertrophy',
              border: OutlineInputBorder(),
            ),
          ),
          const SizedBox(height: MayosSpacing.sm),
          TextFormField(
            controller: _bio,
            maxLength: _maxBio,
            maxLines: 4,
            decoration: const InputDecoration(
              labelText: 'Bio',
              border: OutlineInputBorder(),
            ),
          ),
          const SizedBox(height: MayosSpacing.sm),
          TextFormField(
            controller: _capacity,
            keyboardType: TextInputType.number,
            decoration: const InputDecoration(
              labelText: 'Roster capacity',
              helperText: 'Between $_minCapacity and $_maxCapacity players.',
              border: OutlineInputBorder(),
            ),
            validator: _validateCapacity,
          ),
          if (_saveError != null) ...<Widget>[
            const SizedBox(height: MayosSpacing.sm),
            Text(
              _saveError!,
              style: MayosTypography.bodySecondary.copyWith(color: c.danger),
            ),
          ],
          const SizedBox(height: MayosSpacing.lg),
          MayosButton(
            label: 'Save profile',
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
          Text('Invite a player',
              style: MayosTypography.sectionHeading
                  .copyWith(color: c.textPrimary)),
          const SizedBox(height: MayosSpacing.xs),
          Text(
            'Create a single-use code and give it to one player. It expires and can '
            'only be redeemed while you have roster room; the exact expiry is shown '
            'when the code is issued.',
            style:
                MayosTypography.bodySecondary.copyWith(color: c.textSecondary),
          ),
          const SizedBox(height: MayosSpacing.sm),
          MayosButton(
            label: 'Create player invite',
            icon: Icons.add,
            loading: _issuing,
            onPressed: _issuing ? null : _issue,
          ),
          if (invite != null) ...<Widget>[
            const SizedBox(height: MayosSpacing.md),
            SelectableText(
              invite.token,
              style: MayosTypography.numeric.copyWith(color: c.textPrimary),
            ),
            const SizedBox(height: MayosSpacing.xxs),
            Text('Expires ${invite.expiresAt}',
                style: MayosTypography.caption.copyWith(color: c.textMuted)),
            Text('${invite.remaining} of ${invite.capacity} roster slots free',
                style: MayosTypography.caption.copyWith(color: c.textMuted)),
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
                child: Text('Notices',
                    style: MayosTypography.sectionHeading
                        .copyWith(color: c.textPrimary)),
              ),
              if (unread > 0)
                MayosButton(
                  label: 'Mark all read',
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
              title: Text(notice.message),
              subtitle: Text(notice.createdAt),
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
    return MayosCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          Text('Resolved alerts',
              style: MayosTypography.sectionHeading
                  .copyWith(color: c.textPrimary)),
          for (final CoachAlert alert in _resolvedAlerts)
            ListTile(
              dense: true,
              contentPadding: EdgeInsets.zero,
              leading: Icon(Icons.check_circle_outline, color: c.success),
              title: Text('${alert.playerUsername} · ${alert.description}'),
              subtitle: alert.resolvedBy == null
                  ? null
                  : Text('Resolved by ${alert.resolvedBy}',
                      style: MayosTypography.caption
                          .copyWith(color: c.textMuted)),
            ),
        ],
      ),
    );
  }
}

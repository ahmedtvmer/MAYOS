import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api_client.dart';
import '../../core/models.dart';
import '../../providers.dart';

/// Coach-side assignment console (#24): issue an invite, watch notices, revoke
/// assignments, and disable coaching. Roster history reads belong to #25 and are
/// deliberately absent here.
class CoachAssignmentsScreen extends ConsumerStatefulWidget {
  const CoachAssignmentsScreen({super.key});

  @override
  ConsumerState<CoachAssignmentsScreen> createState() =>
      _CoachAssignmentsScreenState();
}

class _CoachAssignmentsScreenState
    extends ConsumerState<CoachAssignmentsScreen> {
  bool _loading = true;
  bool _issuing = false;
  bool _disabling = false;
  String? _error;
  String? _busyAssignmentId;
  AssignmentInvite? _invite;
  List<CoachRosterEntry> _assignments = <CoachRosterEntry>[];
  List<AssignmentNotice> _notices = <AssignmentNotice>[];

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final List<CoachRosterEntry> assignments =
          await ref.read(apiClientProvider).coachAssignments();
      final List<AssignmentNotice> notices =
          await ref.read(apiClientProvider).coachNotices();
      if (!mounted) return;
      setState(() {
        _assignments = assignments;
        _notices = notices;
        _loading = false;
      });
    } on ApiException catch (error) {
      if (!mounted) return;
      setState(() {
        _loading = false;
        _error = error.message;
      });
    }
  }

  Future<void> _issue() async {
    setState(() {
      _issuing = true;
      _error = null;
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
        _error = error.message;
      });
    }
  }

  Future<void> _revoke(CoachRosterEntry entry) async {
    final bool? confirmed = await showDialog<bool>(
      context: context,
      builder: (BuildContext context) => AlertDialog(
        title: const Text('Revoke assignment?'),
        content: Text(
            '${entry.playerUsername} will lose coaching immediately and can no longer be seen by you.'),
        actions: <Widget>[
          TextButton(
            onPressed: () => Navigator.of(context).pop(false),
            child: const Text('Cancel'),
          ),
          FilledButton(
            onPressed: () => Navigator.of(context).pop(true),
            child: const Text('Revoke'),
          ),
        ],
      ),
    );
    if (confirmed != true || !mounted) return;
    setState(() {
      _busyAssignmentId = entry.assignmentId;
      _error = null;
    });
    try {
      await ref
          .read(apiClientProvider)
          .revokeAssignment(entry.assignmentId);
      if (!mounted) return;
      setState(() {
        _busyAssignmentId = null;
        // The revoke response is the committed truth; drop the row locally.
        _assignments = _assignments
            .where((CoachRosterEntry row) =>
                row.assignmentId != entry.assignmentId)
            .toList(growable: false);
      });
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('Revoked ${entry.playerUsername}.')),
      );
    } on ApiException catch (error) {
      if (!mounted) return;
      setState(() {
        _busyAssignmentId = null;
        _error = error.message;
      });
    }
  }

  Future<void> _markRead() async {
    try {
      await ref.read(apiClientProvider).markCoachNoticesRead();
      if (!mounted) return;
      await _load();
    } on ApiException catch (error) {
      if (!mounted) return;
      setState(() => _error = error.message);
    }
  }

  Future<void> _disable() async {
    final bool? confirmed = await showDialog<bool>(
      context: context,
      builder: (BuildContext context) => AlertDialog(
        title: const Text('Disable coaching?'),
        content: const Text(
            'Every assignment ends immediately and your coach capability is removed. '
            'Your own player training data is kept.'),
        actions: <Widget>[
          TextButton(
            onPressed: () => Navigator.of(context).pop(false),
            child: const Text('Cancel'),
          ),
          FilledButton(
            onPressed: () => Navigator.of(context).pop(true),
            child: const Text('Disable coaching'),
          ),
        ],
      ),
    );
    if (confirmed != true || !mounted) return;
    setState(() {
      _disabling = true;
      _error = null;
    });
    try {
      final int ended =
          await ref.read(apiClientProvider).disableCoachCapability();
      if (!mounted) return;
      setState(() => _disabling = false);
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('Coaching disabled. $ended assignment(s) ended.')),
      );
      ref.read(authControllerProvider.notifier).markCoachDisabled();
    } on ApiException catch (error) {
      if (!mounted) return;
      setState(() {
        _disabling = false;
        _error = error.message;
      });
    }
  }

  Widget _errorBanner(BuildContext context) {
    if (_error == null) {
      return const SizedBox.shrink();
    }
    return Padding(
      padding: const EdgeInsets.only(bottom: 12),
      child: Text(
        _error!,
        style: TextStyle(color: Theme.of(context).colorScheme.error),
      ),
    );
  }

  Widget _inviteCard(BuildContext context) {
    final AssignmentInvite? invite = _invite;
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: <Widget>[
            Text('Player invite',
                style: Theme.of(context).textTheme.titleMedium),
            const SizedBox(height: 8),
            const Text(
              'Create a single-use code and give it to one player. It expires and can '
              'only be redeemed while you have roster room; the exact expiry is shown '
              'when the code is issued.',
            ),
            const SizedBox(height: 12),
            FilledButton.icon(
              onPressed: _issuing ? null : _issue,
              icon: _issuing
                  ? const SizedBox(
                      height: 18,
                      width: 18,
                      child: CircularProgressIndicator(strokeWidth: 2),
                    )
                  : const Icon(Icons.add),
              label: const Text('Create invite code'),
            ),
            if (invite != null) ...<Widget>[
              const SizedBox(height: 16),
              SelectableText(
                invite.token,
                style: Theme.of(context).textTheme.titleMedium,
              ),
              const SizedBox(height: 4),
              Text('Expires ${invite.expiresAt}'),
              Text('${invite.remaining} of ${invite.capacity} roster slots free'),
            ],
          ],
        ),
      ),
    );
  }

  Widget _noticesCard(BuildContext context) {
    if (_notices.isEmpty) {
      return const SizedBox.shrink();
    }
    final int unread = _notices.where((AssignmentNotice n) => n.isUnread).length;
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: <Widget>[
            Row(
              mainAxisAlignment: MainAxisAlignment.spaceBetween,
              children: <Widget>[
                Text('Notices',
                    style: Theme.of(context).textTheme.titleMedium),
                if (unread > 0)
                  TextButton(
                    onPressed: _markRead,
                    child: const Text('Mark all read'),
                  ),
              ],
            ),
            for (final AssignmentNotice notice in _notices)
              ListTile(
                dense: true,
                contentPadding: EdgeInsets.zero,
                leading: Icon(notice.isUnread
                    ? Icons.notifications_active
                    : Icons.notifications_none),
                title: Text(notice.message),
                subtitle: Text(notice.createdAt),
              ),
          ],
        ),
      ),
    );
  }

  Widget _assignmentsCard(BuildContext context) {
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: <Widget>[
            Text('Active assignments',
                style: Theme.of(context).textTheme.titleMedium),
            const SizedBox(height: 8),
            if (_assignments.isEmpty)
              const Text('No assigned players yet.')
            else
              for (final CoachRosterEntry entry in _assignments)
                ListTile(
                  contentPadding: EdgeInsets.zero,
                  leading: const Icon(Icons.person_outline),
                  title: Text(entry.playerUsername),
                  subtitle: Text('Since ${entry.startedAt}'),
                  trailing: TextButton(
                    onPressed: _busyAssignmentId == entry.assignmentId
                        ? null
                        : () => _revoke(entry),
                    child: Text(
                      _busyAssignmentId == entry.assignmentId
                          ? 'Revoking…'
                          : 'Revoke',
                    ),
                  ),
                ),
          ],
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    if (_loading) {
      return const Center(child: CircularProgressIndicator());
    }
    return ListView(
      padding: const EdgeInsets.all(16),
      children: <Widget>[
        _errorBanner(context),
        _inviteCard(context),
        const SizedBox(height: 12),
        _noticesCard(context),
        const SizedBox(height: 12),
        _assignmentsCard(context),
        const SizedBox(height: 24),
        OutlinedButton.icon(
          onPressed: _disabling ? null : _disable,
          icon: const Icon(Icons.logout),
          label: _disabling
              ? const SizedBox(
                  height: 18,
                  width: 18,
                  child: CircularProgressIndicator(strokeWidth: 2),
                )
              : const Text('Disable coaching'),
        ),
      ],
    );
  }
}

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api_client.dart';
import '../../../core/models.dart';
import '../../../providers.dart';

/// Player-side coaching assignment (#24).
///
/// When no assignment is active, the player pastes a coach's bearer code,
/// previews the coach identity and the exact access it grants, then explicitly
/// consents to redeem it. When an assignment is active, the player can end it,
/// which revokes the coach's access immediately.
class PlayerAssignmentScreen extends ConsumerStatefulWidget {
  const PlayerAssignmentScreen({super.key});

  @override
  ConsumerState<PlayerAssignmentScreen> createState() =>
      _PlayerAssignmentScreenState();
}

class _PlayerAssignmentScreenState
    extends ConsumerState<PlayerAssignmentScreen> {
  final TextEditingController _code = TextEditingController();

  bool _loading = true;
  bool _previewing = false;
  bool _redeeming = false;
  bool _ending = false;
  String? _error;
  Assignment? _assignment;
  AssignmentInvitePreview? _preview;
  String? _previewToken;

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void dispose() {
    _code.dispose();
    super.dispose();
  }

  Future<void> _load() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final Assignment? assignment =
          await ref.read(apiClientProvider).myAssignment();
      if (!mounted) return;
      setState(() {
        _assignment = assignment;
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

  /// Any edit invalidates the preview so consent can never target a different code.
  void _onCodeChanged(String _) {
    if (_preview == null && _previewToken == null) {
      return;
    }
    setState(() {
      _preview = null;
      _previewToken = null;
      _error = null;
    });
  }

  Future<void> _previewCode() async {
    final String token = _code.text.trim();
    if (token.length < 10) {
      setState(() => _error = 'Enter the invite code you received.');
      return;
    }
    setState(() {
      _previewing = true;
      _error = null;
      _preview = null;
      _previewToken = null;
    });
    try {
      final AssignmentInvitePreview preview =
          await ref.read(apiClientProvider).previewAssignmentInvite(token);
      if (!mounted) return;
      if (_code.text.trim() != token) {
        setState(() => _previewing = false);
        return;
      }
      setState(() {
        _previewing = false;
        _preview = preview;
        _previewToken = token;
      });
    } on ApiException catch (error) {
      if (!mounted) return;
      setState(() {
        _previewing = false;
        _error = error.message;
      });
    }
  }

  Future<void> _consent() async {
    final String? previewedToken = _previewToken;
    if (previewedToken == null) {
      return;
    }
    setState(() {
      _redeeming = true;
      _error = null;
    });
    try {
      final Assignment assignment = await ref
          .read(apiClientProvider)
          .redeemAssignmentInvite(previewedToken);
      if (!mounted) return;
      _code.clear();
      setState(() {
        _redeeming = false;
        _preview = null;
        _previewToken = null;
        // The redeem response is the committed truth; no follow-up read is needed.
        _assignment = assignment;
      });
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Assignment accepted.')),
      );
    } on ApiException catch (error) {
      if (!mounted) return;
      setState(() {
        _redeeming = false;
        _error = error.message;
      });
    }
  }

  Future<void> _end() async {
    final bool? confirmed = await showDialog<bool>(
      context: context,
      builder: (BuildContext context) => AlertDialog(
        title: const Text('End assignment?'),
        content: const Text(
            'Your coach will immediately lose access to your training history.'),
        actions: <Widget>[
          TextButton(
            onPressed: () => Navigator.of(context).pop(false),
            child: const Text('Cancel'),
          ),
          FilledButton(
            onPressed: () => Navigator.of(context).pop(true),
            child: const Text('End assignment'),
          ),
        ],
      ),
    );
    if (confirmed != true || !mounted) return;
    setState(() {
      _ending = true;
      _error = null;
    });
    try {
      await ref.read(apiClientProvider).endMyAssignment();
      if (!mounted) return;
      setState(() {
        _ending = false;
        _assignment = null;
      });
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Assignment ended.')),
      );
    } on ApiException catch (error) {
      if (!mounted) return;
      setState(() {
        _ending = false;
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

  Widget _activeAssignment(BuildContext context, Assignment assignment) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: <Widget>[
        Text('Your coach', style: Theme.of(context).textTheme.titleLarge),
        const SizedBox(height: 8),
        Card(
          child: ListTile(
            leading: const Icon(Icons.person_outline),
            title: Text(assignment.coach.displayName),
            subtitle: Text(
              assignment.coach.specialization.isEmpty
                  ? 'Coaching assignment active'
                  : assignment.coach.specialization,
            ),
          ),
        ),
        const SizedBox(height: 8),
        const Text(
          'While this assignment is active, your coach can view your current and '
          'historical training data. Ending it revokes that access immediately.',
        ),
        const SizedBox(height: 20),
        OutlinedButton.icon(
          onPressed: _ending ? null : _end,
          icon: const Icon(Icons.link_off),
          label: _ending
              ? const SizedBox(
                  height: 18,
                  width: 18,
                  child: CircularProgressIndicator(strokeWidth: 2),
                )
              : const Text('End assignment'),
        ),
      ],
    );
  }

  Widget _inviteSection(BuildContext context) {
    final AssignmentInvitePreview? preview = _preview;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: <Widget>[
        Text('Coach assignment',
            style: Theme.of(context).textTheme.titleLarge),
        const SizedBox(height: 8),
        const Text(
          'Enter a coach invite code. Your coach can only see your training data '
          'after you accept, and access ends when either of you ends the assignment.',
        ),
        const SizedBox(height: 16),
        TextField(
          key: const Key('assignment_code_field'),
          controller: _code,
          autocorrect: false,
          enableSuggestions: false,
          onChanged: _onCodeChanged,
          decoration: const InputDecoration(
            labelText: 'Invite code',
            border: OutlineInputBorder(),
          ),
        ),
        const SizedBox(height: 12),
        FilledButton(
          onPressed: _previewing || _redeeming ? null : _previewCode,
          child: _previewing
              ? const SizedBox(
                  height: 20,
                  width: 20,
                  child: CircularProgressIndicator(strokeWidth: 2),
                )
              : const Text('Preview access'),
        ),
        if (preview != null) ...<Widget>[
          const Divider(height: 32),
          Text(
            'Your coach will be ${preview.coach.displayName}',
            style: Theme.of(context).textTheme.titleMedium,
          ),
          if (preview.coach.bio.isNotEmpty) ...<Widget>[
            const SizedBox(height: 4),
            Text(preview.coach.bio),
          ],
          const SizedBox(height: 12),
          Text(preview.access.description),
          const SizedBox(height: 16),
          FilledButton.icon(
            onPressed: _redeeming ? null : _consent,
            icon: _redeeming
                ? const SizedBox(
                    height: 18,
                    width: 18,
                    child: CircularProgressIndicator(strokeWidth: 2),
                  )
                : const Icon(Icons.check),
            label: const Text('Accept assignment'),
          ),
        ],
      ],
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
        if (_assignment != null)
          _activeAssignment(context, _assignment!)
        else
          _inviteSection(context),
      ],
    );
  }
}

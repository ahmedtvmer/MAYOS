import 'package:flutter/material.dart';

import '../../../core/display_language/assignment_copy.dart';
import '../../../core/display_language/message_resolver.dart';
import '../../../core/models.dart';
import '../../../core/theme/mayos_theme.dart';
import '../../../core/theme/mayos_typography.dart';
import '../../../core/ui/first_strong_direction.dart';
import '../../../core/ui/mayos_button.dart';
import '../../../core/ui/mayos_card.dart';
import '../../../core/ui/mayos_section_header.dart';
import '../program/program_change_summary_card.dart';

class PlayerNoticeActions {
  const PlayerNoticeActions({
    required this.onMarkAllRead,
    required this.onViewProgram,
    required this.markingRead,
  });

  final VoidCallback onMarkAllRead;
  final VoidCallback onViewProgram;
  final bool markingRead;
}

class PlayerAssignmentNoticesCard extends StatelessWidget {
  const PlayerAssignmentNoticesCard({
    required this.notices,
    required this.copy,
    required this.actions,
    super.key,
  });

  final List<AssignmentNotice> notices;
  final AssignmentCopy copy;
  final PlayerNoticeActions actions;

  @override
  Widget build(BuildContext context) {
    final MayosThemeExtension colors = MayosTheme.of(context);
    final int unread =
        notices.where((AssignmentNotice notice) => notice.isUnread).length;
    return MayosCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          MayosSectionHeader(
            title: copy.notices,
            padding: EdgeInsets.zero,
            trailing: unread == 0
                ? null
                : MayosButton(
                    label: copy.markAllRead,
                    variant: MayosButtonVariant.tertiary,
                    expand: false,
                    loading: actions.markingRead,
                    onPressed:
                        actions.markingRead ? null : actions.onMarkAllRead,
                  ),
          ),
          if (notices.isEmpty)
            Text(
              copy.noNotices,
              style: MayosTypography.of(context)
                  .bodySecondary
                  .copyWith(color: colors.textSecondary),
            )
          else
            for (final AssignmentNotice notice in notices)
              _PlayerNoticeRow(
                notice: notice,
                copy: copy,
                onViewProgram: actions.onViewProgram,
              ),
        ],
      ),
    );
  }
}

class _PlayerNoticeRow extends StatelessWidget {
  const _PlayerNoticeRow({
    required this.notice,
    required this.copy,
    required this.onViewProgram,
  });

  final AssignmentNotice notice;
  final AssignmentCopy copy;
  final VoidCallback onViewProgram;

  @override
  Widget build(BuildContext context) {
    final String message = resolveAssignmentNoticeMessage(
      notice,
      copy.languageCode,
    );
    if (notice.programChangeSummary != null &&
        notice.summaryDismissedAt == null) {
      return Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          ProgramChangeSummaryCard(
            summary: notice.programChangeSummary!,
            message: message,
            onViewProgram: onViewProgram,
          ),
          _PlayerNoticeCaption(notice: notice, copy: copy),
        ],
      );
    }

    final MayosThemeExtension colors = MayosTheme.of(context);
    return ListTile(
      dense: true,
      contentPadding: EdgeInsets.zero,
      leading: Icon(
        notice.isUnread ? Icons.notifications_active : Icons.notifications_none,
        color: notice.isUnread ? colors.accent : colors.textMuted,
      ),
      title: FirstStrongDirection(
        text: message,
        child: Text(message, textAlign: TextAlign.start),
      ),
      subtitle: _PlayerNoticeCaption(notice: notice, copy: copy),
    );
  }
}

class _PlayerNoticeCaption extends StatelessWidget {
  const _PlayerNoticeCaption({required this.notice, required this.copy});

  final AssignmentNotice notice;
  final AssignmentCopy copy;

  @override
  Widget build(BuildContext context) {
    final DateTime? createdAt = DateTime.tryParse(notice.createdAt);
    final String timestamp = createdAt == null
        ? notice.createdAt
        : isoDateOf(createdAt);
    return Text.rich(
      TextSpan(
        children: <InlineSpan>[
          TextSpan(text: '${copy.noticeType(notice.kind)} · '),
          TextSpan(text: '\u2066$timestamp\u2069'),
        ],
      ),
      key: Key('notice_caption_${notice.noticeId}'),
      style: MayosTypography.of(context)
          .caption
          .copyWith(color: MayosTheme.of(context).textMuted),
    );
  }
}

class PlayerAssignmentCheckInsCard extends StatelessWidget {
  const PlayerAssignmentCheckInsCard({
    required this.checkIns,
    required this.copy,
    super.key,
  });

  final List<CheckIn> checkIns;
  final AssignmentCopy copy;

  @override
  Widget build(BuildContext context) {
    final MayosThemeExtension colors = MayosTheme.of(context);
    return MayosCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          MayosSectionHeader(title: copy.checkIns, padding: EdgeInsets.zero),
          if (checkIns.isEmpty)
            Text(
              copy.noCheckIns,
              style: MayosTypography.of(context)
                  .bodySecondary
                  .copyWith(color: colors.textSecondary),
            )
          else
            for (final CheckIn checkIn in checkIns)
              _PlayerCheckInRow(checkIn: checkIn, copy: copy),
        ],
      ),
    );
  }
}

class _PlayerCheckInRow extends StatelessWidget {
  const _PlayerCheckInRow({required this.checkIn, required this.copy});

  final CheckIn checkIn;
  final AssignmentCopy copy;

  @override
  Widget build(BuildContext context) {
    final MayosThemeExtension colors = MayosTheme.of(context);
    final String date = copy.isArabic
        ? '\u2066${checkIn.checkedInOn}\u2069'
        : checkIn.checkedInOn;
    final String subtitle = _checkInSubtitle(checkIn, copy);
    return ListTile(
      dense: true,
      contentPadding: EdgeInsets.zero,
      leading: Icon(Icons.handshake_outlined, color: colors.textSecondary),
      title: Text('$date · ${copy.checkInChannel(checkIn.channel)}'),
      subtitle: subtitle.isEmpty
          ? null
          : FirstStrongDirection(text: subtitle, child: Text(subtitle)),
    );
  }
}

String _checkInSubtitle(CheckIn checkIn, AssignmentCopy copy) => <String>[
      if (checkIn.coachUsername != null)
        checkIn.coachUsername == 'Former coach'
            ? copy.formerCoach
            : copy.coachUsername(checkIn.coachUsername!),
      if (checkIn.assignmentStatus == 'ended') copy.assignmentEndedStatus,
      if (checkIn.note != null && checkIn.note!.isNotEmpty) checkIn.note!,
    ].join(' · ');

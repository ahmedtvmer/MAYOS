import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/display_language/copy_context.dart';
import '../../../core/api_client.dart';
import '../../../core/connectivity_message.dart';
import '../../../core/display_language/catalog.dart';
import '../../../core/display_language/controller.dart';
import '../../../core/models.dart';
import '../../../core/theme/mayos_spacing.dart';
import '../../../core/theme/mayos_theme.dart';
import '../../../core/theme/mayos_typography.dart';
import '../../../core/ui/mayos_card.dart';
import '../../../core/ui/mayos_section_header.dart';
import '../../../providers.dart';

class CheckpointReviewScreen extends ConsumerStatefulWidget {
  const CheckpointReviewScreen({
    super.key,
    required this.checkpoint,
    this.assignmentId,
  });

  final int checkpoint;
  final String? assignmentId;

  @override
  ConsumerState<CheckpointReviewScreen> createState() =>
      _CheckpointReviewScreenState();
}

class _CheckpointReviewScreenState
    extends ConsumerState<CheckpointReviewScreen> {
  late Future<CheckpointReview> _reviewFuture;

  @override
  void initState() {
    super.initState();
    _reviewFuture = _loadReview();
  }

  Future<CheckpointReview> _loadReview() {
    final String? assignmentId = widget.assignmentId;
    if (assignmentId != null) {
      return ref
          .read(apiClientProvider)
          .coachCheckpointReview(assignmentId, widget.checkpoint);
    }
    return ref.read(apiClientProvider).checkpointReview(widget.checkpoint);
  }

  Future<void> _retry() async {
    final Future<CheckpointReview> future = _loadReview();
    setState(() => _replaceReviewFuture(future));
    await future;
  }

  void _replaceReviewFuture(Future<CheckpointReview> future) {
    _reviewFuture = future;
  }

  @override
  Widget build(BuildContext context) {
    ref.listen<String>(displayLanguageProvider, (String? previous, String next) {
      if (previous != null && previous != next) {
        final Future<CheckpointReview> future = _loadReview();
        setState(() => _replaceReviewFuture(future));
      }
    });
    return FutureBuilder<CheckpointReview>(
      future: _reviewFuture,
      builder:
          (BuildContext context, AsyncSnapshot<CheckpointReview> snapshot) {
        if (snapshot.connectionState == ConnectionState.waiting) {
          return const Center(child: CircularProgressIndicator());
        }
        if (!snapshot.hasData) {
          final Object? error = snapshot.error;
          final String message = error is ApiException
              ? displayCopyOf(context).failureMessage(apiFailureMessage(error))
              : displayCopyOf(context).loadCheckpointFailed;
          return Center(
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: <Widget>[
                Text(message),
                const SizedBox(height: MayosSpacing.md),
                OutlinedButton(
                    onPressed: _retry,
                    child: Text(displayCopyOf(context).retry)),
              ],
            ),
          );
        }
        return _ReviewBody(review: snapshot.data!);
      },
    );
  }
}

class _ReviewBody extends StatelessWidget {
  const _ReviewBody({required this.review});

  final CheckpointReview review;

  Widget _heading(
    BuildContext context,
    MayosCopy copy,
    MayosThemeExtension theme,
  ) =>
      Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          Text(
            copy.checkpointReview,
            key: const ValueKey<String>('checkpoint.review.title'),
            style: MayosTypography.of(context).display.copyWith(
              fontSize: 30,
              color: theme.textPrimary,
            ),
          ),
          const SizedBox(height: MayosSpacing.xs),
          Text(
            copy.checkpointAt(review.checkpoint),
            key: const ValueKey<String>('checkpoint.review.checkpoint'),
            style: MayosTypography.of(context)
                .bodySecondary
                .copyWith(color: theme.textSecondary),
          ),
        ],
      );

  Widget _periodCard(
    BuildContext context,
    MayosCopy copy,
    MayosThemeExtension theme,
  ) =>
      MayosCard(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: <Widget>[
            MayosSectionHeader(title: copy.period),
            const SizedBox(height: MayosSpacing.xs),
            Text(
              '${review.periodStart} – ${review.periodEnd}',
              key: const ValueKey<String>('checkpoint.review.period'),
              textDirection: TextDirection.ltr,
              style: MayosTypography.of(context)
                  .bodySecondary
                  .copyWith(color: theme.textSecondary),
            ),
          ],
        ),
      );

  Widget _ratingCard(BuildContext context, MayosCopy copy) => MayosCard(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: <Widget>[
            MayosSectionHeader(title: copy.rating),
            for (int index = 0; index < review.rating.length; index++)
              _ratingRow(copy, index),
          ],
        ),
      );

  Widget _ratingRow(MayosCopy copy, int index) {
    final CheckpointRatingPart rating = review.rating[index];
    return ListTile(
      key: ValueKey<String>('checkpoint.review.rating.$index'),
      contentPadding: EdgeInsets.zero,
      title: Text(copy.checkpointRatingPart(rating.partCode, rating.part)),
      trailing: Text(copy.checkpointRatingLabel(rating.labelCode, rating.label)),
    );
  }

  Widget _reviewTextCard(
    BuildContext context,
    MayosCopy copy,
    MayosThemeExtension theme,
  ) =>
      MayosCard(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: _reviewTextContent(context, copy, theme),
        ),
      );

  List<Widget> _reviewTextContent(
    BuildContext context,
    MayosCopy copy,
    MayosThemeExtension theme,
  ) =>
      <Widget>[
        if (review.textLanguage != null &&
            review.textLanguage != copy.languageCode) ...<Widget>[
          Text(
            copy.originalReviewTextLanguage(review.textLanguage!),
            key: const ValueKey<String>('checkpoint.review.original-language'),
            style: MayosTypography.of(context)
                .bodySecondary
                .copyWith(color: theme.textSecondary),
          ),
          const SizedBox(height: MayosSpacing.sm),
        ],
        Text(
          review.text,
          key: const ValueKey<String>('checkpoint.review.text'),
          style: MayosTypography.of(context)
              .body
              .copyWith(color: theme.textPrimary),
        ),
      ];

  @override
  Widget build(BuildContext context) {
    final MayosThemeExtension theme = MayosTheme.of(context);
    final MayosCopy copy = displayCopyOf(context);
    return ListView(
      padding: MayosSpacing.screen,
      children: <Widget>[
        _heading(context, copy, theme),
        const SizedBox(height: MayosSpacing.lg),
        _periodCard(context, copy, theme),
        const SizedBox(height: MayosSpacing.md),
        _ratingCard(context, copy),
        const SizedBox(height: MayosSpacing.md),
        _reviewTextCard(context, copy, theme),
      ],
    );
  }
}

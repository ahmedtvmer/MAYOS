import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api_client.dart';
import '../../../core/models.dart';
import '../../../core/training_status_projection.dart';
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
    return ref.read(checkpointReviewProvider(widget.checkpoint).future);
  }

  Future<void> _retry() async {
    final Future<CheckpointReview> future = _loadReview();
    setState(() => _reviewFuture = future);
    await future;
  }

  @override
  Widget build(BuildContext context) {
    return FutureBuilder<CheckpointReview>(
      future: _reviewFuture,
      builder: (BuildContext context, AsyncSnapshot<CheckpointReview> snapshot) {
        if (snapshot.connectionState == ConnectionState.waiting) {
          return const Center(child: CircularProgressIndicator());
        }
        if (!snapshot.hasData) {
          final Object? error = snapshot.error;
          final String message = error is ApiException
              ? error.message
              : 'Could not load this Checkpoint review.';
          return Center(
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: <Widget>[
                Text(message),
                const SizedBox(height: MayosSpacing.md),
                OutlinedButton(onPressed: _retry, child: const Text('Retry')),
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

  @override
  Widget build(BuildContext context) {
    final MayosThemeExtension c = MayosTheme.of(context);
    return ListView(
      padding: MayosSpacing.screen,
      children: <Widget>[
        Text(
          'Your ${checkpointOrdinal(review.checkpoint)} workout',
          key: const ValueKey<String>('checkpoint.review.title'),
          style: MayosTypography.display.copyWith(
            fontSize: 30,
            color: c.textPrimary,
          ),
        ),
        const SizedBox(height: MayosSpacing.lg),
        MayosCard(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: <Widget>[
              const MayosSectionHeader(title: 'Period'),
              const SizedBox(height: MayosSpacing.xs),
              Text(
                '${review.periodStart} – ${review.periodEnd}',
                key: const ValueKey<String>('checkpoint.review.period'),
                style: MayosTypography.bodySecondary
                    .copyWith(color: c.textSecondary),
              ),
            ],
          ),
        ),
        const SizedBox(height: MayosSpacing.md),
        MayosCard(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: <Widget>[
              const MayosSectionHeader(title: 'Rating'),
              for (int index = 0; index < review.rating.length; index++)
                ListTile(
                  key: ValueKey<String>('checkpoint.review.rating.$index'),
                  contentPadding: EdgeInsets.zero,
                  title: Text(review.rating[index].part),
                  trailing: Text(review.rating[index].label),
                ),
            ],
          ),
        ),
        const SizedBox(height: MayosSpacing.md),
        MayosCard(
          child: Text(
            review.text,
            key: const ValueKey<String>('checkpoint.review.text'),
            style: MayosTypography.body.copyWith(color: c.textPrimary),
          ),
        ),
      ],
    );
  }
}

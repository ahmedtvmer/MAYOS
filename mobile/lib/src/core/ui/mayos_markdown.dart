import 'package:flutter/material.dart';
import 'package:flutter_markdown_plus/flutter_markdown_plus.dart';

import '../theme/mayos_spacing.dart';
import '../theme/mayos_theme.dart';
import '../theme/mayos_typography.dart';

/// Selectable Markdown text styled with MAYOS roles and theme tokens.
///
/// A non-scrolling body stays inside the chat list, and no animation keeps
/// streamed updates and loaded history on the same rendering path.
class MayosMarkdown extends StatelessWidget {
  const MayosMarkdown({
    super.key,
    required this.source,
    this.bodyStyle = MayosTypography.body,
  });

  final String source;
  final TextStyle bodyStyle;

  @override
  Widget build(BuildContext context) {
    final MayosThemeExtension colors = MayosTheme.of(context);
    final TextStyle body = bodyStyle.copyWith(color: colors.textPrimary);
    final TextStyle code = MayosTypography.numericSmall.copyWith(
      fontFamily: 'monospace',
      fontSize: 13,
      color: colors.textPrimary,
      backgroundColor: colors.surfaceSunken,
    );
    final styleSheet = MarkdownStyleSheet.fromTheme(Theme.of(context)).copyWith(
      p: body,
      pPadding: EdgeInsets.zero,
      h1: MayosTypography.pageHeading.copyWith(color: colors.textPrimary),
      h1Padding: const EdgeInsets.only(
        top: MayosSpacing.xs,
        bottom: MayosSpacing.xs,
      ),
      h2: MayosTypography.sectionHeading.copyWith(color: colors.textPrimary),
      h2Padding: const EdgeInsets.only(
        top: MayosSpacing.xs,
        bottom: MayosSpacing.xxs,
      ),
      h3: MayosTypography.sectionHeading.copyWith(color: colors.textPrimary),
      h3Padding: const EdgeInsets.only(
        top: MayosSpacing.xs,
        bottom: MayosSpacing.xxs,
      ),
      h4: MayosTypography.exerciseTitle.copyWith(color: colors.textPrimary),
      h4Padding: const EdgeInsets.only(
        top: MayosSpacing.xs,
        bottom: MayosSpacing.xxs,
      ),
      h5: MayosTypography.exerciseTitle.copyWith(color: colors.textPrimary),
      h5Padding: const EdgeInsets.only(
        top: MayosSpacing.xs,
        bottom: MayosSpacing.xxs,
      ),
      h6: MayosTypography.exerciseTitle.copyWith(color: colors.textPrimary),
      h6Padding: const EdgeInsets.only(
        top: MayosSpacing.xs,
        bottom: MayosSpacing.xxs,
      ),
      em: body.copyWith(fontStyle: FontStyle.italic),
      strong: MayosTypography.captionStrong.copyWith(
        fontSize: body.fontSize,
        height: body.height,
        letterSpacing: body.letterSpacing,
        color: colors.textPrimary,
      ),
      code: code,
      blockquote: body.copyWith(color: colors.textSecondary),
      blockquotePadding: const EdgeInsets.symmetric(
        horizontal: MayosSpacing.sm,
        vertical: MayosSpacing.xs,
      ),
      blockquoteDecoration: BoxDecoration(
        color: colors.surfaceSunken,
        border: Border(left: BorderSide(color: colors.borderStrong, width: 3)),
        borderRadius: MayosRadii.smallRadius,
      ),
      codeblockPadding: const EdgeInsets.all(MayosSpacing.sm),
      codeblockDecoration: BoxDecoration(
        color: colors.surfaceSunken,
        border: Border.all(color: colors.border),
        borderRadius: MayosRadii.smallRadius,
      ),
      a: body.copyWith(decoration: TextDecoration.none),
      img: body.copyWith(color: colors.textMuted),
      listBullet: body,
      listIndent: MayosSpacing.lg,
      blockSpacing: MayosSpacing.sm,
    );

    return MarkdownBody(
      key: key,
      data: source,
      selectable: true,
      softLineBreak: true,
      styleSheet: styleSheet,
      // Image nodes are reduced to alt text; never resolve a network, file, or
      // asset URI from assistant-controlled Markdown.
      imageBuilder: (Uri uri, String? title, String? alt) {
        final String label = alt?.trim().isNotEmpty == true
            ? alt!.trim()
            : 'Image omitted';
        return Text(label, style: styleSheet.img);
      },
      // No onTapLink is provided because the app has no general link handler.
      // Keep the anchor text as ordinary, noninteractive text.
    );
  }
}

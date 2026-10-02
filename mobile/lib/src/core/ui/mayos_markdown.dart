import 'package:flutter/material.dart';
import 'package:flutter_markdown_plus/flutter_markdown_plus.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../external_url_launcher.dart';
import '../display_language/copy_context.dart';
import 'first_strong_direction.dart';
import '../theme/mayos_spacing.dart';
import '../theme/mayos_theme.dart';
import '../theme/mayos_typography.dart';

final RegExp _fenceMarker = RegExp(r'^ {0,3}(`{3,}|~{3,})');
final RegExp _htmlBlockStart = RegExp(r'^ {0,3}<(?:[A-Za-z]|[!?/])');
// The Markdown package drops block-HTML nodes; escape the opener so their text
// remains visible without turning it into markup.
String _escapeBlockHtml(String source) {
  String? fence;
  return source.split('\n').map((String line) {
    final RegExpMatch? marker = _fenceMarker.firstMatch(line);
    if (marker != null) {
      final String delimiter = marker.group(1)!;
      if (fence == null) {
        fence = delimiter;
      } else if (delimiter[0] == fence![0] &&
          delimiter.length >= fence!.length &&
          line.substring(marker.end).trim().isEmpty) {
        fence = null;
      }
      return line;
    }
    if (fence == null && _htmlBlockStart.hasMatch(line)) {
      return line.replaceFirst('<', '&lt;');
    }
    return line;
  }).join('\n');
}

/// Selectable Markdown text styled with MAYOS roles and theme tokens.
///
/// A non-scrolling body stays inside the chat list, and no animation keeps
/// streamed updates and loaded history on the same rendering path.
class MayosMarkdown extends ConsumerWidget {
  const MayosMarkdown({
    super.key,
    required this.source,
    this.bodyStyle = MayosTypography.body,
  });

  final String source;
  final TextStyle bodyStyle;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final MayosThemeExtension colors = MayosTheme.of(context);
    final TextStyle body = bodyStyle.copyWith(color: colors.textPrimary);
    final TextStyle code = MayosTypography.code.copyWith(
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
        border: BorderDirectional(
          start: BorderSide(
            color: colors.borderStrong,
            width: MayosBorderWidths.emphasis,
          ),
        ),
        borderRadius: MayosRadii.smallRadius,
      ),
      codeblockPadding: const EdgeInsets.all(MayosSpacing.sm),
      codeblockDecoration: BoxDecoration(
        color: colors.surfaceSunken,
        border: Border.all(color: colors.border),
        borderRadius: MayosRadii.smallRadius,
      ),
      a: body.copyWith(
        color: colors.accent,
        decoration: TextDecoration.underline,
      ),
      img: body.copyWith(color: colors.textMuted),
      listBullet: body,
      listIndent: MayosSpacing.lg,
      blockSpacing: MayosSpacing.sm,
      // Intrinsic columns activate the package's bounded horizontal table
      // scroller, avoiding narrow-chat overflow for GFM tables.
      tableColumnWidth: const IntrinsicColumnWidth(),
    );

    return MarkdownBody(
      data: _escapeBlockHtml(source),
      selectable: true,
      softLineBreak: true,
      styleSheet: styleSheet,
      textDirectionBuilder: (String text, String blockTag) => blockTag == 'pre'
          ? TextDirection.ltr
          : firstStrongTextDirection(text),
      onTapLink: (String text, String? href, String title) {
        final Uri? uri = href == null ? null : Uri.tryParse(href);
        if (uri == null ||
            !uri.hasAuthority ||
            uri.host.isEmpty ||
            (uri.scheme != 'http' && uri.scheme != 'https')) {
          return;
        }
        _launchLink(context, ref, uri);
      },
      // Image nodes are reduced to alt text; never resolve a network, file, or
      // asset URI from assistant-controlled Markdown.
      imageBuilder: (Uri uri, String? title, String? alt) {
        final String label = alt?.trim().isNotEmpty == true
            ? alt!.trim()
            : displayCopyOf(context).omittedImage;
        return Text(label, style: styleSheet.img);
      },
    );
  }

  Future<void> _launchLink(BuildContext context, WidgetRef ref, Uri uri) async {
    final bool opened =
        await ref.read(externalUrlLauncherProvider)(uri.toString());
    if (!opened && context.mounted) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text(displayCopyOf(context).unavailableLink)),
      );
    }
  }
}

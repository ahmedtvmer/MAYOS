import 'package:flutter/foundation.dart' show listEquals;
import 'package:flutter/material.dart';

import '../theme/mayos_spacing.dart';
import '../theme/mayos_theme.dart';
import '../theme/mayos_typography.dart';

/// Column widths shared by table headers, rows, and responsive card tables.
class MayosTableColumns {
  const MayosTableColumns(this.widths, this.flexibleIndex);

  final List<double> widths;
  final int flexibleIndex;
}

/// The shared desktop table frame, including its horizontal scrolling and widths.
class MayosTableFrame extends StatelessWidget {
  const MayosTableFrame({
    super.key,
    required this.columns,
    required this.child,
    this.decorated = true,
    this.scrollable = true,
  });

  final MayosTableColumns columns;
  final Widget child;
  final bool decorated;
  final bool scrollable;

  @override
  Widget build(BuildContext context) {
    assert(columns.flexibleIndex >= 0 &&
        columns.flexibleIndex < columns.widths.length);
    final double minimumWidth = columns.widths.fold<double>(
          0,
          (double total, double width) => total + width,
        ) +
        MayosSpacing.xs * 2 +
        (decorated ? 2 : 0);
    return LayoutBuilder(
      builder: (BuildContext context, BoxConstraints constraints) {
        final double viewportWidth = constraints.hasBoundedWidth
            ? constraints.maxWidth
            : minimumWidth;
        final double tableWidth =
            viewportWidth < minimumWidth ? minimumWidth : viewportWidth;
        final List<double> resolvedWidths = List<double>.of(columns.widths);
        resolvedWidths[columns.flexibleIndex] += tableWidth - minimumWidth;
        final Widget table = Container(
          width: tableWidth,
          clipBehavior: decorated ? Clip.antiAlias : Clip.none,
          decoration: decorated
              ? BoxDecoration(
                  border: Border.all(color: MayosTheme.of(context).border),
                  borderRadius: MayosRadii.largeRadius,
                )
              : null,
          child: decorated
              ? Material(
                  type: MaterialType.transparency,
                  child: MayosTableLayout(
                    widths: resolvedWidths,
                    child: child,
                  ),
                )
              : MayosTableLayout(widths: resolvedWidths, child: child),
        );
        if (!scrollable) return table;
        return SizedBox(
          width: viewportWidth,
          child: SingleChildScrollView(
            scrollDirection: Axis.horizontal,
            child: table,
          ),
        );
      },
    );
  }
}

/// Supplies the resolved desktop widths to table headers and data rows.
class MayosTableLayout extends InheritedWidget {
  const MayosTableLayout({
    super.key,
    required this.widths,
    required super.child,
  });

  final List<double> widths;

  static List<double> widthsOf(BuildContext context) {
    final MayosTableLayout? layout =
        context.dependOnInheritedWidgetOfExactType<MayosTableLayout>();
    assert(layout != null, 'Table cells must be inside a MayosTableFrame.');
    return layout!.widths;
  }

  @override
  bool updateShouldNotify(MayosTableLayout oldWidget) =>
      !listEquals(widths, oldWidget.widths);
}

/// Header cells aligned to the widths supplied by [MayosTableFrame].
class MayosTableHeader extends StatelessWidget {
  const MayosTableHeader({
    super.key,
    required this.labels,
    required this.alignments,
  }) : assert(labels.length == alignments.length);

  final List<String> labels;
  final List<TextAlign> alignments;

  @override
  Widget build(BuildContext context) {
    final MayosThemeExtension colors = MayosTheme.of(context);
    final List<double> widths = MayosTableLayout.widthsOf(context);
    assert(labels.length == widths.length);
    return Container(
      padding: const EdgeInsets.symmetric(
        horizontal: MayosSpacing.xs,
        vertical: MayosSpacing.xs,
      ),
      decoration: BoxDecoration(
        color: colors.tableHeader,
        border: Border(bottom: BorderSide(color: colors.border)),
      ),
      child: Row(
        children: <Widget>[
          for (int index = 0; index < labels.length; index++)
            SizedBox(
              width: widths[index],
              child: Text(
                labels[index],
                textAlign: alignments[index],
                style: MayosTypography.of(context)
                    .captionStrong
                    .copyWith(color: colors.textMuted),
              ),
            ),
        ],
      ),
    );
  }
}

/// A data row aligned to the widths supplied by [MayosTableFrame].
class MayosTableRow extends StatelessWidget {
  const MayosTableRow({
    super.key,
    required this.cells,
  });

  final List<Widget> cells;

  @override
  Widget build(BuildContext context) {
    final MayosThemeExtension colors = MayosTheme.of(context);
    final List<double> widths = MayosTableLayout.widthsOf(context);
    assert(cells.length == widths.length);
    return Container(
      padding: const EdgeInsets.symmetric(
        horizontal: MayosSpacing.xs,
        vertical: MayosSpacing.xxs,
      ),
      decoration: BoxDecoration(
        border: Border(bottom: BorderSide(color: colors.border)),
      ),
      child: Row(
        children: <Widget>[
          for (int index = 0; index < cells.length; index++)
            SizedBox(width: widths[index], child: cells[index]),
        ],
      ),
    );
  }
}

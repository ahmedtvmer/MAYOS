import 'package:flutter/foundation.dart' show listEquals;
import 'package:flutter/material.dart';

import '../theme/myos_spacing.dart';
import '../theme/myos_theme.dart';
import '../theme/myos_typography.dart';

/// Column widths shared by table headers, rows, and responsive card tables.
class MyosTableColumns {
  const MyosTableColumns(this.widths, this.flexibleIndex);

  final List<double> widths;
  final int flexibleIndex;
}

/// The shared desktop table frame, including its horizontal scrolling and widths.
class MyosTableFrame extends StatelessWidget {
  const MyosTableFrame({
    super.key,
    required this.columns,
    required this.child,
    this.decorated = true,
    this.scrollable = true,
  });

  final MyosTableColumns columns;
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
        MyosSpacing.xs * 2 +
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
                  border: Border.all(color: MyosTheme.of(context).border),
                  borderRadius: MyosRadii.largeRadius,
                )
              : null,
          child: decorated
              ? Material(
                  type: MaterialType.transparency,
                  child: MyosTableLayout(
                    widths: resolvedWidths,
                    child: child,
                  ),
                )
              : MyosTableLayout(widths: resolvedWidths, child: child),
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
class MyosTableLayout extends InheritedWidget {
  const MyosTableLayout({
    super.key,
    required this.widths,
    required super.child,
  });

  final List<double> widths;

  static List<double> widthsOf(BuildContext context) {
    final MyosTableLayout? layout =
        context.dependOnInheritedWidgetOfExactType<MyosTableLayout>();
    assert(layout != null, 'Table cells must be inside a MyosTableFrame.');
    return layout!.widths;
  }

  @override
  bool updateShouldNotify(MyosTableLayout oldWidget) =>
      !listEquals(widths, oldWidget.widths);
}

/// Header cells aligned to the widths supplied by [MyosTableFrame].
class MyosTableHeader extends StatelessWidget {
  const MyosTableHeader({
    super.key,
    required this.labels,
    required this.alignments,
  }) : assert(labels.length == alignments.length);

  final List<String> labels;
  final List<TextAlign> alignments;

  @override
  Widget build(BuildContext context) {
    final MyosThemeExtension colors = MyosTheme.of(context);
    final List<double> widths = MyosTableLayout.widthsOf(context);
    assert(labels.length == widths.length);
    return Container(
      padding: const EdgeInsets.symmetric(
        horizontal: MyosSpacing.xs,
        vertical: MyosSpacing.xs,
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
                style: MyosTypography.of(context)
                    .captionStrong
                    .copyWith(color: colors.textMuted),
              ),
            ),
        ],
      ),
    );
  }
}

/// A data row aligned to the widths supplied by [MyosTableFrame].
class MyosTableRow extends StatelessWidget {
  const MyosTableRow({
    super.key,
    required this.cells,
  });

  final List<Widget> cells;

  @override
  Widget build(BuildContext context) {
    final MyosThemeExtension colors = MyosTheme.of(context);
    final List<double> widths = MyosTableLayout.widthsOf(context);
    assert(cells.length == widths.length);
    return Container(
      padding: const EdgeInsets.symmetric(
        horizontal: MyosSpacing.xs,
        vertical: MyosSpacing.xxs,
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

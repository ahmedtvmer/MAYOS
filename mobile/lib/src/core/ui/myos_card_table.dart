import 'package:flutter/material.dart';

import '../theme/myos_spacing.dart';
import '../theme/myos_theme.dart';
import '../theme/myos_typography.dart';
import 'is_desktop_layout.dart';
import 'myos_card.dart';
import 'myos_table_frame.dart';

/// Uses the same column labels and cells for desktop tables and phone cards.
class MyosCardTable extends StatelessWidget {
  const MyosCardTable({
    super.key,
    required this.columns,
    this.tableColumns,
    this.headerAlignments,
    this.rows = const <MyosCardTableRow>[],
    this.sections = const <MyosCardTableSection>[],
    this.desktopTable,
  });

  final List<String> columns;
  final MyosTableColumns? tableColumns;
  final List<TextAlign>? headerAlignments;
  final List<MyosCardTableRow> rows;
  final List<MyosCardTableSection> sections;

  /// Desktop rendering for list-shaped surfaces such as the roster, whose
  /// desktop layout is a list rather than a column table.
  final Widget? desktopTable;

  @override
  Widget build(BuildContext context) {
    assert(headerAlignments == null ||
        headerAlignments!.length == columns.length);
    if (isDesktopLayout(context)) {
      if (desktopTable != null) return desktopTable!;
      assert(tableColumns != null);
      assert(columns.length == tableColumns!.widths.length);
      assert(tableColumns!.flexibleIndex >= 0 &&
          tableColumns!.flexibleIndex < columns.length);
      return _desktop(context);
    }
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: <Widget>[
        for (final MyosCardTableSection section in sections) ...<Widget>[
          if (section.heading != null) ...<Widget>[
            if (sections.first != section)
              const SizedBox(height: MyosSpacing.lg),
            Text(
              section.heading!,
              style: MyosTypography.of(context)
                  .sectionHeading
                  .copyWith(color: MyosTheme.of(context).textPrimary),
            ),
            const SizedBox(height: MyosSpacing.sm),
          ],
          for (int index = 0; index < section.rows.length; index++) ...<Widget>[
            if (index > 0) const SizedBox(height: MyosSpacing.sm),
            _MyosCardTableCard(columns: columns, row: section.rows[index]),
          ],
        ],
        for (int index = 0; index < rows.length; index++) ...<Widget>[
          if (index > 0) const SizedBox(height: MyosSpacing.sm),
          _MyosCardTableCard(columns: columns, row: rows[index]),
        ],
      ],
    );
  }

  Widget _desktop(BuildContext context) {
    return MyosTableFrame(
      columns: tableColumns!,
      child: Column(
        children: <Widget>[
          MyosTableHeader(
            labels: columns,
            alignments: headerAlignments ??
                List<TextAlign>.filled(columns.length, TextAlign.start),
          ),
          for (final MyosCardTableSection section in sections) ...<Widget>[
            if (section.heading != null)
              Padding(
                padding: const EdgeInsetsDirectional.fromSTEB(
                  MyosSpacing.xs,
                  MyosSpacing.sm,
                  MyosSpacing.xs,
                  MyosSpacing.xs,
                ),
                child: Align(
                  alignment: AlignmentDirectional.centerStart,
                  child: Text(
                    section.heading!,
                    style: MyosTypography.of(context).sectionHeading.copyWith(
                      color: MyosTheme.of(context).textPrimary,
                    ),
                  ),
                ),
              ),
            for (int index = 0; index < section.rows.length; index++) ...<Widget>[
              _desktopRow(section.rows[index]),
            ],
          ],
          for (int index = 0; index < rows.length; index++) ...<Widget>[
            _desktopRow(rows[index]),
          ],
        ],
      ),
    );
  }

  Widget _desktopRow(MyosCardTableRow row) => MyosTableRow(
        cells: row.cells
            .map((Widget? cell) => cell ?? const SizedBox.shrink())
            .toList(growable: false),
      );
}

class MyosCardTableSection {
  const MyosCardTableSection({this.heading, required this.rows});

  final String? heading;
  final List<MyosCardTableRow> rows;
}

class MyosCardTableRow {
  const MyosCardTableRow({
    this.key,
    required this.cells,
    this.titleLeading,
    this.subtitle,
    this.onTap,
    this.actions,
  });

  final Key? key;
  final List<Widget?> cells;
  final Widget? titleLeading;
  final Widget? subtitle;
  final VoidCallback? onTap;
  final Widget? actions;
}

class _MyosCardTableCard extends StatelessWidget {
  const _MyosCardTableCard({required this.columns, required this.row});

  final List<String> columns;
  final MyosCardTableRow row;

  @override
  Widget build(BuildContext context) {
    assert(row.cells.length == columns.length);
    final MyosThemeExtension colors = MyosTheme.of(context);
    return MyosCard(
      key: row.key,
      onTap: row.onTap,
      padding: const EdgeInsets.all(MyosSpacing.md),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: <Widget>[
          Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: <Widget>[
              if (row.titleLeading != null) ...<Widget>[
                row.titleLeading!,
                const SizedBox(width: MyosSpacing.xs),
              ],
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: <Widget>[
                    row.cells.first ?? const SizedBox.shrink(),
                    if (row.subtitle != null) ...<Widget>[
                      const SizedBox(height: MyosSpacing.xxs),
                      row.subtitle!,
                    ],
                  ],
                ),
              ),
            ],
          ),
          for (int index = 1; index < columns.length; index++)
            if (row.cells[index] != null)
              Padding(
                padding: const EdgeInsets.only(top: MyosSpacing.sm),
                child: Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: <Widget>[
                    Flexible(
                      flex: 4,
                      child: Text(
                        columns[index],
                        textAlign: TextAlign.start,
                        style: Theme.of(context).textTheme.bodySmall?.copyWith(
                          color: colors.textSecondary,
                        ),
                      ),
                    ),
                    const SizedBox(width: MyosSpacing.sm),
                    Expanded(flex: 6, child: row.cells[index]!),
                  ],
                ),
              ),
          if (row.actions != null)
            Align(
              alignment: AlignmentDirectional.centerEnd,
              child: row.actions!,
            ),
        ],
      ),
    );
  }
}

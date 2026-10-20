import 'package:flutter/material.dart';

import '../theme/mayos_spacing.dart';
import '../theme/mayos_theme.dart';
import '../theme/mayos_typography.dart';
import 'is_desktop_layout.dart';
import 'mayos_card.dart';
import 'mayos_table_frame.dart';

/// Uses the same column labels and cells for desktop tables and phone cards.
class MayosCardTable extends StatelessWidget {
  const MayosCardTable({
    super.key,
    required this.columns,
    this.tableColumns,
    this.headerAlignments,
    this.rows = const <MayosCardTableRow>[],
    this.sections = const <MayosCardTableSection>[],
    this.desktopTable,
  });

  final List<String> columns;
  final MayosTableColumns? tableColumns;
  final List<TextAlign>? headerAlignments;
  final List<MayosCardTableRow> rows;
  final List<MayosCardTableSection> sections;

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
        for (final MayosCardTableSection section in sections) ...<Widget>[
          if (section.heading != null) ...<Widget>[
            if (sections.first != section)
              const SizedBox(height: MayosSpacing.lg),
            Text(
              section.heading!,
              style: MayosTypography.of(context)
                  .sectionHeading
                  .copyWith(color: MayosTheme.of(context).textPrimary),
            ),
            const SizedBox(height: MayosSpacing.sm),
          ],
          for (int index = 0; index < section.rows.length; index++) ...<Widget>[
            if (index > 0) const SizedBox(height: MayosSpacing.sm),
            _MayosCardTableCard(columns: columns, row: section.rows[index]),
          ],
        ],
        for (int index = 0; index < rows.length; index++) ...<Widget>[
          if (index > 0) const SizedBox(height: MayosSpacing.sm),
          _MayosCardTableCard(columns: columns, row: rows[index]),
        ],
      ],
    );
  }

  Widget _desktop(BuildContext context) {
    return MayosTableFrame(
      columns: tableColumns!,
      child: Column(
        children: <Widget>[
          MayosTableHeader(
            labels: columns,
            alignments: headerAlignments ??
                List<TextAlign>.filled(columns.length, TextAlign.start),
          ),
          for (final MayosCardTableSection section in sections) ...<Widget>[
            if (section.heading != null)
              Padding(
                padding: const EdgeInsetsDirectional.fromSTEB(
                  MayosSpacing.xs,
                  MayosSpacing.sm,
                  MayosSpacing.xs,
                  MayosSpacing.xs,
                ),
                child: Align(
                  alignment: AlignmentDirectional.centerStart,
                  child: Text(
                    section.heading!,
                    style: MayosTypography.of(context).sectionHeading.copyWith(
                      color: MayosTheme.of(context).textPrimary,
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

  Widget _desktopRow(MayosCardTableRow row) => MayosTableRow(
        cells: row.cells
            .map((Widget? cell) => cell ?? const SizedBox.shrink())
            .toList(growable: false),
      );
}

class MayosCardTableSection {
  const MayosCardTableSection({this.heading, required this.rows});

  final String? heading;
  final List<MayosCardTableRow> rows;
}

class MayosCardTableRow {
  const MayosCardTableRow({
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

class _MayosCardTableCard extends StatelessWidget {
  const _MayosCardTableCard({required this.columns, required this.row});

  final List<String> columns;
  final MayosCardTableRow row;

  @override
  Widget build(BuildContext context) {
    assert(row.cells.length == columns.length);
    final MayosThemeExtension colors = MayosTheme.of(context);
    return MayosCard(
      key: row.key,
      onTap: row.onTap,
      padding: const EdgeInsets.all(MayosSpacing.md),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: <Widget>[
          Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: <Widget>[
              if (row.titleLeading != null) ...<Widget>[
                row.titleLeading!,
                const SizedBox(width: MayosSpacing.xs),
              ],
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: <Widget>[
                    row.cells.first ?? const SizedBox.shrink(),
                    if (row.subtitle != null) ...<Widget>[
                      const SizedBox(height: MayosSpacing.xxs),
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
                padding: const EdgeInsets.only(top: MayosSpacing.sm),
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
                    const SizedBox(width: MayosSpacing.sm),
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

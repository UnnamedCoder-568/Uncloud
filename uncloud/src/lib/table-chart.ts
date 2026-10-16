import type { Block, Inline } from './markdown';

export type MarkdownTable = Extract<Block, { kind: 'table' }>;
export type TableSeries = { column: number; label: string; values: number[] };

export function inlineText(nodes: Inline[]): string {
  return nodes.map(node => 'children' in node ? inlineText(node.children) : node.text).join('');
}

/** Only literal numbers form a series. Never invent scores from prose or
 *  evaluate model-written code to turn an answer into a chart. */
export function tableSeries(table: MarkdownTable, allowSingle = false): TableSeries[] {
  if (table.rows.length < (allowSingle ? 1 : 2) || table.rows.length > 40
    || table.rows.some(row => !inlineText(row[0] ?? []).trim())) return [];
  return table.head.slice(1).flatMap((head, offset) => {
    const column = offset + 1;
    const cells = table.rows.map(row => inlineText(row[column] ?? []).trim());
    const units = cells.map(cell => cell.endsWith('%'));
    if (units.some(unit => unit !== units[0])) return [];
    const values = cells.map(cell => {
      const number = cell.replace(/%$/, '');
      if (!/^[+-]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?(?:e[+-]?\d+)?$/i.test(number)) return NaN;
      return Number(number.replaceAll(',', ''));
    });
    if (values.some(value => !Number.isFinite(value) || Math.abs(value) > 1e100)) return [];
    return [{ column, label: inlineText(head) || `Column ${column + 1}`, values }];
  });
}

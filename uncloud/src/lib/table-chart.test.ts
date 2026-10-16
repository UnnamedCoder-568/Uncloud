import { describe, expect, it } from 'vitest';
import { parseBlocks } from './markdown';
import { tableSeries, type MarkdownTable } from './table-chart';

function table(text: string) { return parseBlocks(text)[0] as MarkdownTable; }

describe('numeric table charts', () => {
  it('reads exact numeric columns, including negatives, percent and thousands separators', () => {
    const series = tableSeries(table('| Model | Score | Change | Count |\n|---|---|---|---|\n| A | **90%** | -2 | 1,200 |\n| B | 85% | 0 | 1,000 |'));
    expect(series.map(item => item.values)).toEqual([[90, 85], [-2, 0], [1200, 1000]]);
  });

  it('does not assign numbers to prose, missing values or mixed units', () => {
    expect(tableSeries(table('| Model | Score |\n|---|---|\n| A | High |\n| B | Medium |'))).toEqual([]);
    expect(tableSeries(table('| Model | Score |\n|---|---|\n| A | 90% |\n| B | 85 |'))).toEqual([]);
    expect(tableSeries(table('| Model | Score |\n|---|---|\n| A | 90 |\n| B | |'))).toEqual([]);
  });
});

import { describe, expect, it } from 'vitest';
import { chartReply, parseBarChart } from './bar-chart';

describe('local chart data validation', () => {
  it('accepts paired labels and finite values, including zero and negatives', () => {
    const chart = { title: 'Sample data', labels: ['A', 'B'], values: [-2, 0] };
    expect(parseBarChart(JSON.stringify(chart))).toEqual(chart);
    expect(chartReply('Result.', [chart])).toContain('```bar-chart\n');
  });
  it.each([
    '{"labels":["A"],"values":[1,2]}',
    '{"labels":["A"],"values":["9"]}',
    '{"labels":["A"],"values":[1e999]}',
    '{"labels":["A"],"values":[1],"script":"alert(1)"}',
    '{"labels":[],"values":[]}',
  ])('rejects invalid or executable-looking data: %s', value => {
    expect(parseBarChart(value)).toBeNull();
  });
});

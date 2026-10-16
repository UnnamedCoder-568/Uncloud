export interface BarChartData { title?: string; labels: string[]; values: number[] }
type ChartError = { code: string; fields?: string[] };
type ChartResult = { chart: BarChartData; error?: never } | { chart?: never; error: ChartError };

/** Data only: no HTML, URLs, expressions, imports or executable source. */
export function readBarChart(text: string): ChartResult {
  try {
    const value = JSON.parse(text);
    if (!value || typeof value !== 'object' || Array.isArray(value)) return { error: { code: 'object_required' } };
    const extra = Object.keys(value).filter(key => !['title', 'labels', 'values'].includes(key));
    if (extra.length) return { error: { code: 'additional_properties', fields: extra } };
    if (value.title !== undefined && (typeof value.title !== 'string' || value.title.length > 120)) {
      return { error: { code: 'schema_validation', fields: ['title'] } };
    }
    if (!Array.isArray(value.labels) || value.labels.length < 1 || value.labels.length > 40
      || value.labels.some((label: unknown) => typeof label !== 'string' || !label.trim() || label.length > 120)) {
      return { error: { code: 'schema_validation', fields: ['labels'] } };
    }
    if (!Array.isArray(value.values)
      || value.values.some((number: unknown) => typeof number !== 'number' || !Number.isFinite(number) || Math.abs(number) > 1e100)) {
      return { error: { code: 'schema_validation', fields: ['values'] } };
    }
    if (value.labels.length !== value.values.length) return { error: { code: 'array_length_mismatch', fields: ['labels', 'values'] } };
    return { chart: value };
  } catch { return { error: { code: 'invalid_json' } }; }
}

export function parseBarChart(text: string): BarChartData | null {
  return readBarChart(text).chart ?? null;
}

export function chartReply(text: string, charts: BarChartData[]): string {
  return [text, ...charts.map(chart => `\`\`\`bar-chart\n${JSON.stringify(chart)}\n\`\`\``)].filter(Boolean).join('\n\n');
}

import { useState, type ReactNode } from 'react';
import { BarChart3, Table2 } from 'lucide-react';
import { inlineText, tableSeries, type MarkdownTable } from '../lib/table-chart';

const COLORS = ['#6ba5f7', '#e9a65d', '#85c6a5', '#c396e7', '#e78399', '#6fc5d1'];

/** A local view of the answer's table; it adds no model prompt or tool call. */
export default function TableChart({ table, children, initialChart = false }: { table: MarkdownTable; children: ReactNode; initialChart?: boolean }) {
  const [chart, setChart] = useState(initialChart);
  const [column, setColumn] = useState<number | null>(null);
  const series = tableSeries(table, initialChart);
  if (!series.length) return <>{children}</>;
  const selected = series.find(item => item.column === column) ?? series[0];
  const min = Math.min(0, ...selected.values);
  const max = Math.max(0, ...selected.values);
  const range = max - min || 1;
  const x = (value: number) => 190 + (value - min) / range * 320;
  const zero = x(0);

  return <div className="md-table-artifact">
    <div className="md-table-toolbar">
      <button className="md-copy" aria-label={chart ? 'Show table' : 'Show bar chart'}
        aria-pressed={chart} onClick={() => setChart(value => !value)}>
        {chart ? <Table2 size={14} /> : <BarChart3 size={14} />}
        {chart ? 'Table' : 'Bar chart'}
      </button>
      {chart && series.length > 1 && <select className="md-chart-metric" aria-label="Chart metric"
        value={selected.column} onChange={event => setColumn(Number(event.target.value))}>
        {series.map(item => <option key={item.column} value={item.column}>{item.label}</option>)}
      </select>}
    </div>
    {chart ? <div className="md-chart-wrap">
      <svg className="md-chart" viewBox={`0 0 600 ${56 + table.rows.length * 36}`}
        role="img" aria-label={`${selected.label} by ${inlineText(table.head[0])}`}>
        <title>{selected.label} by {inlineText(table.head[0])}</title>
        <text x="16" y="24" fill="currentColor" fontSize="14" fontWeight="600">{selected.label}</text>
        <line x1={zero} x2={zero} y1="36" y2={40 + table.rows.length * 36}
          stroke="currentColor" opacity=".25" />
        {table.rows.map((row, index) => {
          const label = inlineText(row[0]);
          const value = selected.values[index];
          const y = 44 + index * 36;
          return <g key={index}>
            <title>{label}: {inlineText(row[selected.column])}</title>
            <text x="178" y={y + 17} textAnchor="end" fill="currentColor" fontSize="13">
              {label.length > 22 ? `${label.slice(0, 21)}…` : label}
            </text>
            <rect x={Math.min(zero, x(value))} y={y} width={Math.abs(x(value) - zero)} height="24"
              rx="3" fill={COLORS[index % COLORS.length]} />
            <text x="526" y={y + 17} fill="currentColor" fontSize="13">
              {inlineText(row[selected.column])}
            </text>
          </g>;
        })}
      </svg>
    </div> : children}
  </div>;
}

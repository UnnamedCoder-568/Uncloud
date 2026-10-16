import type { BarChartData } from '../lib/bar-chart';
import type { Inline } from '../lib/markdown';
import TableChart from './TableChart';

export default function BarChartBlock({ chart }: { chart: BarChartData }) {
  const text = (value: string): Inline[] => [{ kind: 'text', text: value }];
  const title = chart.title || 'Value';
  const rows = chart.labels.map((label, index) => [text(label), text(String(chart.values[index]))]);
  return <TableChart initialChart table={{ kind: 'table', head: [text('Item'), text(title)], rows, align: ['left', 'right'] }}>
    <div className="md-table-wrap"><table className="md-table">
      <thead><tr><th>Item</th><th>{title}</th></tr></thead>
      <tbody>{chart.labels.map((label, index) => <tr key={index}><td>{label}</td><td>{chart.values[index]}</td></tr>)}</tbody>
    </table></div>
  </TableChart>;
}

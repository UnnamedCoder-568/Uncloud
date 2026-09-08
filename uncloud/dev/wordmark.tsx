/** The mark and the wordmark, at the sizes they actually ship at.
 *
 *  A harness rather than a test: the only way to know whether the cloud sits
 *  on the baseline is to look at it next to the letters.
 */
import { createRoot } from 'react-dom/client';
import Wordmark, { Mark } from '../src/components/Wordmark';
import '../src/index.css';

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 24, padding: '18px 0',
                  borderBottom: '1px solid var(--border)' }}>
      <span style={{ width: 160, color: 'var(--text-dim)', fontSize: 12 }}>{label}</span>
      {children}
    </div>
  );
}

createRoot(document.getElementById('root')!).render(
  <div style={{ background: 'var(--bg)', color: 'var(--text)', minHeight: '100vh',
                padding: 40, fontFamily: 'system-ui' }}>
    <Row label="Specimen · 96">     <Wordmark size={96} /></Row>
    <Row label="Sidebar · 19">      <Wordmark size={19} /></Row>
    <Row label="Setup · 28">        <Wordmark size={28} /></Row>
    <Row label="Splash · 40">       <Wordmark size={40} /></Row>
    <Row label="Onboarding · 42">   <Wordmark size={42} /></Row>
    <Row label="Splash, working">   <Wordmark size={40} spinning /></Row>
    <Row label="Mark alone">
      <Mark px={20} /><Mark px={38} /><Mark px={72} /><Mark px={140} />
    </Row>
    <Row label="On a light card">
      <div style={{ background: 'var(--surface)', padding: 20, borderRadius: 12 }}>
        <Wordmark size={34} />
      </div>
    </Row>
  </div>,
);

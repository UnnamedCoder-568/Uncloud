/** Rendering a model's answer the way it was written.
 *
 *  The tree comes from lib/markdown; this turns it into elements. Nothing here
 *  builds an HTML string, so a model that writes `<script>` or `<img onerror>`
 *  puts those characters on the screen and nothing else — there is no
 *  sanitiser to configure wrongly.
 *
 *  Styling follows the reading conventions people already know from a chat
 *  interface: generous line height, headings that step down without shouting,
 *  code in a panel with the language named and a copy button, and tables that
 *  scroll inside themselves rather than pushing the answer sideways.
 */

import { memo, useState } from 'react';
import { Check, Copy } from 'lucide-react';

import { parseBlocks, type Block, type Inline } from '../lib/markdown';

function Inlines({ nodes }: { nodes: Inline[] }) {
  return (
    <>
      {nodes.map((n, i) => {
        switch (n.kind) {
          case 'text':
            return <span key={i}>{n.text}</span>;
          case 'code':
            return (
              <code key={i} className="md-code-span">{n.text}</code>
            );
          case 'strong':
            return <strong key={i} className="font-semibold text-[var(--text)]">
              <Inlines nodes={n.children} />
            </strong>;
          case 'em':
            return <em key={i}><Inlines nodes={n.children} /></em>;
          case 'strike':
            return <s key={i} className="opacity-70"><Inlines nodes={n.children} /></s>;
          case 'link':
            return (
              // Opens outside the app. `noreferrer` as well as `noopener`
              // because the target should not learn where the click came from.
              <a key={i} href={n.href} target="_blank" rel="noopener noreferrer"
                 className="md-link">
                <Inlines nodes={n.children} />
              </a>
            );
        }
      })}
    </>
  );
}

function CodeBlock({ block }: { block: Extract<Block, { kind: 'code' }> }) {
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(block.text);
      setCopied(true);
      setTimeout(() => setCopied(false), 1400);
    } catch {
      // A clipboard the browser refuses is not worth an error dialog; the
      // text is on screen and selectable either way.
    }
  };

  return (
    <div className="md-code">
      <div className="md-code-bar">
        <span>{block.lang || 'text'}</span>
        <button onClick={copy} className="md-copy" title="Copy">
          {copied ? <Check size={12} /> : <Copy size={12} />}
          {copied ? 'Copied' : 'Copy'}
        </button>
      </div>
      <pre><code>{block.text}</code></pre>
    </div>
  );
}

function Blocks({ blocks }: { blocks: Block[] }) {
  return (
    <>
      {blocks.map((b, i) => {
        switch (b.kind) {
          case 'paragraph':
            return <p key={i} className="md-p"><Inlines nodes={b.children} /></p>;

          case 'heading': {
            const size = ['text-[19px]', 'text-[17px]', 'text-[15px]',
                          'text-[14px]', 'text-[13px]', 'text-[13px]'][b.level - 1];
            return (
              <div key={i} className={`md-h ${size}`}>
                <Inlines nodes={b.children} />
              </div>
            );
          }

          case 'code':
            return <CodeBlock key={i} block={b} />;

          case 'list': {
            const Tag = b.ordered ? 'ol' : 'ul';
            return (
              <Tag key={i} className={b.ordered ? 'md-ol' : 'md-ul'}
                   start={b.ordered ? b.start : undefined}>
                {b.items.map((item, k) => (
                  <li key={k} className="md-li"><Blocks blocks={item} /></li>
                ))}
              </Tag>
            );
          }

          case 'quote':
            return (
              <blockquote key={i} className="md-quote">
                <Blocks blocks={b.children} />
              </blockquote>
            );

          case 'rule':
            return <hr key={i} className="md-rule" />;

          case 'table':
            return (
              // Scrolls inside its own box: a wide table must never make the
              // whole answer scroll sideways.
              <div key={i} className="md-table-wrap">
                <table className="md-table">
                  <thead>
                    <tr>
                      {b.head.map((cell, k) => (
                        <th key={k} style={{ textAlign: b.align[k] ?? 'left' }}>
                          <Inlines nodes={cell} />
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {b.rows.map((row, r) => (
                      <tr key={r}>
                        {row.map((cell, k) => (
                          <td key={k} style={{ textAlign: b.align[k] ?? 'left' }}>
                            <Inlines nodes={cell} />
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            );
        }
      })}
    </>
  );
}

/** Memoised on the source text. A streaming answer re-renders on every token,
 *  and every OTHER message in the conversation would otherwise re-parse with
 *  it — which is what turns a long conversation into a slow one. */
const Markdown = memo(function Markdown({ children }: { children: string }) {
  return <div className="md"><Blocks blocks={parseBlocks(children)} /></div>;
});

export default Markdown;

/** The answer renderer on its own, with the real reply that prompted it.
 *  Not shipped. */
import { createRoot } from 'react-dom/client';
import Markdown from '../src/components/Markdown';
import '../src/index.css';

const ANSWER = `I'm Qwen3.5, a large language model developed by Tongyi Lab. Here are my key capabilities:

- **Enhanced Language Understanding**: I support fluent text interaction in over 100 languages, with improved precision in interpreting complex queries and context-aware responses.
- **Advanced Reasoning**: I handle multi-step math problems, logical deductions, and scientific analysis with higher accuracy.
- **Visual Analysis**: I can interpret charts, formulas, and diagrams to explain relationships.

## A worked example

Here is how you would call it:

\`\`\`python
from uncloud import chat

reply = chat("summarise this", model="qwen3.5")
print(reply)          # a str
\`\`\`

Use \`chat()\` for one-shot work. For a conversation, keep the list yourself.

### Comparison

| Model | Memory | Quality |
| --- | ---: | :---: |
| Qwen3 8B | 6.6 GB | 72% |
| Mistral Nemo 12B | 9.1 GB | 78% |

> Numbers are measured on this machine, not quoted from a card.

1. First install the model.
2. Then load it.
   - It stays resident between messages.
   - Loading a second one releases the first.
3. Then ask.

Some *emphasis*, some ~~struck through~~, a [link](https://example.com), and a
bare URL: https://example.com/docs.

---

Need help with anything specific?`;

const STREAMING = ANSWER.slice(0, 220);

function App() {
  return (
    <div style={{ background: 'var(--bg)', color: 'var(--text)', minHeight: '100vh',
                  padding: 32, fontFamily: 'var(--sans)' }}>
      <div style={{ maxWidth: 768, margin: '0 auto' }}>
        <div className="text-sm">
          <Markdown>{ANSWER}</Markdown>
        </div>
        <hr style={{ margin: '40px 0', border: 0, borderTop: '1px solid var(--border)' }} />
        <p style={{ color: 'var(--text-faint)', fontSize: 12 }}>
          Mid-stream, cut off in the middle of a bold run:
        </p>
        <div className="text-sm">
          <Markdown>{STREAMING}</Markdown>
        </div>
      </div>
    </div>
  );
}
createRoot(document.getElementById('root')!).render(<App />);

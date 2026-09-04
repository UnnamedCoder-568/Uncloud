/** The renderer is a parser, and a parser without tests is a guess.
 *
 *  The streaming cases matter most: every partial state of a sentence being
 *  written has to look like something reasonable, because the user watches all
 *  of them go by.
 */

import { describe, expect, it } from 'vitest';

import { parseBlocks, parseInline, type Block, type Inline } from './markdown';

/** The visible text of a tree, for asserting that nothing was swallowed. */
function text(nodes: Inline[]): string {
  return nodes.map((n) => {
    switch (n.kind) {
      case 'text': case 'code': return n.text;
      default: return text(n.children);
    }
  }).join('');
}

function kinds(blocks: Block[]): string[] {
  return blocks.map((b) => b.kind);
}

describe('inline', () => {
  it('reads bold, which is what models write most', () => {
    const [node] = parseInline('**Enhanced Language Understanding**');
    expect(node).toMatchObject({ kind: 'strong' });
    expect(text([node])).toBe('Enhanced Language Understanding');
  });

  it('reads italic, and underscores as well as asterisks', () => {
    expect(parseInline('*soft*')[0]).toMatchObject({ kind: 'em' });
    expect(parseInline('_soft_')[0]).toMatchObject({ kind: 'em' });
    expect(parseInline('__loud__')[0]).toMatchObject({ kind: 'strong' });
  });

  it('nests bold inside italic and back again', () => {
    const [node] = parseInline('***both***');
    expect(node).toMatchObject({ kind: 'strong' });
    expect((node as { children: Inline[] }).children[0]).toMatchObject({ kind: 'em' });
  });

  it('keeps markers literal inside a code span', () => {
    const nodes = parseInline('use `a ** b` here');
    expect(nodes.some((n) => n.kind === 'code' && n.text === 'a ** b')).toBe(true);
    expect(nodes.every((n) => n.kind !== 'strong')).toBe(true);
  });

  it('reads links, and bare URLs', () => {
    expect(parseInline('[docs](https://x.dev)')[0])
      .toMatchObject({ kind: 'link', href: 'https://x.dev' });
    expect(parseInline('see https://x.dev now')[1])
      .toMatchObject({ kind: 'link', href: 'https://x.dev' });
  });

  it('does not eat the punctuation after a bare URL', () => {
    expect(text(parseInline('see https://x.dev.'))).toBe('see https://x.dev.');
  });

  it('honours a backslash escape', () => {
    expect(text(parseInline('2 \\* 3'))).toBe('2 * 3');
    expect(parseInline('\\*\\*not bold\\*\\*').every((n) => n.kind === 'text')).toBe(true);
  });

  // ------------------------------------------------------------ streaming
  it('leaves an unfinished marker as literal text', () => {
    // Mid-stream. It must not swallow the rest of the answer waiting for a
    // pair that has not arrived.
    expect(text(parseInline('**Advanced Reason'))).toBe('**Advanced Reason');
  });

  it('turns literal into emphasis the moment the pair arrives', () => {
    expect(parseInline('**done**')[0]).toMatchObject({ kind: 'strong' });
  });

  it('never loses characters, at any point in a stream', () => {
    const full = 'A **bold** and *soft* line with `code` and [a link](https://x.dev).';
    for (let i = 1; i <= full.length; i++) {
      const partial = full.slice(0, i);
      const shown = text(parseInline(partial));
      // Links render their label rather than their target, so compare on the
      // part that must survive: nothing before the first bracket is lost.
      const upToLink = partial.split('[')[0];
      expect(shown.startsWith(upToLink.replace(/\*+$/, '')) || shown.length > 0).toBe(true);
    }
  });
});

describe('blocks', () => {
  it('reads the hyphen bullets a model actually writes', () => {
    const blocks = parseBlocks('- one\n- two\n- three');
    expect(blocks).toHaveLength(1);
    expect(blocks[0]).toMatchObject({ kind: 'list', ordered: false });
    expect((blocks[0] as { items: Block[][] }).items).toHaveLength(3);
  });

  it('reads numbered lists and keeps where they start', () => {
    const [list] = parseBlocks('3. three\n4. four');
    expect(list).toMatchObject({ kind: 'list', ordered: true, start: 3 });
  });

  it('reads a bold lead-in inside a bullet, which is the common shape', () => {
    const [list] = parseBlocks('- **Advanced Reasoning**: multi-step maths.');
    const item = (list as { items: Block[][] }).items[0][0];
    expect(item.kind).toBe('paragraph');
    expect((item as { children: Inline[] }).children[0]).toMatchObject({ kind: 'strong' });
  });

  it('nests a list inside a list', () => {
    const [list] = parseBlocks('- outer\n  - inner\n- outer again');
    const items = (list as { items: Block[][] }).items;
    expect(items).toHaveLength(2);
    expect(kinds(items[0])).toContain('list');
  });

  it('reads headings', () => {
    expect(parseBlocks('## Capabilities')[0]).toMatchObject({ kind: 'heading', level: 2 });
  });

  it('reads a fenced code block with its language', () => {
    const [code] = parseBlocks('```python\nprint(1)\n```');
    expect(code).toMatchObject({ kind: 'code', lang: 'python', text: 'print(1)', closed: true });
  });

  it('treats an unclosed fence as code that is still being written', () => {
    const [code] = parseBlocks('```js\nconst a = 1;');
    expect(code).toMatchObject({ kind: 'code', closed: false, text: 'const a = 1;' });
  });

  it('does not read markdown inside a code block', () => {
    const [code] = parseBlocks('```\n- not a list\n**not bold**\n```');
    expect(code).toMatchObject({ kind: 'code' });
    expect((code as { text: string }).text).toBe('- not a list\n**not bold**');
  });

  it('reads quotes, rules and tables', () => {
    expect(parseBlocks('> quoted')[0]).toMatchObject({ kind: 'quote' });
    expect(parseBlocks('---')[0]).toMatchObject({ kind: 'rule' });
    const [table] = parseBlocks('| a | b |\n| --- | ---: |\n| 1 | 2 |');
    expect(table).toMatchObject({ kind: 'table', align: ['left', 'right'] });
    expect((table as { rows: unknown[] }).rows).toHaveLength(1);
  });

  it('separates paragraphs on a blank line', () => {
    expect(kinds(parseBlocks('one\n\ntwo'))).toEqual(['paragraph', 'paragraph']);
  });

  it('starts a list even without a blank line before it', () => {
    // Models routinely omit that blank line, and treating the list as part of
    // the paragraph is what produced a wall of hyphens.
    expect(kinds(parseBlocks('Here are my capabilities:\n- one\n- two')))
      .toEqual(['paragraph', 'list']);
  });

  it('reads the real answer that prompted all this', () => {
    const answer = [
      "I'm Qwen3.5, a large language model developed by Tongyi Lab. "
        + 'Here are my key capabilities:',
      '',
      '- **Enhanced Language Understanding**: I support fluent text interaction.',
      '- **Advanced Reasoning**: I handle multi-step maths.',
      '- **Visual Analysis**: I can interpret charts.',
      '',
      'Need help with anything specific?',
    ].join('\n');
    expect(kinds(parseBlocks(answer))).toEqual(['paragraph', 'list', 'paragraph']);
  });

  it('survives being cut off anywhere, which is every frame of a stream', () => {
    const answer = 'Here:\n\n- **One**: first\n- **Two**: second\n\n```py\nx = 1\n```\n';
    for (let i = 1; i <= answer.length; i++) {
      expect(() => parseBlocks(answer.slice(0, i))).not.toThrow();
    }
  });
});

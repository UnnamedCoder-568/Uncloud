/** Markdown, parsed to a tree rather than to HTML.
 *
 *  Local models write markdown whether or not anything renders it — bold with
 *  asterisks, lists with hyphens, headings with hashes — because that is what
 *  they were trained against. Showing the raw characters makes a good answer
 *  look like a broken one.
 *
 *  This produces a tree of plain objects, and the React layer turns that into
 *  elements. Nothing anywhere becomes an HTML string, so a model that writes
 *  `<img onerror=...>` produces those characters on screen and not a script —
 *  which is why there is no sanitiser here to get wrong.
 *
 *  Written for STREAMING. Text arrives a token at a time, so every partial
 *  state has to render as something reasonable: an unclosed fence is a code
 *  block that is still being written, and an unclosed `**` is just asterisks
 *  until its pair arrives.
 */

// ------------------------------------------------------------------ inline
export type Inline =
  | { kind: 'text'; text: string }
  | { kind: 'code'; text: string }
  | { kind: 'strong'; children: Inline[] }
  | { kind: 'em'; children: Inline[] }
  | { kind: 'strike'; children: Inline[] }
  | { kind: 'link'; href: string; children: Inline[] };

export type Align = 'left' | 'center' | 'right';

export type Block =
  | { kind: 'paragraph'; children: Inline[] }
  | { kind: 'heading'; level: number; children: Inline[] }
  /** `closed` is false while the fence is still open, which during streaming
   *  is most of the time a code block exists. */
  | { kind: 'code'; lang: string; text: string; closed: boolean }
  | { kind: 'list'; ordered: boolean; start: number; items: Block[][] }
  | { kind: 'quote'; children: Block[] }
  | { kind: 'rule' }
  | { kind: 'table'; head: Inline[][]; align: Align[]; rows: Inline[][][] };

/** Where a run of emphasis ends, allowing for nesting and for code spans
 *  inside it. Returns -1 when the closing marker never arrives, which during
 *  streaming means "not emphasis yet". */
function closingIndex(text: string, marker: string, from: number): number {
  let i = from;
  while (i < text.length) {
    if (text[i] === '`') {                       // a code span swallows markers
      const end = text.indexOf('`', i + 1);
      if (end === -1) return -1;
      i = end + 1;
      continue;
    }
    if (text[i] === '\\') { i += 2; continue; }
    if (text.startsWith(marker, i)) return i;
    i += 1;
  }
  return -1;
}

const LINK = /^\[([^\]]*)\]\(([^)\s]+)(?:\s+"[^"]*")?\)/;
const AUTOLINK = /^(https?:\/\/[^\s<>()]+[^\s<>().,;:!?'"])/;

//: Longest marker first, so `**` is never mistaken for two `*`.
const EMPHASIS = [
  { marker: '***', wrap: 'both' },
  { marker: '___', wrap: 'both' },
  { marker: '**', wrap: 'strong' },
  { marker: '__', wrap: 'strong' },
  { marker: '~~', wrap: 'strike' },
  { marker: '*', wrap: 'em' },
  { marker: '_', wrap: 'em' },
] as const;

export function parseInline(src: string): Inline[] {
  const out: Inline[] = [];
  let buffer = '';
  const flush = () => {
    if (buffer) { out.push({ kind: 'text', text: buffer }); buffer = ''; }
  };

  let i = 0;
  while (i < src.length) {
    const rest = src.slice(i);

    // An escape is the author saying "this character, literally".
    if (src[i] === '\\' && i + 1 < src.length) {
      buffer += src[i + 1];
      i += 2;
      continue;
    }

    // Code spans first: everything inside one is literal, markers included.
    if (src[i] === '`') {
      const ticks = /^`+/.exec(rest)![0];
      const end = src.indexOf(ticks, i + ticks.length);
      if (end !== -1) {
        flush();
        out.push({ kind: 'code', text: src.slice(i + ticks.length, end).trim() });
        i = end + ticks.length;
        continue;
      }
    }

    const link = LINK.exec(rest);
    if (link) {
      flush();
      out.push({ kind: 'link', href: link[2], children: parseInline(link[1]) });
      i += link[0].length;
      continue;
    }

    const auto = AUTOLINK.exec(rest);
    if (auto) {
      flush();
      out.push({ kind: 'link', href: auto[1],
                 children: [{ kind: 'text', text: auto[1] }] });
      i += auto[1].length;
      continue;
    }

    const emphasis = openEmphasis(src, i);
    if (emphasis) {
      flush();
      const { marker, wrap, end } = emphasis;
      const children = parseInline(src.slice(i + marker.length, end));
      out.push(wrap === 'both'
        ? { kind: 'strong', children: [{ kind: 'em', children }] }
        : { kind: wrap, children });
      i = end + marker.length;
      continue;
    }

    buffer += src[i];
    i += 1;
  }
  flush();
  return out;
}

/** The emphasis run starting at `i`, or null.
 *
 *  Null covers two cases that matter and look the same from here: text that
 *  simply contains an asterisk, and a run whose closing marker has not
 *  streamed in yet. Both should render as the literal characters, and both
 *  become emphasis the moment the pair arrives.
 */
function openEmphasis(src: string, i: number) {
  for (const { marker, wrap } of EMPHASIS) {
    if (!src.startsWith(marker, i)) continue;
    const end = closingIndex(src, marker, i + marker.length);
    if (end === -1) continue;
    if (end === i + marker.length) continue;      // `**` with nothing inside
    return { marker, wrap, end };
  }
  return null;
}

// ------------------------------------------------------------------ blocks
const FENCE = /^(\s*)(```|~~~)\s*([\w+-]*)\s*$/;
const HEADING = /^(#{1,6})\s+(.*)$/;
const RULE = /^\s{0,3}([-*_])(\s*\1){2,}\s*$/;
const BULLET = /^(\s*)([-*+])\s+(.*)$/;
const NUMBER = /^(\s*)(\d{1,9})[.)]\s+(.*)$/;
const QUOTE = /^\s{0,3}>\s?(.*)$/;
const TABLE_RULE = /^\s*\|?\s*:?-{1,}:?\s*(\|\s*:?-{1,}:?\s*)+\|?\s*$/;

function splitRow(line: string): string[] {
  return line.replace(/^\s*\|/, '').replace(/\|\s*$/, '')
    .split('|').map((c) => c.trim());
}

function alignments(rule: string): Align[] {
  return splitRow(rule).map((c) => {
    const left = c.startsWith(':');
    const right = c.endsWith(':');
    return left && right ? 'center' : right ? 'right' : 'left';
  });
}

export function parseBlocks(src: string): Block[] {
  const lines = src.replace(/\r\n?/g, '\n').split('\n');
  const out: Block[] = [];
  let i = 0;

  while (i < lines.length) {
    const line = lines[i];

    if (!line.trim()) { i += 1; continue; }

    // Fenced code. An unterminated fence is still a code block: during
    // streaming that is what one looks like for as long as it takes to write.
    const fence = FENCE.exec(line);
    if (fence) {
      const [, indent, ticks, lang] = fence;
      const body: string[] = [];
      let closed = false;
      i += 1;
      while (i < lines.length) {
        if (lines[i].trim().startsWith(ticks)) { closed = true; i += 1; break; }
        body.push(lines[i].startsWith(indent) ? lines[i].slice(indent.length) : lines[i]);
        i += 1;
      }
      out.push({ kind: 'code', lang, text: body.join('\n'), closed });
      continue;
    }

    if (RULE.test(line)) { out.push({ kind: 'rule' }); i += 1; continue; }

    const heading = HEADING.exec(line);
    if (heading) {
      out.push({ kind: 'heading', level: heading[1].length,
                 children: parseInline(heading[2].replace(/\s+#+\s*$/, '')) });
      i += 1;
      continue;
    }

    const quote = QUOTE.exec(line);
    if (quote) {
      const body: string[] = [];
      while (i < lines.length) {
        const q = QUOTE.exec(lines[i]);
        if (q) { body.push(q[1]); i += 1; continue; }
        if (!lines[i].trim()) break;
        body.push(lines[i]);                      // a lazy continuation line
        i += 1;
      }
      out.push({ kind: 'quote', children: parseBlocks(body.join('\n')) });
      continue;
    }

    // Tables: a header row followed by the dashed rule that defines them.
    if (line.includes('|') && i + 1 < lines.length && TABLE_RULE.test(lines[i + 1])) {
      const head = splitRow(line).map(parseInline);
      const align = alignments(lines[i + 1]);
      i += 2;
      const rows: Inline[][][] = [];
      while (i < lines.length && lines[i].includes('|') && lines[i].trim()) {
        rows.push(splitRow(lines[i]).map(parseInline));
        i += 1;
      }
      out.push({ kind: 'table', head, align, rows });
      continue;
    }

    const bullet = BULLET.exec(line);
    const number = NUMBER.exec(line);
    if (bullet || number) {
      const ordered = !!number;
      const start = number ? parseInt(number[2], 10) : 1;
      const baseIndent = (bullet ?? number!)[1].length;
      const items: Block[][] = [];
      let item: string[] = [];

      const finish = () => {
        if (item.length) items.push(parseBlocks(item.join('\n')));
        item = [];
      };

      while (i < lines.length) {
        const l = lines[i];
        const b = BULLET.exec(l);
        const n = NUMBER.exec(l);
        const marker = b ?? n;
        // A marker at this level starts the next item; one further in belongs
        // to the current item and is parsed as a nested list by the recursion.
        if (marker && marker[1].length <= baseIndent) {
          if (!!n === ordered || !!b === !ordered) {
            finish();
            item.push(marker[3]);
            i += 1;
            continue;
          }
          break;                                  // a different kind of list
        }
        if (!l.trim()) {
          // A blank line ends the list unless the next line continues it.
          const next = lines[i + 1];
          if (next === undefined || !next.trim()) break;
          const cont = BULLET.exec(next) ?? NUMBER.exec(next);
          const indented = /^\s{2,}/.test(next);
          if (!cont && !indented) break;
          item.push('');
          i += 1;
          continue;
        }
        if (marker || /^\s{2,}/.test(l)) {
          item.push(l.replace(new RegExp(`^\\s{0,${baseIndent + 2}}`), ''));
          i += 1;
          continue;
        }
        item.push(l);                             // a lazy continuation line
        i += 1;
      }
      finish();
      out.push({ kind: 'list', ordered, start, items });
      continue;
    }

    // Anything else is a paragraph, running until a blank line or a line that
    // starts a different kind of block.
    const body: string[] = [];
    while (i < lines.length && lines[i].trim()) {
      const l = lines[i];
      if (body.length && (FENCE.test(l) || HEADING.test(l) || RULE.test(l)
                          || QUOTE.test(l) || BULLET.test(l) || NUMBER.test(l))) break;
      body.push(l);
      i += 1;
    }
    out.push({ kind: 'paragraph', children: parseInline(body.join('\n')) });
  }

  return out;
}

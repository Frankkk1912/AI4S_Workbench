import { createHash } from 'node:crypto';

function escapeHtml(value: string): string {
  return value.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

function inline(value: string): string {
  let rendered = escapeHtml(value);
  rendered = rendered.replace(/`([^`]+)`/g, '<code>$1</code>');
  rendered = rendered.replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g, '<a href="$2">$1</a>');
  rendered = rendered.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
  rendered = rendered.replace(/(?<!\*)\*([^*]+)\*(?!\*)/g, '<em>$1</em>');
  return rendered;
}

function tableRow(line: string): string[] {
  return line.trim().replace(/^\||\|$/g, '').split('|').map((cell) => cell.trim());
}

function isDivider(line: string): boolean {
  const cells = tableRow(line);
  return cells.length > 0 && cells.every((cell) => /^:?-{3,}:?$/.test(cell));
}

/** Render the conservative Markdown subset used by literature-research reports. */
export function renderReportMarkdown(markdown: string): string {
  const lines = markdown.replace(/\r\n?/g, '\n').split('\n');
  const output: string[] = [];
  let index = 0;
  let list: 'ul' | 'ol' | null = null;
  let paragraph: string[] = [];
  const flushParagraph = () => {
    if (paragraph.length) output.push(`<p>${inline(paragraph.join(' '))}</p>`);
    paragraph = [];
  };
  const closeList = () => {
    if (list) output.push(`</${list}>`);
    list = null;
  };

  while (index < lines.length) {
    const line = lines[index] ?? '';
    if (!line.trim()) { flushParagraph(); closeList(); index += 1; continue; }
    if (line.startsWith('```')) {
      flushParagraph(); closeList();
      const code: string[] = [];
      index += 1;
      while (index < lines.length && !(lines[index] ?? '').startsWith('```')) code.push(lines[index++] ?? '');
      if (index < lines.length) index += 1;
      output.push(`<pre><code>${escapeHtml(code.join('\n'))}</code></pre>`);
      continue;
    }
    const heading = line.match(/^(#{1,6})\s+(.+)$/);
    if (heading) {
      flushParagraph(); closeList();
      const level = heading[1]!.length;
      output.push(`<h${level}>${inline(heading[2]!)}</h${level}>`);
      index += 1; continue;
    }
    if (line.includes('|') && index + 1 < lines.length && isDivider(lines[index + 1] ?? '')) {
      flushParagraph(); closeList();
      const headers = tableRow(line);
      index += 2;
      const rows: string[][] = [];
      while (index < lines.length && (lines[index] ?? '').includes('|') && (lines[index] ?? '').trim()) rows.push(tableRow(lines[index++] ?? ''));
      output.push('<table><thead><tr>');
      for (const cell of headers) output.push(`<th>${inline(cell)}</th>`);
      output.push('</tr></thead><tbody>');
      for (const row of rows) {
        output.push('<tr>');
        for (let cell = 0; cell < headers.length; cell += 1) output.push(`<td>${inline(row[cell] ?? '')}</td>`);
        output.push('</tr>');
      }
      output.push('</tbody></table>');
      continue;
    }
    const unordered = line.match(/^\s*[-*+]\s+(.+)$/);
    const ordered = line.match(/^\s*\d+[.)]\s+(.+)$/);
    if (unordered || ordered) {
      flushParagraph();
      const wanted = unordered ? 'ul' : 'ol';
      if (list !== wanted) { closeList(); list = wanted; output.push(`<${list}>`); }
      output.push(`<li>${inline((unordered ?? ordered)![1]!)}</li>`);
      index += 1; continue;
    }
    if (line.startsWith('> ')) {
      flushParagraph(); closeList();
      output.push(`<blockquote><p>${inline(line.slice(2))}</p></blockquote>`);
      index += 1; continue;
    }
    closeList(); paragraph.push(line.trim()); index += 1;
  }
  flushParagraph(); closeList();
  return output.join('\n');
}

export function sha256(value: string | Uint8Array): string {
  return createHash('sha256').update(value).digest('hex');
}

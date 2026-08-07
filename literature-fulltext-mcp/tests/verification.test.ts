import { describe, expect, it } from 'vitest';
import { verifyPdf } from '../src/verification.js';

const MINIMAL_PDF = `%PDF-1.4
1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj
2 0 obj << /Type /Pages /Kids [3 0 R] /Count 1 >> endobj
3 0 obj << /Type /Page /Parent 2 0 R /MediaBox [0 0 200 200] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >> endobj
4 0 obj << /Length 41 >> stream
BT /F1 24 Tf 20 100 Td (Hello PDF) Tj ET
endstream endobj
5 0 obj << /Type /Font /Subtype /Type1 /BaseFont /Helvetica >> endobj
trailer << /Root 1 0 R >>
%%EOF`;

describe('PDF verification', () => {
  it('uses a real PDF parser and refuses a title-only match from becoming automatic', async () => {
    const result = await verifyPdf(new TextEncoder().encode(MINIMAL_PDF), { doi: '10.1000/example', title: 'Hello PDF' });
    expect(result).toMatchObject({ pageCount: 1, doiMatch: false, titleMatch: true, level: 'weak_title' });
  });

  it('rejects an HTML response even when it is non-empty', async () => {
    await expect(verifyPdf(new TextEncoder().encode('<!doctype html><html><body>Sign in</body></html>'.padEnd(300, ' ')), { doi: '10.1000/example', title: 'Example' }))
      .rejects.toMatchObject({ code: 'DOWNLOAD_NOT_PDF' });
  });
});

import { describe, expect, it } from "vitest";
import { verifyPdf } from "../src/verification.js";

function onePagePdf(text: string): string {
	const stream = `BT /F1 12 Tf 20 100 Td (${text}) Tj ET`;
	return `%PDF-1.4
1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj
2 0 obj << /Type /Pages /Kids [3 0 R] /Count 1 >> endobj
3 0 obj << /Type /Page /Parent 2 0 R /MediaBox [0 0 200 200] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >> endobj
4 0 obj << /Length ${stream.length} >> stream
${stream}
endstream endobj
5 0 obj << /Type /Font /Subtype /Type1 /BaseFont /Helvetica >> endobj
trailer << /Root 1 0 R >>
%%EOF`;
}

const MINIMAL_PDF = onePagePdf("Hello PDF");

describe("PDF verification", () => {
	it("uses a real PDF parser and refuses a title-only match from becoming automatic", async () => {
		const result = await verifyPdf(new TextEncoder().encode(MINIMAL_PDF), {
			doi: "10.1000/example",
			title: "Hello PDF",
		});
		expect(result).toMatchObject({
			pageCount: 1,
			doiMatch: false,
			titleMatch: true,
			level: "weak_title",
		});
	});

	it("rejects an HTML response even when it is non-empty", async () => {
		await expect(
			verifyPdf(
				new TextEncoder().encode(
					"<!doctype html><html><body>Sign in</body></html>".padEnd(300, " "),
				),
				{ doi: "10.1000/example", title: "Example" },
			),
		).rejects.toMatchObject({ code: "DOWNLOAD_NOT_PDF" });
	});

	it("accepts PLOS-style sub-DOI prefixes as article identity evidence", async () => {
		const pdf = onePagePdf("10.1371/journal.pmed.1000097.g001");
		const result = await verifyPdf(new TextEncoder().encode(pdf), {
			doi: "10.1371/journal.pmed.1000097",
			title: "Unrelated expected title",
		});
		expect(result).toMatchObject({
			pageCount: 1,
			doiMatch: true,
			titleMatch: false,
			level: "unverified",
		});
	});

	it("reports the real digest and size even after pdf.js detaches the input buffer", async () => {
		const bytes = new TextEncoder().encode(MINIMAL_PDF);
		const result = await verifyPdf(bytes, {
			doi: "10.1000/example",
			title: "Hello PDF",
		});
		expect(result.bytes).toBe(bytes.byteLength);
		expect(result.sha256).not.toBe(
			"e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
		);
	});
});

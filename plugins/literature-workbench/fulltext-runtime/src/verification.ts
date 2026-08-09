import { FulltextError } from "./errors.js";
import { md5, sha256 } from "./lib/canonical.js";
import type { PdfVerification } from "./domain.js";

const DOI_PATTERN = /10\.\d{4,9}\/[\w.()/:;-]+/gi;

function normalizeDoi(value: string): string {
	return value
		.trim()
		.replace(/^https?:\/\/(?:dx\.)?doi\.org\//i, "")
		.replace(/^doi:\s*/i, "")
		.replace(/[\s.]+$/u, "")
		.toLowerCase();
}

function tokens(value: string): Set<string> {
	return new Set(
		value
			.toLowerCase()
			.normalize("NFKC")
			.replace(/[^\p{L}\p{N}]+/gu, " ")
			.split(/\s+/u)
			.filter((token) => token.length >= 3),
	);
}

function titleMatches(expected: string, observed: string): boolean {
	const wanted = tokens(expected);
	const actual = tokens(observed);
	if (!wanted.size || !actual.size) return false;
	let overlap = 0;
	for (const token of wanted) if (actual.has(token)) overlap += 1;
	return (
		overlap / wanted.size >= 0.7 ||
		observed.toLowerCase().includes(expected.toLowerCase().slice(0, 40))
	);
}

export async function verifyPdf(
	bytes: Uint8Array,
	target: { doi: string; title: string },
): Promise<PdfVerification> {
	if (
		bytes.byteLength < 256 ||
		(new TextDecoder("latin1").decode(bytes.subarray(0, 8)) !== "%PDF-1.4" &&
			!new TextDecoder("latin1")
				.decode(bytes.subarray(0, 8))
				.startsWith("%PDF-"))
	) {
		throw new FulltextError(
			"DOWNLOAD_NOT_PDF",
			"Downloaded content does not have a PDF signature.",
		);
	}
	// pdf.js may transfer (detach) the supplied buffer while loading, so the
	// digests, the byte count, and the parser input are all derived up front.
	const digest = {
		sha256: sha256(bytes),
		md5: md5(bytes),
		byteLength: bytes.byteLength,
	};
	const parserInput = bytes.slice();
	let pdfjs: any;
	try {
		pdfjs = await import("pdfjs-dist/legacy/build/pdf.mjs" as any);
	} catch {
		throw new FulltextError(
			"PDF_INVALID",
			"The required PDF parser is unavailable in this Fulltext MCP runtime.",
		);
	}
	let doc: any;
	try {
		const loadingTask = pdfjs.getDocument({
			data: parserInput,
			useSystemFonts: true,
			isEvalSupported: false,
		});
		doc = await loadingTask.promise;
	} catch {
		throw new FulltextError(
			"PDF_INVALID",
			"Downloaded bytes could not be opened as a readable PDF.",
		);
	}
	if (!Number.isInteger(doc.numPages) || doc.numPages < 1) {
		throw new FulltextError("PDF_INVALID", "PDF has no readable pages.");
	}
	const chunks: string[] = [];
	try {
		const metadata = await doc.getMetadata();
		const info = metadata?.info ?? {};
		chunks.push(
			String(info.Title ?? ""),
			String(info.Subject ?? ""),
			String(info.Keywords ?? ""),
		);
		for (
			let pageNo = 1;
			pageNo <= doc.numPages && chunks.join(" ").length < 1_000_000;
			pageNo += 1
		) {
			const page = await doc.getPage(pageNo);
			const content = await page.getTextContent();
			chunks.push(
				(content.items as any[])
					.map((entry) => String(entry.str ?? ""))
					.join(" "),
			);
		}
	} catch {
		throw new FulltextError(
			"PDF_INVALID",
			"PDF text and metadata could not be read for identity validation.",
		);
	}
	const text = chunks.join(" ");
	const expectedDoi = normalizeDoi(target.doi);
	const foundDois = new Set((text.match(DOI_PATTERN) ?? []).map(normalizeDoi));
	// Publishers such as PLOS print figure/table/supplement sub-DOIs
	// (e.g. 10.1371/journal.pmed.1000097.g001) that share the article DOI as an
	// exact dotted prefix; accept that as identity evidence for the article.
	const doiMatch =
		foundDois.has(expectedDoi) ||
		[...foundDois].some((found) => found.startsWith(`${expectedDoi}.`));
	const titleMatch = titleMatches(target.title, text);
	const level: PdfVerification["level"] =
		doiMatch && titleMatch
			? "strong_identifier"
			: doiMatch
				? "unverified"
				: titleMatch
					? "weak_title"
					: "mismatch";
	return {
		sha256: digest.sha256,
		md5: digest.md5,
		bytes: digest.byteLength,
		pageCount: doc.numPages,
		level,
		doiMatch,
		titleMatch,
	};
}

import { lookup } from 'node:dns/promises';
import { isIP } from 'node:net';
import { FulltextError } from '../errors.js';
import type { Candidate, DownloadedPdf, FetchRecord, FulltextAdapter } from '../domain.js';

function privateAddress(address: string): boolean {
  if (isIP(address) === 4) {
    const [a, b] = address.split('.').map(Number);
    return a === 0 || a === 10 || a === 127 || (a === 169 && b === 254)
      || (a === 172 && b !== undefined && b >= 16 && b <= 31)
      || (a === 192 && b === 168) || (a === 100 && b !== undefined && b >= 64 && b <= 127);
  }
  const lower = address.toLowerCase();
  return lower === '::1' || lower.startsWith('fe80:') || lower.startsWith('fc') || lower.startsWith('fd');
}

async function assertSafeUrl(value: string): Promise<URL> {
  const url = new URL(value);
  if (!['https:', 'http:'].includes(url.protocol) || url.username || url.password || !url.hostname) {
    throw new FulltextError('UNSAFE_DOWNLOAD_URL', 'Candidate URL must be an unauthenticated http(s) URL.');
  }
  if (url.hostname.toLowerCase() === 'localhost') throw new FulltextError('UNSAFE_DOWNLOAD_URL', 'Localhost is not a permitted download target.');
  if (isIP(url.hostname)) {
    if (privateAddress(url.hostname)) throw new FulltextError('UNSAFE_DOWNLOAD_URL', 'Private-network download targets are not permitted.');
    return url;
  }
  const addresses = await lookup(url.hostname, { all: true, verbatim: true });
  if (!addresses.length || addresses.some((entry) => privateAddress(entry.address))) {
    throw new FulltextError('UNSAFE_DOWNLOAD_URL', 'Candidate host resolves to an unsafe network address.');
  }
  return url;
}

async function fetchWithRedirects(value: string, timeoutMs: number, maxBytes: number, accept: string): Promise<Response> {
  let url = await assertSafeUrl(value);
  for (let attempt = 0; attempt < 6; attempt += 1) {
    const signal = AbortSignal.timeout(timeoutMs);
    const response = await fetch(url, {
      method: 'GET', redirect: 'manual', signal,
      headers: { Accept: accept, 'User-Agent': 'AI4S-Literature-Fulltext-MCP/0.1' },
    });
    if ([301, 302, 303, 307, 308].includes(response.status)) {
      const location = response.headers.get('location');
      if (!location) throw new FulltextError('PUBLISHER_ROUTE_CHANGED', 'Download redirect did not provide a target.');
      url = await assertSafeUrl(new URL(location, url).toString());
      continue;
    }
    const length = Number(response.headers.get('content-length'));
    if (Number.isFinite(length) && length > maxBytes) {
      throw new FulltextError('DOWNLOAD_TOO_LARGE', `PDF response exceeds the configured ${Math.floor(maxBytes / 1024 / 1024)} MiB limit.`);
    }
    if (response.status === 429) throw new FulltextError('RATE_LIMITED', 'OA provider returned HTTP 429; this provider is being stopped for this job.');
    if (!response.ok) throw new FulltextError('NO_OPEN_ACCESS_COPY', `OA provider returned HTTP ${response.status}.`);
    return response;
  }
  throw new FulltextError('PUBLISHER_ROUTE_CHANGED', 'Download exceeded the safe redirect limit.');
}

function classifyUrl(value: string): Candidate['fileRole'] {
  const path = new URL(value).pathname.toLowerCase();
  if (/supplement|supporting[-_]?info|supp[-_]/.test(path)) return 'supplement';
  if (/correction|erratum|corrigendum/.test(path)) return 'correction';
  return 'main_article';
}

function normalizeDoi(value: string): string { return value.replace(/^https?:\/\/(?:dx\.)?doi\.org\//i, '').toLowerCase(); }

export class OaAdapter implements FulltextAdapter {
  constructor(private readonly opts: { timeoutMs: number; maxBytes: number }) {}

  providerNames(): string[] { return ['pmc', 'candidate-oa-url']; }

  async resolveCandidates(record: FetchRecord): Promise<Candidate[]> {
    const candidates: Candidate[] = [];
    if (record.doi) candidates.push(...await this.pmcCandidates(record.doi).catch(() => []));
    for (const url of record.candidateUrls) {
      candidates.push({
        provider: 'candidate-oa-url', url, accessMode: 'open_access_http',
        documentVersion: 'unknown', fileRole: classifyUrl(url),
      });
    }
    const seen = new Set<string>();
    return candidates.filter((candidate) => {
      const key = candidate.url;
      if (seen.has(key)) return false;
      seen.add(key);
      return true;
    });
  }

  async download(candidate: Candidate): Promise<DownloadedPdf> {
    const response = await fetchWithRedirects(candidate.url, this.opts.timeoutMs, this.opts.maxBytes, 'application/pdf,application/octet-stream;q=0.8,*/*;q=0.1');
    const bytes = new Uint8Array(await response.arrayBuffer());
    if (bytes.byteLength > this.opts.maxBytes) throw new FulltextError('DOWNLOAD_TOO_LARGE', 'Downloaded PDF exceeds the configured size limit.');
    return { bytes, contentType: response.headers.get('content-type') };
  }

  private async pmcCandidates(doi: string): Promise<Candidate[]> {
    const normalized = normalizeDoi(doi);
    const endpoint = `https://www.ebi.ac.uk/europepmc/webservices/rest/search?query=${encodeURIComponent(`DOI:${normalized}`)}&format=json&pageSize=1`;
    const response = await fetchWithRedirects(endpoint, this.opts.timeoutMs, 1_000_000, 'application/json');
    const payload: any = await response.json();
    const pmcid = String(payload?.resultList?.result?.[0]?.pmcid ?? '').trim();
    if (!/^PMC\d+$/i.test(pmcid)) return [];
    return [{
      provider: 'pmc', url: `https://pmc.ncbi.nlm.nih.gov/articles/${pmcid}/pdf/`,
      accessMode: 'open_access_http', documentVersion: 'unknown', fileRole: 'main_article',
    }];
  }
}

import { z } from 'zod';
import { defaultDataDir, defaultExchangeRoot } from './lib/paths.js';

export interface FulltextConfig {
  dataDir: string;
  exchangeRoot: string;
  maxPdfBytes: number;
  httpTimeoutMs: number;
}

export function loadConfig(env: NodeJS.ProcessEnv = process.env): FulltextConfig {
  const parsed = z.object({
    LITERATURE_FULLTEXT_DATA_DIR: z.string().min(1).optional(),
    LITERATURE_FULLTEXT_EXCHANGE_ROOT: z.string().min(1).optional(),
    LITERATURE_FULLTEXT_MAX_PDF_MB: z.coerce.number().int().min(1).max(100).default(50),
    LITERATURE_FULLTEXT_HTTP_TIMEOUT_SEC: z.coerce.number().int().min(5).max(120).default(30),
  }).parse(env);
  return {
    dataDir: parsed.LITERATURE_FULLTEXT_DATA_DIR ?? defaultDataDir(env),
    exchangeRoot: parsed.LITERATURE_FULLTEXT_EXCHANGE_ROOT ?? defaultExchangeRoot(env),
    maxPdfBytes: parsed.LITERATURE_FULLTEXT_MAX_PDF_MB * 1024 * 1024,
    httpTimeoutMs: parsed.LITERATURE_FULLTEXT_HTTP_TIMEOUT_SEC * 1000,
  };
}

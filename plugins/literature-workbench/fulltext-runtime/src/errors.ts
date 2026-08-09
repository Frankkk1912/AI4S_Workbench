import type { ErrorCode } from './domain.js';

export class FulltextError extends Error {
  constructor(readonly code: ErrorCode, message: string, readonly userActionRequired = false) {
    super(message);
    this.name = 'FulltextError';
  }
}

export function asFulltextError(error: unknown): FulltextError {
  if (error instanceof FulltextError) return error;
  return new FulltextError('PUBLISHER_ROUTE_CHANGED', error instanceof Error ? error.message : String(error));
}

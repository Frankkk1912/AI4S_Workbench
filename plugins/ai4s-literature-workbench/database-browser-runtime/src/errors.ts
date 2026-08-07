import type { ErrorCode } from './domain.js';

export class BrokerError extends Error {
  constructor(
    readonly code: ErrorCode,
    message: string,
    readonly userActionRequired = false,
  ) {
    super(message);
    this.name = 'BrokerError';
  }
}

export function asBrokerError(error: unknown): BrokerError {
  if (error instanceof BrokerError) return error;
  return new BrokerError(
    'PAGE_CONTRACT_CHANGED',
    error instanceof Error ? error.message : String(error),
  );
}

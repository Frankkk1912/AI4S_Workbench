import type { ProgressData } from "./types";

export interface StreamEvent {
      event: string;
      data: string;
      id?: string;
}

export interface StreamHandlers {
      onEvent: (event: StreamEvent) => void;
      onError: () => void;
      onOpen: () => void;
}

export interface StreamSource {
      start(handlers: StreamHandlers): void;
      close(): void;
}

/**
 * A reconnectable SSE source factory. `lastEventId` is the byte offset the
 * backend streams from on reconnect (Last-Event-ID semantics, T2.5/T4.3).
 */
export type StreamSourceFactory = (lastEventId: string) => StreamSource;

/** Native EventSource adapter for the backend /stream/log endpoint. */
export function nativeEventSourceFactory(url: string): StreamSourceFactory {
      return () => {
            let source: EventSource | null = null;
            return {
                  start(handlers: StreamHandlers) {
                        const es = new EventSource(url);
                        source = es;
                        es.onopen = () => handlers.onOpen();
                        es.onerror = () => handlers.onError();
                        es.addEventListener("progress", (event) => {
                              handlers.onEvent({
                                    event: "progress",
                                    data: (event as MessageEvent).data,
                              });
                        });
                        es.addEventListener("log", (event) => {
                              handlers.onEvent({
                                    event: "log",
                                    data: (event as MessageEvent).data,
                                    id:
                                          (event as MessageEvent).lastEventId ||
                                          undefined,
                              });
                        });
                  },
                  close() {
                        source?.close();
                  },
            };
      };
}

export function parseProgress(data: string): ProgressData {
      return JSON.parse(data) as ProgressData;
}

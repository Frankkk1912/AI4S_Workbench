import { useEffect, useRef, useState } from "react";
import type { ProgressData } from "../api/types";
import {
  parseProgress,
  type StreamEvent,
  type StreamSourceFactory,
} from "../api/stream";

export interface LiveLogProps {
  createSource: StreamSourceFactory;
  reconnectDelayMs?: number;
  onProgress?: (progress: ProgressData) => void;
}

export function LiveLog({
  createSource,
  reconnectDelayMs = 2000,
  onProgress,
}: LiveLogProps) {
  const [lines, setLines] = useState<string[]>([]);
  const [paused, setPaused] = useState(false);
  const [reconnecting, setReconnecting] = useState(false);
  const [connected, setConnected] = useState(false);
  const lastEventIdRef = useRef("");
  const pausedRef = useRef(false);
  const pendingRef = useRef<string[]>([]);

  useEffect(() => {
    pausedRef.current = paused;
  }, [paused]);

  useEffect(() => {
    let source: ReturnType<StreamSourceFactory> | null = null;
    let disposed = false;
    let timer: ReturnType<typeof setTimeout> | null = null;

    const connect = () => {
      if (disposed) return;
      source = createSource(lastEventIdRef.current);
      source.start({
        onOpen: () => {
          setReconnecting(false);
          setConnected(true);
        },
        onError: () => {
          setConnected(false);
          setReconnecting(true);
          source?.close();
          if (timer) clearTimeout(timer);
          timer = setTimeout(connect, reconnectDelayMs);
        },
        onEvent: (event: StreamEvent) => {
          if (event.event === "log" && event.data) {
            if (event.id) lastEventIdRef.current = event.id;
            if (pausedRef.current) {
              pendingRef.current.push(event.data);
            } else {
              setLines((existing) => [...existing, event.data]);
            }
          } else if (event.event === "progress") {
            try {
              onProgress?.(parseProgress(event.data));
            } catch {
              // Ignore a malformed progress frame; the log stream still renders.
            }
          }
        },
      });
    };

    connect();
    return () => {
      disposed = true;
      if (timer) clearTimeout(timer);
      source?.close();
    };
  }, [createSource, reconnectDelayMs, onProgress]);

  const togglePause = () => {
    if (!paused) {
      setPaused(true);
      return;
    }
    const buffered = pendingRef.current;
    pendingRef.current = [];
    setLines((existing) => [...existing, ...buffered]);
    setPaused(false);
  };

  return (
    <section className="live-log" data-testid="live-log">
      <div className="log-toolbar">
        <h3>实时日志</h3>
        <span className="log-connection" data-testid="log-connection">
          {reconnecting ? "断线，正在重连…" : connected ? "已连接" : "连接中…"}
        </span>
        <button type="button" onClick={togglePause} data-testid="log-pause">
          {paused ? "恢复" : "暂停"}
        </button>
      </div>
      <pre className="log-output" data-testid="log-output">
        {lines.join("\n")}
      </pre>
    </section>
  );
}

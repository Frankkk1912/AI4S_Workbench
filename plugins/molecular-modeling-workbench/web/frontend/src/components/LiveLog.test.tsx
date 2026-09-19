import { describe, expect, it, vi } from "vitest";
import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { LiveLog } from "./LiveLog";
import type {
  StreamEvent,
  StreamHandlers,
  StreamSource,
  StreamSourceFactory,
} from "../api/stream";
import type { ProgressData } from "../api/types";

interface MockSource {
  factory: StreamSourceFactory;
  calls: string[];
  emit: (event: StreamEvent) => void;
  error: () => void;
  open: () => void;
}

function createMockSource(): MockSource {
  const calls: string[] = [];
  let handlers: StreamHandlers | null = null;
  const factory: StreamSourceFactory = (lastEventId: string): StreamSource => {
    calls.push(lastEventId);
    return {
      start(next: StreamHandlers) {
        handlers = next;
      },
      close() {
        handlers = null;
      },
    };
  };
  return {
    factory,
    calls,
    emit: (event) => handlers?.onEvent(event),
    error: () => handlers?.onError(),
    open: () => handlers?.onOpen(),
  };
}

describe("LiveLog", () => {
  it("renders log lines and resumes with Last-Event-ID after an error", async () => {
    const mock = createMockSource();
    render(<LiveLog createSource={mock.factory} reconnectDelayMs={5} />);
    act(() => mock.open());
    act(() => mock.emit({ event: "log", data: "hello", id: "10" }));
    expect(screen.getByTestId("log-output")).toHaveTextContent("hello");

    act(() => mock.error());
    expect(screen.getByTestId("log-connection")).toHaveTextContent(
      "断线，正在重连",
    );

    await waitFor(() => expect(mock.calls[mock.calls.length - 1]).toBe("10"));
  });

  it("pauses and resumes log appending", () => {
    const mock = createMockSource();
    render(<LiveLog createSource={mock.factory} />);
    act(() => mock.open());
    act(() => mock.emit({ event: "log", data: "line1", id: "1" }));
    expect(screen.getByTestId("log-output")).toHaveTextContent("line1");

    fireEvent.click(screen.getByTestId("log-pause"));
    act(() => mock.emit({ event: "log", data: "line2", id: "2" }));
    expect(screen.getByTestId("log-output")).not.toHaveTextContent("line2");

    fireEvent.click(screen.getByTestId("log-pause"));
    expect(screen.getByTestId("log-output")).toHaveTextContent("line2");
  });

  it("forwards progress frames to onProgress", () => {
    const mock = createMockSource();
    const onProgress = vi.fn();
    render(<LiveLog createSource={mock.factory} onProgress={onProgress} />);
    act(() => mock.open());
    const progress: ProgressData = {
      checked_at: "now",
      step: 1,
      total_steps: 100,
      percent: 1,
      ns_per_day: null,
      eta: "unavailable",
      stale: false,
      source: "monitoring",
    };
    act(() => mock.emit({ event: "progress", data: JSON.stringify(progress) }));
    expect(onProgress).toHaveBeenCalledWith(
      expect.objectContaining({ step: 1, source: "monitoring" }),
    );
  });
});

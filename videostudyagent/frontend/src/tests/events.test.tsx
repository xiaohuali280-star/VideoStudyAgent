import { act, renderHook } from "@testing-library/react";
import { EventTracker, SSEParser, useOperationEvents } from "../hooks/useOperationEvents";

test("SSE parsing supports UTF8 split chunks, CRLF, comments and multiple data lines", () => {
  const frames: { event: string; data: string; id: string }[] = [];
  const parser = new SSEParser(frame => frames.push(frame)), decoder = new TextDecoder();
  const bytes = new TextEncoder().encode(': heartbeat\r\nid: 2\r\nevent: operation\r\ndata: {"text":\r\ndata: "字幕 -0.1"}\r\n\r\n');
  for (const byte of bytes) parser.feed(decoder.decode(new Uint8Array([byte]), { stream: true }));
  expect(frames).toHaveLength(1); expect(frames[0].id).toBe("2");
  expect(JSON.parse(frames[0].data).text).toBe("字幕 -0.1");
});

test("deduplicates events and rejects stale attempts/revisions while honoring reset", () => {
  const tracker = new EventTracker();
  const event = { event_id: 3, task_id: "course", operation_id: "op", attempt: 2, state_revision: 5, stage: "review", status: "running" };
  expect(tracker.accept(event, "course")).toBe(true);
  expect(tracker.accept(event, "course")).toBe(false);
  expect(tracker.accept({ ...event, event_id: 4, attempt: 1 }, "course")).toBe(false);
  expect(tracker.accept({ ...event, event_id: 5, state_revision: 4 }, "course")).toBe(false);
  expect(tracker.accept({ ...event, event_id: 6, task_id: "other" }, "course")).toBe(false);
  expect(tracker.snapshot({ cursor: 2, operations: [] }, "course")).toBe(false);
  expect(tracker.snapshot({ cursor: 8, operations: [] }, "course", true)).toBe(true);
  expect(tracker.accept({ ...event, event_id: 9, state_revision: 6 }, "course")).toBe(true);
});

test.each([401, 403, 404, 422])("HTTP %s stops streaming without endless reconnect", async status => {
  const mocked = vi.fn().mockResolvedValue({ status, ok: false }); vi.stubGlobal("fetch", mocked);
  const { result, unmount } = renderHook(() => useOperationEvents("course", vi.fn()));
  await act(async () => {});
  expect(result.current.mode).toBe("stopped"); expect(mocked).toHaveBeenCalledTimes(1); unmount();
});

test("temporary failure falls back to polling and unmount aborts reconnect", async () => {
  vi.useFakeTimers();
  const mocked = vi.fn().mockResolvedValue({ status: 503, ok: false }); vi.stubGlobal("fetch", mocked);
  const { result, unmount } = renderHook(() => useOperationEvents("course", vi.fn()));
  await act(async () => { await vi.advanceTimersByTimeAsync(0); });
  expect(result.current.mode).toBe("polling");
  await act(async () => { await vi.advanceTimersByTimeAsync(1000); });
  expect(mocked).toHaveBeenCalledTimes(2);
  unmount(); await act(async () => { await vi.advanceTimersByTimeAsync(30000); });
  expect(mocked).toHaveBeenCalledTimes(2); vi.useRealTimers();
});

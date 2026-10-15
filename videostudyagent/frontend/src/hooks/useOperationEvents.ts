import { useEffect, useRef, useState } from "react";

export type LiveEvent = { event_id: number; task_id: string; operation_id: string; attempt: number; state_revision: number; stage: string; status: string; completed_units?: number | null; total_units?: number | null };
type Frame = { event: string; id: string; data: string };

export class SSEParser {
  private buffer = "";
  private frame: Frame = { event: "message", id: "", data: "" };
  constructor(private deliver: (frame: Frame) => void) {}
  feed(text: string) {
    this.buffer += text;
    if (this.buffer.length > 262144) throw new Error("STREAM_LIMIT");
    let newline: number;
    while ((newline = this.buffer.indexOf("\n")) >= 0) {
      const line = this.buffer.slice(0, newline).replace(/\r$/, "");
      this.buffer = this.buffer.slice(newline + 1);
      if (!line) {
        if (this.frame.data) this.deliver({ ...this.frame, data: this.frame.data.slice(0, -1) });
        this.frame = { event: "message", id: "", data: "" }; continue;
      }
      if (line.startsWith(":")) continue;
      const colon = line.indexOf(":"), field = colon < 0 ? line : line.slice(0, colon);
      const value = colon < 0 ? "" : line.slice(colon + 1).replace(/^ /, "");
      if (field === "event") this.frame.event = value;
      else if (field === "id" && !value.includes("\0")) this.frame.id = value;
      else if (field === "data") this.frame.data += value + "\n";
      if (this.frame.data.length > 262144) throw new Error("STREAM_LIMIT");
    }
  }
}

export class EventTracker {
  cursor = 0;
  private versions = new Map<string, { attempt: number; revision: number }>();
  accept(event: LiveEvent, taskId: string) {
    if (event.task_id !== taskId || !Number.isSafeInteger(event.event_id) || event.event_id <= this.cursor ||
        !Number.isSafeInteger(event.attempt) || event.attempt < 1 || !Number.isSafeInteger(event.state_revision) || event.state_revision < 0) return false;
    const old = this.versions.get(event.operation_id);
    this.cursor = event.event_id;
    if (old && (event.attempt < old.attempt || (event.attempt === old.attempt && event.state_revision <= old.revision))) return false;
    this.versions.set(event.operation_id, { attempt: event.attempt, revision: event.state_revision });
    return true;
  }
  snapshot(data: { cursor: number; operations: { id: string; task_id: string; attempt: number; event_revision: number }[] }, taskId: string, reset = false) {
    if (!Number.isSafeInteger(data.cursor) || data.cursor < 0 || (!reset && data.cursor < this.cursor) || !Array.isArray(data.operations)) return false;
    if (reset) this.versions.clear();
    this.cursor = data.cursor;
    for (const op of data.operations) if (op.task_id === taskId) this.versions.set(op.id, { attempt: op.attempt, revision: op.event_revision });
    return true;
  }
}

function pause(ms: number, signal: AbortSignal) {
  return new Promise<void>(resolve => {
    const done = () => { clearTimeout(timer); signal.removeEventListener("abort", done); resolve(); };
    const timer = setTimeout(done, ms); signal.addEventListener("abort", done, { once: true });
    if (signal.aborted) done();
  });
}

export function useOperationEvents(id: string, onChange: () => void) {
  const callback = useRef(onChange); callback.current = onChange;
  const [mode, setMode] = useState<"connecting" | "live" | "polling" | "stopped">("connecting");
  const [latest, setLatest] = useState<LiveEvent>();
  useEffect(() => {
    const lifetime = new AbortController(), tracker = new EventTracker();
    let active: AbortController | null = null, notification: ReturnType<typeof setTimeout> | undefined;
    setMode("connecting"); setLatest(undefined);
    const notify = () => {
      if (notification) clearTimeout(notification);
      notification = setTimeout(() => {
        if (lifetime.signal.aborted) return;
        callback.current(); window.dispatchEvent(new CustomEvent("vsa:operation-change", { detail: { id } }));
      }, 120);
    };
    async function connect() {
      let failures = 0;
      while (!lifetime.signal.aborted && failures < 5) {
        const current = new AbortController(); active = current;
        let idle = setTimeout(() => current.abort(), 15000);
        try {
          const response = await fetch(`/api/tasks/${encodeURIComponent(id)}/events${tracker.cursor ? `?since=${tracker.cursor}` : ""}`, { signal: current.signal, headers: { Accept: "text/event-stream" } });
          if (lifetime.signal.aborted) return;
          if ([401, 403, 404, 422].includes(response.status)) { setMode("stopped"); return; }
          if (!response.ok || !response.body || !response.headers?.get("content-type")?.includes("text/event-stream")) throw new Error("STREAM_UNAVAILABLE");
          setMode("live");
          const decoder = new TextDecoder(), reader = response.body.getReader();
          const parser = new SSEParser(frame => {
            if (lifetime.signal.aborted) return;
            const value = JSON.parse(frame.data);
            if (frame.event === "operation" && tracker.accept(value, id)) { setLatest(value); notify(); }
            else if ((frame.event === "snapshot" || frame.event === "reset") && tracker.snapshot(value, id, frame.event === "reset")) notify();
          });
          try {
            while (!lifetime.signal.aborted) {
              clearTimeout(idle); idle = setTimeout(() => current.abort(), 35000);
              const chunk = await reader.read(); if (chunk.done) break;
              failures = 0; parser.feed(decoder.decode(chunk.value, { stream: true }));
            }
          } finally { void reader.cancel().catch(() => {}); reader.releaseLock(); }
          if (lifetime.signal.aborted) return;
          throw new Error("STREAM_CLOSED");
        } catch {
          if (lifetime.signal.aborted) return;
          setMode("polling"); failures += 1;
        } finally { clearTimeout(idle); current.abort(); }
        await pause(Math.min(10000, 1000 * 2 ** (failures - 1)), lifetime.signal);
      }
    }
    void connect();
    return () => { lifetime.abort(); active?.abort(); if (notification) clearTimeout(notification); };
  }, [id]);
  return { mode, latest };
}

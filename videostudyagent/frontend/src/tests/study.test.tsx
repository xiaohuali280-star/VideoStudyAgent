import { act, fireEvent, render, renderHook, screen } from "@testing-library/react";
import { useTask } from "../hooks/useTask";
import Sources from "../components/Sources";
import type { Transcript } from "../api/client";
import { downloadExport } from "../api/client";

afterEach(() => vi.useRealTimers());
test("polls an active task and stops after reading its final result", async () => {
  vi.useFakeTimers();
  let calls = 0;
  const fetchMock = vi.fn(async (url: string) => ({ ok: true, json: async () => url.endsWith("/result") ? { task_id: "a", notes: null } : { task: { status: ++calls === 1 ? "running" : "succeeded" } } }));
  vi.stubGlobal("fetch", fetchMock);
  const { result } = renderHook(() => useTask("a", 0));
  await act(async () => { await vi.advanceTimersByTimeAsync(0); });
  expect(result.current.detail?.task.status).toBe("running");
  await act(async () => { await vi.advanceTimersByTimeAsync(2000); });
  expect(result.current.detail?.task.status).toBe("succeeded");
  await act(async () => { await vi.advanceTimersByTimeAsync(10000); });
  expect(fetchMock).toHaveBeenCalledTimes(4);
});
test("switching courses cancels the old request", async () => {
  const fetchMock = vi.fn().mockReturnValue(new Promise(() => {}));
  vi.stubGlobal("fetch", fetchMock);
  const { rerender, unmount } = renderHook(({ id }) => useTask(id, 0), { initialProps: { id: "first" } });
  const oldSignal = fetchMock.mock.calls[0][1].signal;
  rerender({ id: "second" });
  expect(oldSignal.aborted).toBe(true);
  unmount();
  expect(fetchMock.mock.calls[1][1].signal.aborted).toBe(true);
});
test("source jump preserves milliseconds rather than rounded display time", () => {
  const transcript = { segments: [{ id: "seg", start_ms: 1234, end_ms: 4567, text: "source" }] } as Transcript;
  const seek = vi.fn(); render(<Sources ids={["seg"]} transcript={transcript} onSeek={seek} />);
  fireEvent.click(screen.getByRole("button", { name: "跳转至 00:01" }));
  expect(seek).toHaveBeenCalledWith(1234);
});
test("failed download reports a safe error instead of saving an error response", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false, status: 409, json: async () => ({ schema_version: "1.0", error: { code: "RESULT_NOT_READY", message: "private detail" } }) }));
  await expect(downloadExport("a", "quiz.json")).rejects.toThrow("对应学习资料尚未生成");
});

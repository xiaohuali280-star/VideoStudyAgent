import { fireEvent, render, screen } from "@testing-library/react";
import EvidenceSearch from "../components/EvidenceSearch";

test("search pins the course snapshot and displays actual source time", async () => {
  const seek = vi.fn();
  const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    if (url.endsWith("study-state")) return { ok: true, json: async () => ({ transcript_snapshot_id: "source", context_snapshot_id: null }) };
    const body = JSON.parse(init!.body as string);
    expect(body.snapshot_id).toBe("source"); expect(body.snapshot_type).toBe("transcript");
    expect(body.query).toBe("梯度"); expect(body.top_k).toBe(5);
    return { ok: true, json: async () => ({ hits: [{ task_id: "course", snapshot_id: "source", source_type: "transcript", source_id: "s1", start_ms: 1234, raw_text: "梯度 -0.1" }], warnings: [] }) };
  });
  vi.stubGlobal("fetch", fetchMock);
  render(<EvidenceSearch id="course" onSeek={seek} />);
  fireEvent.change(screen.getByLabelText("课程术语"), { target: { value: "梯度" } });
  fireEvent.click(screen.getByRole("button", { name: "查找课程证据" }));
  fireEvent.click(await screen.findByRole("button", { name: "00:01" }));
  expect(seek).toHaveBeenCalledWith(1234);
  expect(screen.getByText("梯度 -0.1")).toBeInTheDocument();
});

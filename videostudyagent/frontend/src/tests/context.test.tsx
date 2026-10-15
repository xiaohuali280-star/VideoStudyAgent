import { fireEvent, render, screen } from "@testing-library/react";
import { EvidenceLinks } from "../components/ContextEvidence";
import type { EvidenceRef, VideoContext } from "../components/ContextEvidence";

test("OCR references jump to actual frame milliseconds and reject another snapshot", () => {
  const context = { id: "snapshot", task_id: "course", frames: [{ id: "frame", timestamp_ms: 1234 }], observations: [{ id: "ocr", frame_id: "frame" }], transcript: null } as VideoContext;
  const ref: EvidenceRef = { task_id: "course", snapshot_id: "snapshot", source_type: "ocr", source_id: "ocr", quote: "rate -0.1" };
  const seek = vi.fn();
  const { rerender } = render(<EvidenceLinks refs={[ref]} context={context} onSeek={seek} />);
  fireEvent.click(screen.getByRole("button", { name: "画面 00:01" }));
  expect(seek).toHaveBeenCalledWith(1234);
  rerender(<EvidenceLinks refs={[{ ...ref, snapshot_id: "other" }]} context={context} onSeek={seek} />);
  expect(screen.queryByRole("button")).toBeNull();
});

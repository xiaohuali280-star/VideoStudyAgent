import type { components } from "../api/schema";
import { clock } from "./Sources";

export type VideoContext = components["schemas"]["VideoContextSnapshot"];
export type EvidenceRef = components["schemas"]["EvidenceRef"];

export function EvidenceLinks({ refs, context, onSeek }: { refs: EvidenceRef[]; context?: VideoContext | null; onSeek?: (ms: number) => void }) {
  return <div className="source-links">{refs.map((ref, index) => {
    if (!context || ref.task_id !== context.task_id || ref.snapshot_id !== context.id) return <span key={index}>{ref.source_type === "ocr" ? "画面文字" : "字幕"}：{ref.quote}</span>;
    const observation = context.observations.find(o => o.id === ref.source_id);
    const frame = context.frames.find(f => f.id === observation?.frame_id);
    const time = ref.source_type === "ocr" ? frame?.timestamp_ms : context.transcript?.segments.find(s => s.id === ref.source_id)?.start_ms;
    return <span key={index}>{time !== undefined && onSeek ? <button type="button" onClick={() => onSeek(time)}>{ref.source_type === "ocr" ? "画面" : "字幕"} {clock(time)}</button> : <span>{ref.source_type === "ocr" ? "画面文字" : "字幕"}</span>} <q>{ref.quote}</q></span>;
  })}</div>;
}

export default function ContextEvidence({ context, onSeek }: { context: VideoContext; onSeek?: (ms: number) => void }) {
  return <details className="context-evidence"><summary>课程来源与画面证据</summary>
    <p>字幕：{context.branch_statuses.transcript === "succeeded" ? "已准备" : "无可用语音或字幕"} · 画面文字：{context.branch_statuses.ocr === "succeeded" ? "已识别" : context.branch_statuses.ocr === "disabled" ? "未启用" : "未完成"}</p>
    {context.warnings.length > 0 && <p role="status">部分来源不可用：{context.warnings.join("、")}</p>}
    <p className="muted">画面文字可能识别有误，请结合原画面核对数字和公式。</p>
    {context.frames.map(frame => <figure key={frame.id}><img loading="lazy" style={{ maxWidth: "100%" }} alt={`课程画面 ${clock(frame.timestamp_ms)}`} src={`/api/tasks/${context.task_id}/contexts/${context.id}/frames/${frame.id}`} />
      <figcaption>{onSeek ? <button onClick={() => onSeek(frame.timestamp_ms)}>{clock(frame.timestamp_ms)}</button> : clock(frame.timestamp_ms)}{context.observations.filter(o => o.frame_id === frame.id).map(o => <p key={o.id}>{o.raw_text}</p>)}</figcaption></figure>)}
  </details>;
}

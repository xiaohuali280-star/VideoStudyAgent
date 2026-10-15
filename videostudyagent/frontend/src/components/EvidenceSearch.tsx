import { useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";
import { friendlyError, getStudyState, jsonRequest } from "../api/client";
import type { components } from "../api/schema";
import { clock } from "./Sources";

export default function EvidenceSearch({ id, onSeek }: { id: string; onSeek?: (ms: number) => void }) {
  const [query, setQuery] = useState(""), [source, setSource] = useState("all");
  const [start, setStart] = useState(""), [end, setEnd] = useState("");
  const [result, setResult] = useState<components["schemas"]["EvidenceSearchResult"]>();
  const [busy, setBusy] = useState(false), [error, setError] = useState("");
  const controller = useRef<AbortController | null>(null);
  useEffect(() => { setResult(undefined); setBusy(false); setError(""); return () => controller.current?.abort(); }, [id]);
  async function search(event: FormEvent) {
    event.preventDefault(); if (!query.trim() || busy) return;
    controller.current?.abort(); const current = new AbortController(); controller.current = current;
    setBusy(true); setError("");
    try {
      const state = await getStudyState(id);
      if (current.signal.aborted) return;
      const snapshot = state.context_snapshot_id || state.transcript_snapshot_id;
      if (!snapshot) { setError("课程来源尚未准备好。"); return; }
      const next = await jsonRequest<components["schemas"]["EvidenceSearchResult"]>(`/api/tasks/${id}/evidence/search`, {
        method: "POST", signal: current.signal, headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ snapshot_id: snapshot, snapshot_type: state.context_snapshot_id ? "context" : "transcript", query: query.trim(), top_k: 5,
          source_types: source === "all" ? ["transcript", "ocr"] : [source], start_ms: start === "" ? null : Math.round(Number(start) * 1000), end_ms: end === "" ? null : Math.round(Number(end) * 1000) }),
      });
      if (!current.signal.aborted) setResult(next);
    } catch (e) { if (!current.signal.aborted) setError(friendlyError(e)); }
    finally { if (!current.signal.aborted) setBusy(false); }
  }
  return <details className="evidence-search"><summary>在课程原文中查找</summary><p className="muted">按术语查找字幕与画面文字；不调用模型。结果属于当前课程来源版本。</p>
    <form onSubmit={event => void search(event)}><label>课程术语<input aria-label="课程术语" maxLength={300} value={query} onChange={e => setQuery(e.target.value)} /></label>
      <label>证据来源<select aria-label="证据来源" value={source} onChange={e => setSource(e.target.value)}><option value="all">全部来源</option><option value="transcript">字幕</option><option value="ocr">画面文字</option></select></label>
      <label>开始秒数（可选）<input type="number" min="0" step="0.001" value={start} onChange={e => setStart(e.target.value)} /></label><label>结束秒数（可选）<input type="number" min="0" step="0.001" value={end} onChange={e => setEnd(e.target.value)} /></label>
      <button disabled={busy || !query.trim()}>{busy ? "查找中…" : "查找课程证据"}</button></form>
    {result?.warnings.length ? <p role="status">索引暂不可用，已在本课程原始资料中查找。{result.warnings.includes("RETRIEVAL_SCAN_LIMIT") && "本次未搜索全部资料，请缩小时间范围。"}</p> : null}
    {result?.hits.map(hit => <article key={`${hit.source_type}-${hit.source_id}`}><p>{hit.source_type === "ocr" ? "画面文字" : "字幕"} · {onSeek ? <button onClick={() => onSeek(hit.start_ms)}>{clock(hit.start_ms)}</button> : clock(hit.start_ms)} · 来源版本 {hit.snapshot_id.slice(0, 8)}</p><p>{hit.raw_text}</p>
      {hit.frame_id && <img loading="lazy" style={{ maxWidth: "100%" }} alt={`证据画面 ${clock(hit.start_ms)}`} src={`/api/tasks/${id}/contexts/${hit.snapshot_id}/frames/${hit.frame_id}`} />}</article>)}
    {result && !result.hits.length && <p>未找到匹配证据，可换一个课程术语或缩小范围。</p>}{error && <p role="alert">{error}</p>}
  </details>;
}

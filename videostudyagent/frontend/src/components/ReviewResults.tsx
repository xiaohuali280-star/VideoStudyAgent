import { useState } from "react";
import { friendlyError, jsonRequest } from "../api/client";
import type { components } from "../api/schema";

export default function ReviewResults({ id, operationId }: { id: string; operationId: string }) {
  const [reports, setReports] = useState<components["schemas"]["ReviewReport"][]>();
  const [error, setError] = useState("");
  async function load() {
    try { setReports(await jsonRequest(`/api/tasks/${id}/operations/${operationId}/reviews`)); }
    catch (e) { setError(friendlyError(e)); }
  }
  return <details><summary onClick={() => { if (!reports) void load(); }}>查看发布审核</summary>
    {reports?.length === 0 && <p>此操作没有发布审核记录；历史资料保持原样。</p>}
    {reports?.map(r => <article key={r.id}><p>{r.target_kind === "notes" ? "笔记" : "自测"} · {r.policy === "hard_only" ? "结构与引用校验（语义未验证）" : "内容审核"} · {{ passed: "通过", failed: "未通过", uncertain: "无法判定" }[r.status]} · 第 {r.round + 1} 轮</p>
      {r.issues.map((issue, index) => <p key={index}>{issue.target_id}：{issue.suggestion}</p>)}</article>)}
    {error && <p role="alert">{error}</p>}
  </details>;
}

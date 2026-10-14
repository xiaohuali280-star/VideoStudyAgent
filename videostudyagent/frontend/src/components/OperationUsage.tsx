import { useEffect, useState } from "react";
import { friendlyError, getOperations, jsonRequest } from "../api/client";
import type { StudyOperation } from "../api/client";

export default function OperationUsage({ id }: { id: string }) {
  const [ops, setOps] = useState<StudyOperation[]>([]), [error, setError] = useState("");
  useEffect(() => {
    let stopped = false;
    const refresh = async () => { try { const all: StudyOperation[] = []; let page: StudyOperation[];
      do { page = await jsonRequest<StudyOperation[]>(`/api/tasks/${id}/operations?limit=100&offset=${all.length}`); all.push(...page); } while (page.length === 100);
      if (!stopped) setOps(all);
    } catch (e) { if (!stopped) setError(friendlyError(e)); } };
    void refresh(); const timer = setInterval(() => void refresh(), 2000);
    return () => { stopped = true; clearInterval(timer); };
  }, [id]);
  const usages = ops.flatMap(op => [op.usage, ...(op.attempts || []).map(a => a.usage)]);
  const total = usages.reduce((sum, u) => sum + u.tokens_reserved, 0);
  async function action(op: StudyOperation, name: "retry" | "cancel") {
    try { await jsonRequest(`/api/tasks/${id}/operations/${op.id}/${name}`, { method: "POST" }); setOps(await getOperations(id)); }
    catch (e) { setError(friendlyError(e)); }
  }
  return <details className="usage-panel"><summary>操作记录与预算 · 累计预留 {total.toLocaleString()} tokens</summary>
    <p className="muted">预留包含可能的重试和最大输出，不等于账单。未知的实际用量不会显示为 0。失败后仅手动重试。</p>
    {ops.map(op => <div key={op.id}><strong>{op.request.kind} · {op.status} · 第 {op.attempt} 次</strong><p>本次预留 {op.usage.tokens_reserved.toLocaleString()} / {op.usage.token_limit.toLocaleString()} tokens；请求 {op.usage.requests_reserved} / {op.usage.request_limit}；实际输入/输出：{op.usage.input_tokens == null ? "未知" : op.usage.input_tokens} / {op.usage.output_tokens == null ? "未知" : op.usage.output_tokens}</p>
      {op.error && <p>{op.error.message}</p>}
      {["queued", "running"].includes(op.status) && <button onClick={() => void action(op, "cancel")}>取消操作</button>}
      {op.request.kind !== "initial_study" && op.status === "failed" && op.error?.retryable && <button onClick={() => void action(op, "retry")}>重试此操作</button>}
    </div>)}{error && <p role="alert">{error}</p>}
  </details>;
}

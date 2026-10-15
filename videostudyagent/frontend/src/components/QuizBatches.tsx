import { useEffect, useRef, useState } from "react";
import { friendlyError, getOperations, getStudyState, jsonRequest, submitOperation } from "../api/client";
import type { QuizDocument } from "../api/client";

type Batch = { id: string; sequence: number; difficulty: "easy" | "medium" | "hard"; question_count: number };
export default function QuizBatches({ id, language, difficulty, onSelected }: { id: string; language: string; difficulty: Batch["difficulty"]; onSelected: (quiz: QuizDocument, batchId: string) => void }) {
  const [batches, setBatches] = useState<Batch[]>([]), [selected, setSelected] = useState("");
  const [level, setLevel] = useState(difficulty), [busy, setBusy] = useState(false), [error, setError] = useState("");
  const [page, setPage] = useState(0);
  const callback = useRef(onSelected), selection = useRef("");
  const loaded = useRef("");
  callback.current = onSelected; selection.current = selected;
  useEffect(() => {
    let stopped = false;
    const refresh = async () => {
      try {
        const [items, ops] = await Promise.all([jsonRequest<Batch[]>(`/api/tasks/${id}/quiz-batches?offset=${page * 20}`), getOperations(id)]);
        if (!stopped) {
          setBatches(items); setBusy(ops.some(op => ["queued", "running"].includes(op.status)));
          if (!selection.current) {
            const state = await getStudyState(id);
            if (state.quiz_batch_id && loaded.current !== state.quiz_batch_id) {
              const document = await jsonRequest<QuizDocument>(`/api/tasks/${id}/quiz-batches/${state.quiz_batch_id}`);
              if (!stopped && !selection.current) { loaded.current = state.quiz_batch_id; callback.current(document, state.quiz_batch_id); }
            }
          }
        }
      } catch (e) { if (!stopped) setError(friendlyError(e)); }
    };
    void refresh(); const timer = setInterval(() => void refresh(), 2000);
    return () => { stopped = true; clearInterval(timer); };
  }, [id, page]);
  async function select(value: string) {
    try { const target = value || (await getStudyState(id)).quiz_batch_id; if (!target) return; const quiz = await jsonRequest<QuizDocument>(`/api/tasks/${id}/quiz-batches/${target}`); setSelected(value); loaded.current = target; onSelected(quiz, target); }
    catch (e) { setError(friendlyError(e)); }
  }
  async function regenerate() {
    setBusy(true); setError("");
    try {
      const state = await getStudyState(id);
      if ((!state.transcript_snapshot_id && !state.context_snapshot_id)) return;
      await submitOperation(id, { kind: "generate_quiz", transcript_snapshot_id: state.transcript_snapshot_id, context_snapshot_id: state.context_snapshot_id, notes_revision_id: state.notes_revision_id, options: { question_count: 5, difficulty: level, output_language: language } });
    } catch (e) { setError(friendlyError(e)); setBusy(false); }
  }
  return <div className="batch-controls">
    <label>自测历史 <select aria-label="自测历史" value={selected} onChange={e => void select(e.target.value)}><option value="">当前批次</option>{batches.map(b => <option key={b.id} value={b.id}>第 {b.sequence} 批 · {b.question_count} 题 · {b.difficulty}</option>)}</select></label>
    <label>换题难度 <select aria-label="换题难度" value={level} onChange={e => setLevel(e.target.value as Batch["difficulty"])}><option value="easy">基础理解</option><option value="medium">理解与应用</option><option value="hard">综合分析</option></select></label>
    <button disabled={busy} onClick={() => void regenerate()}>{busy ? "正在处理…" : "换一批（5 题）"}</button>
    {page > 0 && <button onClick={() => setPage(p => p - 1)}>上一页</button>}{batches.length === 20 && <button onClick={() => setPage(p => p + 1)}>下一页</button>}
    {error && <p role="alert">{error}</p>}
  </div>;
}

import { useEffect, useState, useRef } from "react";
import { friendlyError, getOperations, getStudyState, jsonRequest, submitOperation } from "../api/client";
import type { CourseStudyState, StudyOperation } from "../api/client";

export default function StudyActions({ id, onCompleted, options }: { id: string; onCompleted: () => void; options: { difficulty: "easy" | "medium" | "hard"; output_language: string } }) {
  const [state, setState] = useState<CourseStudyState>();
  const [operations, setOperations] = useState<StudyOperation[]>([]);
  const [error, setError] = useState(""), [sending, setSending] = useState(false);
  const previous = useRef(new Map<string, string>()), callback = useRef(onCompleted);
  callback.current = onCompleted;
  useEffect(() => {
    let stopped = false, timer: ReturnType<typeof setTimeout>;
    async function refresh() {
      try {
        const [nextState, nextOps] = await Promise.all([getStudyState(id), getOperations(id)]);
        if (stopped) return;
        if (nextOps.some(op => ["running", "queued"].includes(previous.current.get(op.id) || "") && !["running", "queued"].includes(op.status))) callback.current();
        previous.current = new Map(nextOps.map(op => [op.id, op.status]));
        setState(nextState); setOperations(nextOps); setError("");
      } catch (failure) { if (!stopped) setError(friendlyError(failure)); }
      if (!stopped) timer = setTimeout(refresh, 2000);
    }
    void refresh(); return () => { stopped = true; clearTimeout(timer); };
  }, [id]);
  const busy = sending || operations.some(op => ["queued", "running"].includes(op.status));
  async function generate(kind: "generate_notes" | "generate_quiz") {
    if (!state?.transcript_snapshot_id) return;
    setSending(true); setError("");
    try {
      const saved = kind === "generate_notes" ? await jsonRequest<{ preferences: Extract<StudyOperation["request"], { kind: "generate_notes" }>["preferences"] } | null>(`/api/tasks/${id}/note-preferences`) : null;
      const action = { kind, transcript_snapshot_id: state.transcript_snapshot_id,
        ...(kind === "generate_quiz" ? { notes_revision_id: state.notes_revision_id, options: { question_count: 5, difficulty: options.difficulty, output_language: options.output_language } } : { output_language: options.output_language, preferences: saved?.preferences || { detail: "standard", style: "outline", include_examples: false, highlight_formulas: true, focus_topics: [], custom_instructions: "" } }) } as StudyOperation["request"];
      const op = await submitOperation(id, action);
      setOperations(ops => [op, ...ops]); previous.current.set(op.id, "queued");
    } catch (failure) { setError(friendlyError(failure)); }
    finally { setSending(false); }
  }
  return <div className="study-actions">
    {state?.transcript_snapshot_id && !state.notes_revision_id && <button disabled={busy} onClick={() => void generate("generate_notes")}>补生成笔记</button>}
    {state?.transcript_snapshot_id && !state.quiz_batch_id && <button disabled={busy} onClick={() => void generate("generate_quiz")}>生成 5 道自测题</button>}
    {busy && <p className="muted" role="status">操作已排队或正在处理，原有资料仍可阅读。</p>}
    {error && <p role="alert">{error}</p>}
    {operations[0]?.status === "failed" && <p role="alert">{operations[0].error?.message}</p>}
  </div>;
}

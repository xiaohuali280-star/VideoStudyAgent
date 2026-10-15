import { useEffect, useState } from "react";
import { downloadExport, friendlyError, getStudyState, jsonRequest, submitOperation } from "../api/client";
import type { NotesDocument, StudyOperation } from "../api/client";
import NotesViewer from "./NotesViewer";

type Pref = Extract<StudyOperation["request"], { kind: "revise_notes" }>["preferences"];
type Revision = { id: string; status: "draft" | "published"; discarded: boolean; parent_revision_id?: string | null; created_at: string };
const defaults: Pref = { detail: "standard", style: "outline", include_examples: false, highlight_formulas: true, focus_topics: [], custom_instructions: "" };
export default function NoteRevisions({ id, notes, onApplied }: { id: string; notes: NotesDocument; onApplied: () => void }) {
  const [preferences, setPreferences] = useState<Pref>(defaults), [prefRevision, setPrefRevision] = useState(0);
  const [revisions, setRevisions] = useState<Revision[]>([]), [selected, setSelected] = useState<Revision>(), [preview, setPreview] = useState<NotesDocument>();
  const [chapters, setChapters] = useState<string[]>([]), [instruction, setInstruction] = useState("按课程偏好重新整理笔记");
  const [error, setError] = useState(""), [busy, setBusy] = useState(false), [page, setPage] = useState(0);
  useEffect(() => { let active = true; void jsonRequest<{ revision: number; preferences: Pref } | null>(`/api/tasks/${id}/note-preferences`).then(p => { if (active && p) { setPreferences(p.preferences); setPrefRevision(p.revision); } }).catch(e => { if (active) setError(friendlyError(e)); }); return () => { active = false; }; }, [id]);
  useEffect(() => { let active = true; const refresh = async () => { try { const items = await jsonRequest<Revision[]>(`/api/tasks/${id}/notes-revisions?offset=${page * 20}`); if (active) setRevisions(items); } catch (e) { if (active) setError(friendlyError(e)); } }; void refresh(); const timer = setInterval(() => void refresh(), 2000); return () => { active = false; clearInterval(timer); }; }, [id, page]);
  async function run(action: () => Promise<void>) { if (busy) return; setBusy(true); setError(""); try { await action(); } catch (e) { setError(friendlyError(e)); } finally { setBusy(false); } }
  async function save() { const value = await jsonRequest<{ revision: number }>(`/api/tasks/${id}/note-preferences`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ expected_revision: prefRevision, preferences }) }); setPrefRevision(value.revision); }
  async function revise() { const state = await getStudyState(id); if (!state.notes_revision_id || (!state.transcript_snapshot_id && !state.context_snapshot_id)) return; await submitOperation(id, { kind: "revise_notes", base_revision_id: state.notes_revision_id, transcript_snapshot_id: state.transcript_snapshot_id, context_snapshot_id: state.context_snapshot_id, chapter_ids: chapters, preferences, instruction }); }
  async function inspect(value: Revision) { const document = await jsonRequest<NotesDocument>(`/api/tasks/${id}/notes-revisions/${value.id}`); setSelected(value); setPreview(document); }
  async function apply() { if (!selected) return; const state = await getStudyState(id); await jsonRequest(`/api/tasks/${id}/notes-revisions/${selected.id}/apply`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ expected_current_id: state.notes_revision_id }) }); setPreview(undefined); setSelected(undefined); onApplied(); }
  async function discard() { if (!selected) return; await jsonRequest(`/api/tasks/${id}/notes-revisions/${selected.id}/discard`, { method: "POST" }); setSelected(undefined); setPreview(undefined); }
  return <details className="note-preferences"><summary>笔记偏好、修订与历史版本</summary>
    <p className="muted">偏好仅属于本课程。保存偏好不调用模型；生成草稿后须明确应用。不会自动更换已有自测。</p>
    <label>详细程度<select value={preferences.detail} onChange={e => setPreferences(p => ({ ...p, detail: e.target.value as Pref["detail"] }))}><option value="concise">精简</option><option value="standard">标准</option><option value="detailed">详细</option></select></label>
    <label>笔记风格<select value={preferences.style} onChange={e => setPreferences(p => ({ ...p, style: e.target.value as Pref["style"] }))}><option value="outline">提纲</option><option value="explained">讲解</option><option value="review">复习</option></select></label>
    <label><input type="checkbox" checked={preferences.include_examples} onChange={e => setPreferences(p => ({ ...p, include_examples: e.target.checked }))} />保留课程例子</label>
    <label><input type="checkbox" checked={preferences.highlight_formulas} onChange={e => setPreferences(p => ({ ...p, highlight_formulas: e.target.checked }))} />强调公式</label>
    <label>重点主题（每行一个，最多 20 个）<textarea maxLength={2000} value={preferences.focus_topics?.join("\n")} onChange={e => setPreferences(p => ({ ...p, focus_topics: e.target.value.split("\n").filter(Boolean) }))} /></label>
    <label>课程笔记偏好<textarea maxLength={2000} value={preferences.custom_instructions} onChange={e => setPreferences(p => ({ ...p, custom_instructions: e.target.value }))} /></label>
    <button disabled={busy} onClick={() => void run(save)}>保存课程偏好</button>
    <fieldset><legend>修订章节（不选表示全部）</legend>{notes.chapters.map(c => <label key={c.id}><input type="checkbox" checked={chapters.includes(c.id)} onChange={e => setChapters(ids => e.target.checked ? [...ids, c.id] : ids.filter(v => v !== c.id))} />{c.title}</label>)}</fieldset>
    <label>本次修改要求<textarea aria-label="本次修改要求" maxLength={2000} value={instruction} onChange={e => setInstruction(e.target.value)} /></label>
    <button disabled={busy || !instruction.trim() || chapters.length > 20} onClick={() => void run(revise)}>生成修改草稿</button>
    <h3>历史版本与草稿</h3>{revisions.filter(r => !r.discarded).map(r => <button key={r.id} disabled={busy} onClick={() => void run(() => inspect(r))}>{r.status === "draft" ? "草稿" : "已发布"} · {r.id.slice(0, 8)}</button>)}
    {page > 0 && <button onClick={() => setPage(p => p - 1)}>上一页</button>}{revisions.length === 20 && <button onClick={() => setPage(p => p + 1)}>下一页</button>}
    {selected && preview && <section aria-label="笔记版本预览"><h3>版本预览 · {selected.id.slice(0, 8)}</h3><div className="revision-comparison"><div><h4>当前正式笔记</h4><NotesViewer notes={notes} /></div><div><h4>所选版本</h4><NotesViewer notes={preview} /></div></div>
      <button disabled={busy} onClick={() => void run(apply)}>{selected.status === "draft" ? "应用草稿" : "恢复此版本"}</button>
      {selected.status === "draft" && <button disabled={busy} onClick={() => void run(discard)}>放弃草稿</button>}
      <button onClick={() => void run(() => downloadExport(id, "notes.md", { notes_revision_id: selected.id }))}>导出所选版本</button>
      <button onClick={() => { setSelected(undefined); setPreview(undefined); }}>关闭预览</button>
    </section>}{error && <p role="alert">{error}</p>}
  </details>;
}

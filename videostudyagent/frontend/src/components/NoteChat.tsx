import { useEffect, useRef, useState } from "react";
import { friendlyError, getStudyState, jsonRequest, submitOperation } from "../api/client";
import type { NotesDocument, Transcript } from "../api/client";
import SafeMarkdown from "./SafeMarkdown";
import Sources from "./Sources";

type Message = { id: string; role: "user" | "assistant"; content: string; sequence: number; notes_revision_id: string; citations: { segment_id: string; quote: string }[] };
export default function NoteChat({ id, notes, transcript, onSeek }: { id: string; notes: NotesDocument; transcript?: Transcript | null; onSeek?: (ms: number) => void }) {
  const [conversation, setConversation] = useState(""), [messages, setMessages] = useState<Message[]>([]);
  const [chapters, setChapters] = useState<string[]>([notes.chapters[0].id]), [text, setText] = useState("");
  const [error, setError] = useState(""), [busy, setBusy] = useState(false);
  const key = useRef(crypto.randomUUID()), sending = useRef(false);
  useEffect(() => { let active = true; void jsonRequest<{ id: string }[]>(`/api/tasks/${id}/conversations`).then(items => { if (active && items[0]) setConversation(items[0].id); }).catch(e => { if (active) setError(friendlyError(e)); }); return () => { active = false; }; }, [id]);
  useEffect(() => {
    if (!conversation) return;
    let active = true;
    const refresh = async () => { try { const all: Message[] = []; let page: Message[];
      do { page = await jsonRequest<Message[]>(`/api/tasks/${id}/conversations/${conversation}/messages?after_sequence=${all.at(-1)?.sequence || 0}&limit=100`); all.push(...page); } while (page.length === 100);
      if (active) setMessages(all);
    } catch (e) { if (active) setError(friendlyError(e)); } };
    void refresh(); const timer = setInterval(() => void refresh(), 2000);
    return () => { active = false; clearInterval(timer); };
  }, [id, conversation]);
  async function send() {
    if (sending.current || !text.trim() || !chapters.length) return;
    sending.current = true; setBusy(true); setError("");
    try {
      const state = await getStudyState(id);
      if (!state.notes_revision_id) return;
      let conv = conversation;
      if (!conv) { conv = (await jsonRequest<{ id: string }>(`/api/tasks/${id}/conversations`, { method: "POST" })).id; setConversation(conv); }
      await submitOperation(id, { kind: "chat_reply", conversation_id: conv, notes_revision_id: state.notes_revision_id, chapter_ids: chapters, message: text.trim() }, key.current);
      setText(""); key.current = crypto.randomUUID();
    } catch (e) { setError(friendlyError(e)); }
    finally { setBusy(false); sending.current = false; }
  }
  return <section className="note-chat" aria-label="笔记聊天"><h2>和课程笔记聊一聊</h2><p className="muted">回答基于所选章节，聊天不会改动正式笔记。操作进度、取消和重试见上方操作记录。</p>
    <fieldset><legend>选择讨论章节（最多 20 个）</legend>{notes.chapters.map(c => <label key={c.id}><input type="checkbox" checked={chapters.includes(c.id)} onChange={e => setChapters(ids => e.target.checked ? [...ids, c.id] : ids.filter(v => v !== c.id))} />{c.title}</label>)}</fieldset>
    <div aria-live="polite">{messages.map(m => <article key={m.id}><strong>{m.role === "user" ? "你" : "课程助教"}</strong><small> · 笔记版本 {m.notes_revision_id.slice(0, 8)}</small><SafeMarkdown content={m.content} />{m.citations.map((c, i) => <div key={i}><blockquote>{c.quote}</blockquote><Sources ids={[c.segment_id]} transcript={transcript} onSeek={onSeek} /></div>)}</article>)}</div>
    <label>向课程助教提问<textarea aria-label="向课程助教提问" maxLength={2000} value={text} onChange={e => setText(e.target.value)} /></label>
    <button disabled={busy || !text.trim() || chapters.length === 0 || chapters.length > 20} onClick={() => void send()}>{busy ? "正在提交…" : "发送问题"}</button>{error && <p role="alert">{error}</p>}
  </section>;
}

import { useRef, useState } from "react";
import { downloadExport, friendlyError, retryTask, videoURL } from "../api/client";
import type { ExportFormat } from "../api/client";
import { useTask } from "../hooks/useTask";
import NotesViewer from "./NotesViewer";
import QuizViewer from "./QuizViewer";
import { clock } from "./Sources";

export const statusLabels = { queued: "等待处理", running: "正在整理", succeeded: "已完成", failed: "处理未完成" };
const stepLabels: Record<string, string> = { load_subtitles: "读取字幕", extract_audio: "提取音频", transcribe_audio: "识别语音", generate_notes: "梳理笔记", generate_quiz: "生成自测", unknown: "检查调用" };
const exports: [ExportFormat, string, "notes" | "quiz" | "transcript"][] = [
  ["notes.md", "笔记 Markdown", "notes"], ["quiz.md", "自测 Markdown", "quiz"],
  ["quiz.json", "自测 JSON", "quiz"], ["transcript.json", "字幕 JSON", "transcript"], ["transcript.srt", "字幕 SRT", "transcript"],
];

export default function TaskView({ id, onUpdated }: { id: string; onUpdated: () => void }) {
  const [revision, setRevision] = useState(0), [tab, setTab] = useState("notes");
  const [actionError, setActionError] = useState(""), [busy, setBusy] = useState(false);
  const [downloading, setDownloading] = useState<string>(), [videoError, setVideoError] = useState(false);
  const video = useRef<HTMLVideoElement>(null);
  const { detail, result, error, corrupt } = useTask(id, revision);
  async function retry() {
    setBusy(true); setActionError("");
    try { await retryTask(id); setRevision(v => v + 1); onUpdated(); }
    catch (failure) { setActionError(friendlyError(failure)); }
    finally { setBusy(false); }
  }
  async function download(format: ExportFormat) {
    setDownloading(format); setActionError("");
    try { await downloadExport(id, format); } catch (failure) { setActionError(friendlyError(failure)); }
    finally { setDownloading(undefined); }
  }
  if (!detail) return <section className="result-panel"><h1>正在打开课程…</h1>{error && <p role="alert" className="error-message">{error}</p>}</section>;
  const task = detail.task, hasVideo = detail.input_kinds.includes("video");
  const seek = hasVideo ? (ms: number) => { if (video.current) { video.current.currentTime = ms / 1000; video.current.focus(); } } : undefined;
  const phases = detail.input_kinds.includes("subtitle") ? ["load_subtitles", "generate_notes", "generate_quiz"] : ["extract_audio", "transcribe_audio", "generate_notes", "generate_quiz"];
  const canRetry = (task.status === "failed" && task.error?.retryable) || corrupt;
  return <section className="result-panel" aria-label="课程学习资料">
    <div className="course-heading"><div><div className="eyebrow">YOUR COURSE / STUDY NOTES</div><h1>{task.title}</h1></div><span className={`status-badge ${task.status}`} role="status">{statusLabels[task.status]}</span></div>
    <p className="muted">{task.options.question_count} 道简答题 · {{ easy: "基础理解", medium: "理解与应用", hard: "综合分析" }[task.options.difficulty]} · {task.options.output_language === "zh-CN" ? "简体中文" : task.options.output_language}</p>
    <ol className="progress-track" aria-label="处理进度">{phases.map(name => {
      const step = [...detail.steps].reverse().find(s => s.tool_name === name);
      const state = step?.status || "pending";
      return <li key={name} className={state}><span className="progress-dot" /><span>{stepLabels[name]}</span><small>{{ pending: "待处理", running: "处理中", succeeded: "已完成", skipped: "已复用", failed: "未完成" }[state]}</small></li>;
    })}</ol>
    {task.status === "queued" && <p className="waiting-note">课程已保存，等待后台处理。</p>}
    {(task.error || error || actionError) && <div className="error-box" role="alert"><p>{actionError || error || task.error?.message}</p>{canRetry && <button type="button" className="secondary-button" disabled={busy} onClick={() => void retry()}>{busy ? "正在提交…" : "重试处理"}</button>}</div>}
    {hasVideo && <div className="video-wrap"><video ref={video} controls preload="metadata" src={videoURL(id)} onError={() => setVideoError(true)} aria-label="课程视频" />{videoError && <p className="muted">视频暂时无法播放，仍可阅读已生成的学习资料。</p>}</div>}
    <div className="result-toolbar"><div className="result-tabs" role="tablist" aria-label="学习资料">{[["notes", "课程笔记"], ["quiz", "自测练习"], ["transcript", "课程字幕"]].map(([value, label]) => <button key={value} type="button" role="tab" aria-selected={tab === value} onClick={() => setTab(value)}>{label}</button>)}</div></div>
    <div className="result-content" role="tabpanel" aria-label={{ notes: "课程笔记", quiz: "自测练习", transcript: "课程字幕" }[tab]}>
      {tab === "notes" && (result?.notes ? <NotesViewer notes={result.notes} transcript={result.transcript} onSeek={seek} /> : <p className="empty-result">笔记会在整理完成后出现在这里。</p>)}
      {tab === "quiz" && (result?.quiz ? <QuizViewer quiz={result.quiz} transcript={result.transcript} onSeek={seek} /> : <p className="empty-result">自测题会在生成完成后出现在这里。</p>)}
      {tab === "transcript" && (result?.transcript ? <ol className="transcript-list">{result.transcript.segments.map(segment => <li key={segment.id}>{seek ? <button className="timecode" type="button" onClick={() => seek(segment.start_ms)}>{clock(segment.start_ms)}–{clock(segment.end_ms)}</button> : <span className="timecode">{clock(segment.start_ms)}–{clock(segment.end_ms)}</span>}<p>{segment.text}</p></li>)}</ol> : <p className="empty-result">课程字幕尚未准备好。</p>)}
    </div>
    <div className="export-bar"><span>保存学习资料</span><div>{exports.map(([format, label, kind]) => <button key={format} type="button" className="export-button" disabled={!result?.[kind] || !!downloading} onClick={() => void download(format)} aria-label={`导出${label}`}>{downloading === format ? "下载中…" : label} <span aria-hidden="true">↓</span></button>)}</div></div>
  </section>;
}

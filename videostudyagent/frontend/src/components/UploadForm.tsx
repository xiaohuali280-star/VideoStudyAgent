import { useState } from "react";
import type { FormEvent } from "react";
import { createTask, friendlyError } from "../api/client";
import type { PublicConfig, StudyOptions, Task } from "../api/client";

export default function UploadForm({ config, onCreated }: { config: PublicConfig; onCreated: (task: Task) => void }) {
  const [video, setVideo] = useState<File>(), [subtitle, setSubtitle] = useState<File>();
  const [title, setTitle] = useState(""), [notes, setNotes] = useState(true), [quiz, setQuiz] = useState(true);
  const [ocr, setOcr] = useState(false), [review, setReview] = useState(false);
  const [difficulty, setDifficulty] = useState<StudyOptions["difficulty"]>("medium");
  const [language, setLanguage] = useState("zh-CN"), [spoken, setSpoken] = useState("");
  const [busy, setBusy] = useState(false), [error, setError] = useState("");
  async function submit(event: FormEvent) {
    event.preventDefault(); setError("");
    if (!video && !subtitle) { setError("请选择视频或字幕文件。"); return; }
    if (video && (!/\.mp4$/i.test(video.name) || video.size > config.max_video_bytes)) { setError("视频格式或大小不符合要求。"); return; }
    if (subtitle && (!/\.(srt|vtt)$/i.test(subtitle.name) || subtitle.size > config.max_subtitle_bytes)) { setError("字幕格式或大小不符合要求。"); return; }
    const body = new FormData();
    if (video) body.append("video", video);
    if (subtitle) body.append("subtitle", subtitle);
    if (title.trim()) body.append("title", title.trim());
    body.append("options", JSON.stringify({ question_count: 5, enable_ocr: ocr && !!video, review_policy: review ? "semantic" : "hard_only", generate_notes: notes, generate_quiz: quiz, difficulty,
      output_language: language, transcript_language: spoken || null }));
    setBusy(true);
    try { onCreated(await createTask(body)); } catch (failure) { setError(friendlyError(failure)); }
    finally { setBusy(false); }
  }
  return <form className="upload-panel" onSubmit={submit} aria-label="课程导入">
    <div className="panel-heading"><span className="step-number">01</span><div><h2>导入一节课程</h2><p>本地视频或字幕，作为学习的起点。</p></div></div>
    <label htmlFor="course-title">课程名称（可选）</label><input id="course-title" type="text" maxLength={200} value={title} onChange={e => setTitle(e.target.value)} placeholder="例如：梯度下降入门" disabled={busy} />
    <div className="file-grid"><div className="file-field"><label htmlFor="video-file">课程视频（MP4，可选）</label><input id="video-file" type="file" accept=".mp4,video/mp4" disabled={busy} onChange={e => setVideo(e.target.files?.[0])} /><small>最大 {Math.round(config.max_video_bytes / 1048576)} MiB</small></div>
      <div className="file-field"><label htmlFor="subtitle-file">字幕文件（SRT / VTT，可选）</label><input id="subtitle-file" type="file" accept=".srt,.vtt" disabled={busy} onChange={e => setSubtitle(e.target.files?.[0])} /><small>最大 {Math.round(config.max_subtitle_bytes / 1048576)} MiB</small></div></div>
    <p className="field-hint">至少选择一种文件；同时提供时优先使用字幕，跳过语音识别。课程最长 {Math.round(config.max_duration_ms / 60000)} 分钟。</p>
    <div className="processing-options"><label><input type="checkbox" checked={review} disabled={busy} onChange={e => setReview(e.target.checked)} />审核笔记与答案内容（增加模型调用）</label><label><input type="checkbox" checked={ocr} disabled={busy || !video} onChange={e => setOcr(e.target.checked)} />读取画面文字（本地 OCR，可选）</label><label><input type="checkbox" checked={notes} disabled={busy} onChange={e => setNotes(e.target.checked)} /> 梳理笔记</label><label><input type="checkbox" checked={quiz} disabled={busy} onChange={e => setQuiz(e.target.checked)} /> 生成自测（每批 5 题）</label><p className="field-hint">字幕自动准备；纯画面课程启用 OCR 后可基于画面文字整理资料。</p></div><div className="options-grid">
      <div><label htmlFor="difficulty">难度</label><select id="difficulty" value={difficulty} disabled={busy} onChange={e => setDifficulty(e.target.value as StudyOptions["difficulty"])}><option value="easy">基础理解</option><option value="medium">理解与应用</option><option value="hard">综合分析</option></select></div>
      <div><label htmlFor="output-language">资料语言</label><select id="output-language" value={language} disabled={busy} onChange={e => setLanguage(e.target.value)}><option value="zh-CN">简体中文</option><option value="en">English</option></select></div>
      <div><label htmlFor="spoken-language">课程语种</label><select id="spoken-language" value={spoken} disabled={busy} onChange={e => setSpoken(e.target.value)}><option value="">自动识别</option><option value="zh">中文</option><option value="en">English</option></select></div></div>
    {error && <p role="alert" className="error-message">{error}</p>}
    <div className="form-footer"><span>整理笔记 · 生成自测 · 保留来源</span><button className="primary-button" type="submit" disabled={busy}>{busy ? "正在上传…" : "开始整理"}<span aria-hidden="true"> ↗</span></button></div>
  </form>;
}

import { useEffect, useState } from "react";
import { friendlyError, getConfig, getHealth, getTasks } from "./api/client";
import type { PublicConfig, Task } from "./api/client";
import UploadForm from "./components/UploadForm";
import TaskView, { statusLabels } from "./components/TaskView";

const fallback: PublicConfig = { schema_version: "1.0", max_video_bytes: 524288000, max_subtitle_bytes: 5242880, max_duration_ms: 7200000, export_formats: ["notes.md", "quiz.md", "quiz.json", "transcript.json", "transcript.srt"] };
function restoredTask() {
  const id = new URLSearchParams(location.search).get("task");
  return id && /^[a-f0-9-]{36}$/i.test(id) ? id : undefined;
}

export default function App() {
  const [selected, setSelected] = useState<string | undefined>(restoredTask);
  const [connection, setConnection] = useState("checking"), [config, setConfig] = useState(fallback);
  const [tasks, setTasks] = useState<Task[]>([]), [error, setError] = useState("");
  const [page, setPage] = useState(0), [revision, setRevision] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    void Promise.allSettled([
      getHealth(controller.signal).then(() => { if (!controller.signal.aborted) setConnection("connected"); }).catch(() => { if (!controller.signal.aborted) setConnection("unavailable"); }),
      getConfig(controller.signal).then(value => { if (!controller.signal.aborted) setConfig(value); }),
    ]);
    return () => controller.abort();
  }, [revision]);
  useEffect(() => {
    const controller = new AbortController();
    setError("");
    getTasks(page * 20, controller.signal).then(value => { if (!controller.signal.aborted) setTasks(value); }).catch(failure => { if (!controller.signal.aborted) setError(friendlyError(failure)); });
    return () => controller.abort();
  }, [page, revision]);
  function select(id?: string) {
    setSelected(id);
    const url = new URL(location.href);
    if (id) url.searchParams.set("task", id); else url.searchParams.delete("task");
    history.replaceState(null, "", url);
  }
  function created(task: Task) { select(task.id); setPage(0); setRevision(value => value + 1); }
  return <div className="workspace">
    <aside className="sidebar">
      <a className="brand" href="/" onClick={event => { event.preventDefault(); select(); }}><span className="brand-mark">V</span><span>VideoStudy<span className="brand-light">Agent</span></span></a>
      <p className="nav-label">我的学习空间</p>
      <button type="button" className="new-course" onClick={() => select()}>＋ 导入新课程</button>
      <div className="library-heading"><h2>最近的课程</h2><button type="button" aria-label="刷新课程列表" onClick={() => setRevision(value => value + 1)}>↻</button></div>
      {error && <p className="error-message" role="alert">{error}</p>}
      {!tasks.length && !error && <p className="library-empty">还没有课程。<br />从一节课开始积累。</p>}
      <nav className="course-list" aria-label="课程列表">{tasks.map(task => <button type="button" key={task.id} aria-current={selected === task.id ? "page" : undefined} onClick={() => select(task.id)}><span>{task.title}</span><small>{statusLabels[task.status]}</small></button>)}</nav>
      <div className="pagination"><button type="button" disabled={page === 0} onClick={() => setPage(p => p - 1)}>上一页</button><span>{page + 1}</span><button type="button" disabled={tasks.length < 20} onClick={() => setPage(p => p + 1)}>下一页</button></div>
      <p className="sidebar-note">本地课程 · 专注学习</p>
    </aside>
    <main><header className="topbar"><span>学习工作台</span><span className="connection" role="status"><i className={`connection-dot ${connection}`} />{{ checking: "正在连接本地服务", connected: "本地服务已连接", unavailable: "本地服务未连接，请启动后端后刷新" }[connection]}</span></header>
      <div className="content">{selected ? <TaskView key={selected} id={selected} onUpdated={() => setRevision(value => value + 1)} /> : <>
        <div className="eyebrow">VIDEOSTUDYAGENT / YOUR LEARNING SPACE</div>
        <section className="intro"><div><h1>让每一节课，<br /><span>都成为自己的知识。</span></h1><p className="lead">从课程视频到清晰笔记，再用问题检验理解。<br />把看过的内容变成学会的内容。</p></div><div className="intro-symbol" aria-hidden="true">▶</div></section>
        <UploadForm config={config} onCreated={created} />
        <div className="learning-path"><span>01 导入课程</span><span>02 梳理知识</span><span>03 检验理解</span></div>
      </>}<footer className="page-footer"><span>从一节课开始，积累可回顾的知识。</span><span>VideoStudyAgent · 本地学习工作台</span></footer></div>
    </main>
  </div>;
}

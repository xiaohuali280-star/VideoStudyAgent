import { useEffect, useState } from "react";
import { getHealth } from "./api/client";

type Connection = "checking" | "connected" | "unavailable";

const steps = [
  { number: "01", title: "导入课程", description: "本地视频或字幕，作为学习的起点。", tag: "MP4 / SRT / VTT" },
  { number: "02", title: "梳理知识", description: "按章节整理重点，保留内容来源。", tag: "结构化笔记" },
  { number: "03", title: "检验理解", description: "用自测题回顾课程，查看答案与解析。", tag: "自测与回顾" },
];

export default function App() {
  const [connection, setConnection] = useState<Connection>("checking");

  useEffect(() => {
    const controller = new AbortController();
    getHealth(controller.signal)
      .then(() => { if (!controller.signal.aborted) setConnection("connected"); })
      .catch(() => { if (!controller.signal.aborted) setConnection("unavailable"); });
    return () => controller.abort();
  }, []);

  const connectionLabel = {
    checking: "正在连接本地服务",
    connected: "本地服务已连接",
    unavailable: "本地服务未连接，请启动后端后刷新",
  }[connection];

  return (
    <div className="workspace">
      <aside className="sidebar">
        <a className="brand" href="/" aria-label="VideoStudyAgent 首页">
          <span className="brand-mark" aria-hidden="true">V</span>
          <span>VideoStudy<span className="brand-light">Agent</span></span>
        </a>
        <p className="nav-label">我的学习空间</p>
        <div className="nav-item" aria-current="page"><span aria-hidden="true">▤</span> 学习工作台</div>
        <div className="sidebar-note"><span className="small-dot" /> 本地课程 · 专注学习</div>
      </aside>
      <main>
        <header className="topbar">
          <span>学习工作台</span>
          <span className="connection" role="status">
            <span className={`connection-dot ${connection}`} aria-hidden="true" />{connectionLabel}
          </span>
        </header>
        <div className="content">
          <div className="eyebrow">VIDEOSTUDYAGENT / YOUR LEARNING SPACE</div>
          <section className="intro" aria-labelledby="welcome-title">
            <div>
              <h1 id="welcome-title">让每一节课，<br /><span>都成为自己的知识。</span></h1>
              <p className="lead">从课程视频到清晰笔记，再用问题检验理解。<br />在这里，把看过的内容变成学会的内容。</p>
            </div>
            <div className="intro-symbol" aria-hidden="true"><span>▶</span><i /><i /></div>
          </section>
          <section className="readiness" aria-labelledby="stage-title">
            <span className="stage-badge">阶段 01</span>
            <div><h2 id="stage-title">学习空间正在准备中</h2><p>当前已建立基础页面与服务连接。课程上传、笔记生成和自测将在后续阶段开放。</p></div>
          </section>
          <div className="section-heading"><h2>你的课程学习路径</h2><span>功能即将开放</span></div>
          <section className="steps" aria-label="计划中的学习流程">
            {steps.map((step) => (
              <article className="step-card" key={step.number}>
                <div className="step-top"><span className="step-number">{step.number}</span><span className="step-arrow" aria-hidden="true">↗</span></div>
                <h3>{step.title}</h3><p>{step.description}</p><span className="step-tag">{step.tag}</span>
              </article>
            ))}
          </section>
          <footer className="page-footer"><span>从一节课开始，积累可回顾的知识。</span><span>本地学习工作台 · v0.1</span></footer>
        </div>
      </main>
    </div>
  );
}

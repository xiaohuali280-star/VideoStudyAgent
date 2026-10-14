# VideoStudyAgent

2026-10-14：阶段 8–14 已实现：字幕自动准备、笔记/自测可选、章节聊天、课程笔记偏好及草稿版本、固定 5 题换批与历史导出、预算及分块恢复。离线与本地媒体验收见 [阶段 14 报告](videostudyagent/docs/STAGE_14_REPORT.md)。已有课程库需先停止 API/Worker 并显式备份升级；详见启动指南。

课程视频智能学习系统。上传本地 MP4 或 SRT/VTT，生成带来源时间的结构化笔记、自测题、答案与解析，在 Web 页面阅读并导出。

阶段 1–7 的实现和离线验收已完成。真实 FFmpeg/Whisper 与实际 API/Worker/本地 HTTP 模型协议联调已通过；**真实 DeepSeek 生成质量与费用验收按用户要求延后**。

- [安装、配置、启动及测试](videostudyagent/README.md)
- [架构、数据契约与阶段计划](PLAN.md)
- [阶段 6 验收](videostudyagent/docs/STAGE_6_REPORT.md) / [阶段 7 验收](videostudyagent/docs/STAGE_7_REPORT.md)
- [开源复用来源](videostudyagent/docs/UPSTREAM_SOURCES.md) / [许可证与通知](videostudyagent/THIRD_PARTY_NOTICES.md)

React + FastAPI + SQLite + 独立单 Worker；单 Agent 原生 Tool Calling。没有多 Agent、OCR、RAG、认证或自动评分。仅供本机使用，未部署。

源码在 videostudyagent/backend 和 videostudyagent/frontend。密钥、上传内容、数据库、缓存、模型、依赖和构建产物均排除在 Git 之外。

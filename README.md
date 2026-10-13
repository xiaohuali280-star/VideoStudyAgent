# VideoStudyAgent

课程视频智能学习系统：计划支持本地视频/字幕导入、带时间戳转写、结构化笔记、自测题及结果导出。

当前完成阶段 1：React + FastAPI 工程骨架、数据契约、SQLite 迁移骨架与离线测试。上传、ASR、笔记/题目生成和 Agent 调度待后续阶段实现。

- [本地安装、启动与测试](videostudyagent/README.md)
- [架构与分阶段计划](PLAN.md)
- [开发约束](videostudyagent/AGENTS.md)
- [阶段 1 验收记录](videostudyagent/docs/STAGE_1_REPORT.md)
- [五个 GitHub 项目的复用调研](videostudyagent/docs/REUSE_RESEARCH.md)

源码在 `videostudyagent/backend/` 和 `videostudyagent/frontend/`。后端 63 项、前端 7 项测试通过；类型检查与生产构建通过。阶段 1 无需 API Key 或模型即可运行。

本地 `.env`、用户资料、缓存、模型、虚拟环境、依赖和构建产物不纳入版本控制。当前未纳入候选上游业务源码，正式采用时按计划保留许可及来源记录。

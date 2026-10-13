# VideoStudyAgent

课程视频智能学习系统：计划支持本地视频/字幕导入、带时间戳转写、结构化笔记、自测题及结果导出。

当前完成阶段 1–3：工程骨架、上传与持久化、字幕/媒体处理及本地 ASR 工具。笔记/题目生成和 Agent 调度待后续阶段实现。

- [本地安装、启动与测试](videostudyagent/README.md)
- [架构与分阶段计划](PLAN.md)
- [开发约束](videostudyagent/AGENTS.md)
- [阶段 1 验收记录](videostudyagent/docs/STAGE_1_REPORT.md)
- [五个 GitHub 项目的复用调研](videostudyagent/docs/REUSE_RESEARCH.md)

源码在 `videostudyagent/backend/` 和 `videostudyagent/frontend/`。后端 96 项测试通过，前端已验证 7 项测试；类型检查与生产构建通过。基础服务不需要密钥，ASR 需显式准备本地模型。

本地 `.env`、用户资料、缓存、模型、虚拟环境、依赖和构建产物不纳入版本控制。BiliNote 转写适配已纳入并保留许可及来源记录，其余候选按阶段评估。

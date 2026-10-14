# 阶段 8 验收记录：契约、操作与版本基础

日期：2026-10-14（Asia/Shanghai）。用户已授权继续实现并上传 GitHub；本次仅完成阶段 8，不提前实现阶段 9–14。

## 交付

- 新增 1.1 DTO：笔记/自测开关、固定五题请求、课程笔记偏好、五类操作请求、操作/尝试用量与输出引用、字幕快照、笔记版本、自测批次、课程当前版本、会话及消息。聊天消息只允许 user/assistant；公共操作请求不接受 Key、路径或预算参数。
- 保留全部 1.0 DTO 和旧 1/5/20 题文档读取；新版自测章节引用可空，为后续“只出题、不生成笔记”准备契约，来源证据仍必填。
- 0003_study_foundation 显式新增 8 张表。外键包含课程归属，阻止跨课程引用；操作幂等、批次序号/nonce、消息序号/客户端 ID 有唯一约束。
- StudyRepository：原子幂等提交、同课程操作串行领取、状态迁移、运行中取消请求/Worker 确认分离、冻结预算与单调用量、保留失败尝试用量；不可变版本索引、偏好版本比较、笔记/自测当前指针的并发比较、历史版本恢复、消息去重与分页。
- VersionReader 与显式 LegacyStudyImporter：校验文件 hash/文档/来源后建立旧结果索引；保留原文件、Task 及原题数。来源时间变化会生成独立版本，不能仅用相同笔记文字合并。中断旧执行索引为失败可恢复，不自动重跑；损坏产物不伪装为有效版本。
- 健康阶段更新到 8，允许阶段上限到 14；OpenAPI components 与前端类型同步。没有新增尚未实现的 HTTP 路由。

## 运行与迁移边界

现有 API/Worker 的 initialize_database 默认目标固定为 0002_tasks，保持原业务路径；新迁移仅在显式传入 revision="0003_study_foundation" 时执行。阶段 8 不自动接管队列，也不自动索引用户结果。

本次所有迁移、导入和仓储测试使用临时数据库/自建样例；未升级用户 app.db，未改 .env/Key/时长或预算，未停止用户 Worker，未调用真实模型。现有前端开关、聊天和换批入口尚未实现，不能把本阶段 DTO 当成已上线功能。

仓储负责版本归属、不可变索引、状态和并发；VersionReader 负责真实文件校验。后续生成/聊天服务还须在发布前校验内容与引用，不能只凭索引存在发布有效结果。取消的真实进程终止将在 Worker 接入阶段实现，本阶段仅建立不会过早宣称已取消的状态契约。

0003 降级只允许全部新表为空，非空时明确拒绝，避免静默删除版本/聊天资料。未来实施生产迁移前仍需停机或协调写入、备份并演练，不能直接对运行中的用户库执行升级/降级。

## 修改文件

- backend/app/schemas/iteration.py：新 DTO；schemas/common.py：健康阶段。
- backend/app/db/iteration_models.py、study_repository.py：新表元数据与仓储；repository.py：显式迁移目标。
- backend/alembic/versions/0003_study_foundation.py、alembic/env.py：固定迁移及完整元数据登记。
- backend/app/services/study_versions.py：版本读取与旧数据显式导入。
- backend/app/main.py、openapi.json、frontend/src/api/schema.d.ts、client.ts：契约及健康兼容。
- backend/tests/test_study_foundation.py、test_migrations.py、test_config_health.py：新增与既有回归。
- ITERATION_2_PLAN.md、PLAN.md、AGENTS.md、README：阶段与授权记录、迁移说明。

## 实测

| 检查 | 结果 |
| --- | --- |
| 全量 pytest | **225 passed，25.63 s，无跳过**；相对阶段 7 新增 37 项 |
| Ruff check / format --check | 通过，72 个项目 Python 文件；原样 vendor 仍排除 |
| uv lock --check --offline | 通过，53 packages；无新增依赖 |
| Vitest | **13 passed** |
| TypeScript / Vite build | 通过；既有 Markdown/KaTeX 大包提示仍存在 |
| Playwright Chromium | **2 passed，17.3 s**；旧上传/笔记/折叠/下载/刷新恢复/手机布局不回归 |

阶段 8 测试包含：新请求严格五题、禁止越权参数、四种结果集合、旧库默认不自动升级、重复迁移/空表降级/非空拒绝降级、迁移列及索引与 ORM 一致、双线程幂等及串行领取、数据库级跨课程外键、预算不可修改/用量不回退、重试保留尝试历史、取消确认、不可变版本/旧草稿冲突/恢复、消息去重/角色/课程归属、旧 1/5/20 题导入/文件不变、来源时间轴变动隔离、损坏旧产物报告、中断索引不自动执行。

## 复用与遗留

继续使用已引入的来源校验、ArtifactStore、Pydantic/SQLAlchemy/Alembic；没有采用新的上游源码，也没有改动现有受来源清单保护的文件，原本的来源 hash 测试通过。

本阶段新增内容属于本项目契约、持久化和兼容胶水。真实模型能力/教学质量仍未在本轮验证；新操作、版本与聊天 UI/API 的可用行为将在后续阶段接入。

下一阶段为 9：实现两个开关、动态工具权限与完成条件、仅字幕不要求 LLM、无笔记直接出题、初批固定五题，并在受控迁移后接入统一操作队列。

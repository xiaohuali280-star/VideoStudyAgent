# 阶段 14：综合验收与交接

日期：2026-10-14。阶段 9–14 的实现工作已完成；真实 DeepSeek 质量与费用验收按用户要求延后，没有将离线模型结果当作真实质量证据。

## 完成范围及文件

- 可选笔记/自测，字幕始终自动；16 种 SRT/VTT/MP4/双输入与功能组合均有离线测试。
- 固定 5 题、换批难度、历史分页、规范化文本去重、幂等提交、指定版本导出；换批失败保留旧资料。近期重复文本校验不等于语义去重。
- 按章节/笔记版本的持久聊天、原文引用、有限历史上下文；聊天要求可明确转为修改草稿。
- 课程偏好、部分章节修订、草稿对照预览/应用/放弃、旧版本恢复；不自动重出题。
- 预算预检、逐块检查点及损坏重做、用量与尝试历史、统一 Worker 队列、取消和手动恢复。

本阶段主要修改文件：

| 文件/目录 | 修改与目的 |
| --- | --- |
| backend/app/operation_worker.py、worker.py | 取消竞态处理、子进程异常脱敏、原生课程锁检查、重启不误标仍存活的尝试；旧库先检查升级要求 |
| backend/app/services/operations.py | 初次取消/异常的课程状态同步、固定开始版本、已持久化输出恢复，避免重试重复生成 |
| backend/app/api.py、routes/study.py | 取消入口及旧题数重试边界 |
| backend/app/migrate_study.py、services/study_versions.py | 备份/锁及幂等导入；跳过原生新课程；旧排队操作不自动执行，保留旧 Task 和文件 |
| backend/app/services/exports.py、note_chat.py、providers/budget.py | 导出选择与格式一致、历史单独验证、历史上下文内存有界、超预算返回也记录供应商已报告用量 |
| frontend/src/components/QuizBatches.tsx、StudyActions.tsx、NoteChat.tsx | 当前/历史题批次与下载一致、补生成读取课程偏好、聊天要求明确转草稿 |
| frontend/src/styles.css | 聊天、偏好、版本对照及移动页面样式 |
| backend/tests/test_iteration_acceptance.py、test_iteration_edges.py、test_optional_study.py、test_checkpoints.py | 升级备份/锁、16 种组合、损坏恢复、缓存失效、无效角色/引用、部分章节不变、真实进程取消 |
| frontend/e2e/iteration.spec.ts、study.spec.ts、backend/tests/e2e_app.py | 完整新功能与既有导出流程，隔离本机替身模型 |
| backend/scripts/smoke_local.py | 更新固定 5 题和新批次不复用旧题缓存的实际进程验收 |
| backend/openapi.json、frontend/src/api/schema.d.ts、schema/common.py、api/client.ts | 最终契约、健康阶段号及友好错误 |
| README.md、videostudyagent/README.md、AGENTS.md、PLAN.md、ITERATION_2_PLAN.md | 当前功能、Windows 启动、旧库显式备份升级/回滚及实际验收状态 |

## 实际测试结果

| 检查 | 结果 |
| --- | --- |
| 后端完整 pytest | **258 passed**，61.56 秒，无跳过；默认隔离本地 Key 和外网，使用临时课程库 |
| 前端 Vitest | **13 passed** |
| Playwright | **4 passed**，36.2 秒：聊天→保存偏好→聊天要求生成草稿→应用→换题→历史下载→刷新；仅字幕后补自测无隐藏笔记；原主流程与五种导出；移动和无效上传 |
| TypeScript、Vite 构建 | 通过，仍有 Markdown/KaTeX 构建包超过 500 kB 的提示 |
| Ruff check / format --check | 通过，86 个 Python 文件格式检查 |
| uv lock --check --offline | 通过，53 个锁定依赖包；使用项目内缓存目录 |
| 上游文件散列/许可 | 完整测试内通过，B3 提示哈希按 LF 归一化校验；原 vendor 模块未改动 |
| 真实媒体/本地 ASR/HTTP 协议冒烟 | 4 种模式通过；见下文，云端调用 0 |

本地实际媒体证据：自建 34 秒 MP4，经真实 FFmpeg 和 tiny CPU/int8 转写为 7 个带毫秒时间戳的片段。实际 API、生产 Worker、任务子进程、DeepSeek HTTP 适配器接入本机 HTTP 测试模型，验证 MP4、VTT、MP4 配 SRT、缓存模式各生成 5 题、五种导出及 API 重启后结果一致。HTTP 替身收到 23 次请求，其中生成请求 6 次；这不是 DeepSeek 质量或账单证据。原始记录留在忽略目录 `.cache/smoke-final-7188a6a87681/smoke-report.json`。

已在临时库演练 SQLite 升级前备份、Worker 锁拒绝升级、重复迁移、旧 1/20 题兼容及损坏产物边界；未迁移用户个人课程库。关闭原数据库连接并创建新 API 后，验证正式版本、聊天消息、偏好和两个题批次保持一致；输出已落盘但成功状态未记录时，手动重试不调用模型。操作成功而课程状态未同步时，重启仅修复状态。取消测试启动并终止自有等待进程和其子进程，检查取消后的操作与课程状态；不终止用户的服务。

## GitHub 分阶段交付

| 阶段 | 已上传提交 |
| --- | --- |
| 9 | [d04b8c8](https://github.com/xiaohuali280-star/VideoStudyAgent/commit/d04b8c8f85c33e452017ed4886783093aa4e03fa) |
| 10 | [201c721](https://github.com/xiaohuali280-star/VideoStudyAgent/commit/201c721effaf73a3cc816a655bbfa91827d7ced4) |
| 11 | [14b3263](https://github.com/xiaohuali280-star/VideoStudyAgent/commit/14b32630124cbaf03845d58c45d00baf46937f30) |
| 12 | [189b337](https://github.com/xiaohuali280-star/VideoStudyAgent/commit/189b33714a5802d1ea25584b0f4edb5da3adcabb) |
| 13 | [e663b34](https://github.com/xiaohuali280-star/VideoStudyAgent/commit/e663b3464f45e93868de630b044a6d77a46d64aa) |
| 14 | 本报告随阶段 14 独立提交上传；具体提交号见 main 的提交历史 |

各提交的文件清单可在对应链接逐项查看。采用既有 B1/B2/B3/B4、D1/D2/D3、T1，未新增上游项目依赖。本轮主要扩展外围契约/仓储/UI；D2 允许无笔记自测的空章节引用仍必须有有效字幕证据，B3 仅允许课程偏好控制表达，不允许覆盖事实/来源约束。

## 使用与遗留验收

已有库需先停止 API/Worker，按 README 执行 `python -m app.migrate_study --api-stopped`，再重启三个本机服务。没有在开发过程中替用户执行升级或重跑课程。新空库可直接启动使用。

按既有授权没有调用云端、修改 `.env`、密钥、时长或调用预算，没有部署，也未上传媒体、字幕、数据库、模型、缓存、依赖或构建产物。真实 DeepSeek 的中文课程质量、公式/事实、难度与题目语义差异、长课程性能和费用仍需以后明确付费验收；当前引用检查只证明来源匹配。长页面暂未虚拟滚动，Markdown/KaTeX 体积优化不是本轮范围。

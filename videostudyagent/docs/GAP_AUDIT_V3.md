# V3 差距审计（规划稿）

日期：2026-10-14；本项目基线：84251227a61cfc6f05167a88c000146f3e8fd737。状态：只完成审计及规划，阶段 15–19 尚未获批实施。

本次读取 PLAN.md、项目 AGENTS.md、STAGE_14_REPORT.md 及用户提供的 Downloads/VideoStudyAgent_Codex_Roadmap_v3.md。项目内 ROADMAP_V3.md 原先缺失，本次新增对应规划稿；下载文件只作为参考，没有执行其中的启动指令或视为实施授权。

## 1. 核查方法与证据边界

- 阅读实际 Python/TypeScript 源码、Pydantic 契约、相关测试及原阶段报告；按当前 HEAD 固定结论。
- 本次重跑后端完整 pytest：258 passed，62.90 秒；前端 Vitest：13 passed；TypeScript 类型检查通过。
- 本次没有重新运行 Playwright、构建、真实 Whisper 冒烟或任何真实 LLM。阶段 14 的 4 项浏览器、真实 34 秒 MP4/tiny/FFmpeg、23 次本机 HTTP 替身请求属于历史证据，不能当成本次重新运行，更不是云端模型质量证据。
- 后端测试的 conftest.py 使用临时 data_dir、Settings(_env_file=None)、清除 VSA_ 环境并阻止外网；未读写个人课程数据库、修改配置或触发个人任务。没有安装新依赖、执行上游脚本、提交或推送。
- “实现状态”和“验证状态”分开：一个功能可以已经实现，同时未经真实模型质量验证。

## 2. 能力核查

下列路径均相对 videostudyagent/；函数行号对应上述 HEAD。

| 能力 | 实现状态与实际边界 | 源码证据 | 测试证据与验证状态 |
| --- | --- | --- | --- |
| MP4、SRT/VTT、配字幕优先、带毫秒时间戳 | 已实现；配字幕时验证视频时长，不静默转 ASR | backend/app/services/transcription.py:21、42、66；schemas/study.py:31、44；services/media.py | test_transcription.py 的 millisecond_subtitles、invalid_subtitle_timing_is_not_guessed、subtitle_priority_blocks_asr；真实 tiny 质量仅有历史短样本，不代表中文板书/长课效果 |
| 单 Agent 原生 Tool Calling | 已实现；五个受控工具、一次纠正、无进展和调用上限；仅字幕准备不需要 LLM | backend/app/agent/loop.py:21；agent/tools.py；task_runner.py:18 | test_agent_worker.py:46、97、119、136、162、170；HTTP Mock 合约通过；真实 deepseek-flash 工具选择可靠性未经验收 |
| 笔记/自测开关、无笔记直接出题 | 已实现；字幕始终准备 | schemas/iteration.py:32；services/operations.py；frontend/src/components/UploadForm.tsx | test_optional_study.py:17，四种输入 × 四种开关组合；只字幕零模型调用 |
| 严格结构、原文引用、来源 ID 核验 | 已实现的是确定性核验；不包含语义蕴涵证明 | adapters/grounding.py:31、47、54；schemas/study.py:126 | test_generation.py:87、113；test_iteration_edges.py:80；有效引用配错误答案仍可能通过现有检查 |
| 全字幕分块、逐块恢复 | 已实现；验证覆盖全部原片段 ID，检查点校验散列和来源；没有静默截断 canonical Transcript | services/generation.py:114、129、142；services/checkpoints.py:11；adapters/chunking.py | test_generation.py:61；test_checkpoints.py:15、47、62：中断、损坏、仅补缺失块、模型/语言/偏好失效；“ID 全覆盖”不等于知识点语义全覆盖 |
| 新批固定 5 题、三难度、换批/历史/导出 | 已实现；旧 1–20 题保留读取 | schemas/study.py:152；schemas/iteration.py:44、174；services/generation.py:184；routes/study.py:87 | test_quiz_batches.py:11；test_iteration_acceptance.py:73；test_study_foundation.py:408；难度与答案的真实语义质量未经验收 |
| 跨批去重 | 部分实现：规范化文本去重，读取最近至多 100 批，提示最近 15 题；没有语义等价检测 | services/operations.py:290；services/generation.py:230、242 | test_quiz_batches.py：重复文本失败保留旧批；同义改写重复题未被证明可检出 |
| 章节聊天及持久消息 | 已实现；只选已发布笔记章节，送对应字幕和同版本最近六条消息；不检索整课 | services/note_chat.py:24、34、63；routes/study.py:124；frontend/src/components/NoteChat.tsx | test_note_chat.py:10；test_iteration_edges.py:80；test_iteration_acceptance.py:92；真实回答忠实性未验收 |
| 偏好、局部修订、草稿/应用/放弃/恢复 | 已实现；章节 ID/原来源保持，未选章节不变；已有题批次保留原笔记依据 | services/note_revisions.py:20、41；db/study_repository.py:550、579、610；routes/notes.py；NoteRevisions.tsx | test_note_revisions.py:10；test_iteration_edges.py:24；test_study_foundation.py:296；真实偏好遵从性未验收 |
| 操作队列、互斥、取消、重启恢复 | 已实现；一个独立 Worker，课程级锁，手动重试，输出已持久化时可恢复 | operation_worker.py:17、77、115；db/study_repository.py:87、160、303、335；services/operations.py:131 | test_iteration_acceptance.py:51、79、92；test_iteration_edges.py:146；旧迁移/锁/跨课程隔离另见 test_study_foundation.py |
| 预算及用量 | 已实现保守请求/token 预留、运行时硬上限和尝试历史；观测完整性部分实现 | providers/budget.py；schemas/iteration.py:110；db/study_repository.py:187；OperationUsage.tsx | test_checkpoints.py:47；test_study_foundation.py:252；没有真实账单或价格换算；混合缺失 usage 时累计量可能只有供应商已报告部分 |
| 时间戳跳转、五种导出、安全 Markdown | 已实现 | services/exports.py；frontend/src/components/Sources.tsx、SafeMarkdown.tsx、TaskView.tsx | test_exports.py:25、86；frontend/src/tests/study.test.tsx；历史 Playwright 4 项，本次未重跑 |
| 关键帧 OCR、统一 VideoContext | 未实现；Transcript.source 仅 subtitle/asr，没有帧/OCR 证据契约 | schemas/study.py:44；schemas/tasks.py:30；schemas/iteration.py:154；transcription.py | 当前没有该业务能力；现有 MP4 测试不能当成 OCR 验收 |
| 语义 Critic、定向知识修复 | 未实现；当前 JSON/来源失败最多一次修复，不是语义 Critic | generation.py:88；grounding.py | 有结构/引用错误测试，没有语义审核模型及质量评测 |
| 整课 EvidenceRetrieval、FTS/向量混合 | 未实现；章节取源和生成分块均不等于检索 | note_chat.py:34；generation.py:75；当前 app 中未发现检索索引/provider | 无 Recall@K、空召回、索引恢复等检索测试 |
| AgentEvaluation 与黄金集 | 未实现独立评估器；已有大量程序回归测试 | backend/tests、tests/scripted_llm.py；没有 evaluation 目录/评测入口 | 258 项通过证明程序契约回归，不给出课程准确率 |
| SSE | 未实现；当前为轮询 | frontend/src/hooks/useTask.ts:14；StudyActions.tsx:12；其余聊天/版本组件的定时刷新 | 当前没有事件序号、Last-Event-ID、跨进程重放/断线流测试 |

## 3. V3 必须补齐的设计边界

1. **OCR-only 不是空 Transcript。** Transcript 要求非空 segments，旧工具成功条件要求 transcript，现有笔记/题目证据是 segment_id/quote。db/iteration_models.py 的 NotesRevisionRow/QuizBatchRow 也有必填 transcript_snapshot_id 和跨课程外键；study_repository.py:232 的 finish 仅接受旧输出。新增可选 OCR 需要独立 VideoContextSnapshot、多来源 EvidenceRef、版本化来源字段、受控输入及新的成功条件，并在临时库验证关联表迁移；不能把画面文字伪装为 ASR，也不能为旧快照换一种内容。
2. **来源有效不等于答案正确。** validate_notes 检查 ID 集合，validate_quiz 检查来源/章节/原文/题数，没有判断答案是否推出、例子是否杜撰。阶段 15 先准备“引用正确而答案错误”和“ID 全覆盖而重要知识遗漏”的负例，阶段 17 才实现审核。
3. **用量记录不等于账单。** BoundedLLM 用 OR 记录 usage_known；当若干回复缺 usage、另一些有 usage 时，没有完整度字段，已报告值不能直接当全部用量。阶段 15 指标规范显式区分 unknown/partial/reported，不重写现有预算系统；若需运行时完整度字段，另作为后续小改动验收。
4. **审核要在正式发布前。** operations.py 和仓储已有发布与 CAS；新审核必须卡在新正式版本/批次发布之前，并覆盖草稿 apply 路径及缓存恢复路径，不能只审核一次初次生成。旧版本默认仍可读，不能追加审核后把历史突然判为不可用。
5. **阶段 17/18 不形成循环依赖。** 阶段 17 先用来源 ID/时间范围确定性选择原始证据，阶段 18 再提供可插拔检索；不为 Critic 先建一套重复 RAG。
6. **字幕优先仍然保留。** 无效的用户字幕不应悄悄被 OCR 替代；OCR 失败、无音轨/无语音和用户字幕格式错误要区分错误类型与降级策略。
7. **新表/新快照只显式迁移。** 所有升级和回退先在临时库测试，旧 JSON 文件保持原样。当前本次审计不读取或迁移个人数据库。

## 4. DOVideo-AI 源码审计

固定参考版本：df4fa83a78a51dfa1718606bf47cf49942e1112e，MIT，LICENSE 版权标识为 Copyright (c) 2026 Majst。下表使用完整固定源码链接；不是 README 功能清单推断。没有运行其 Java 测试、真实依赖或整站。

| 模块与源码 | 借鉴点 | 本项目必须调整 |
| --- | --- | --- |
| [VideoContext DTO](https://github.com/Xiaoc7r/DOVideo-AI/blob/df4fa83a78a51dfa1718606bf47cf49942e1112e/server/src/main/java/com/example/server/dto/VideoContext.java)、[Service](https://github.com/Xiaoc7r/DOVideo-AI/blob/df4fa83a78a51dfa1718606bf47cf49942e1112e/server/src/main/java/com/example/server/service/VideoContextService.java#L70) | ASR/OCR 双路、独立超时、60 秒窗口、场景检测与 30 秒保底、dHash | 目标与媒体上下文分离；新增稳定来源 ID、快照与分支状态；保留真实 PTS。234 行序号推时刻不采用；按窗口聚合不能丢原字幕精确区间。dHash 近似相同不能证明文字相同，尤其数字/公式变化 |
| [OcrUtils](https://github.com/Xiaoc7r/DOVideo-AI/blob/df4fa83a78a51dfa1718606bf47cf49942e1112e/server/src/main/java/com/example/server/utils/OcrUtils.java#L25) | 本地 Tesseract、中文/英文、可终止进程 | stdout/stderr 分离；不能把成功进程的诊断文字当 OCR 内容；错误脱敏；用可选 TSV 取得 bbox/置信度，置信度不是准确率 |
| [AgentLoop](https://github.com/Xiaoc7r/DOVideo-AI/blob/df4fa83a78a51dfa1718606bf47cf49942e1112e/server/src/main/java/com/example/server/service/AgentLoopService.java#L207)、[EvidenceVerification](https://github.com/Xiaoc7r/DOVideo-AI/blob/df4fa83a78a51dfa1718606bf47cf49942e1112e/server/src/main/java/com/example/server/service/EvidenceVerificationService.java#L28) | 明确审核问题、时间范围、有限轮数、草稿/审核状态恢复、定向补证 | 沿用唯一 StudyAgent；Critic 只是普通审核组件。supportsClaim 是结论文字绑定加引用存在，非蕴涵证明；其 normalize 去标点/符号，不适合负号/公式，保留现有 quote_present。达到轮数后仍保存带警告结果的策略不直接用于本项目的正式发布 |
| [VideoChunking](https://github.com/Xiaoc7r/DOVideo-AI/blob/df4fa83a78a51dfa1718606bf47cf49942e1112e/server/src/main/java/com/example/server/service/VideoChunkingService.java)、[EvidenceRetrieval](https://github.com/Xiaoc7r/DOVideo-AI/blob/df4fa83a78a51dfa1718606bf47cf49942e1112e/server/src/main/java/com/example/server/service/VideoEvidenceRetrievalService.java#L56)、[LongVideoContext](https://github.com/Xiaoc7r/DOVideo-AI/blob/df4fa83a78a51dfa1718606bf47cf49942e1112e/server/src/main/java/com/example/server/service/LongVideoContextService.java#L90) | 时间块、词法/语义/OCR 多信号、远端向量失败回退、按反馈补证 | 不复制 0.6/0.25/0.15 权重或固定 Top3；先本地词法基线。上游查询意图和摘要可能额外调用 LLM，本项目默认不加；24,000 字符选择丢段不能替代整课笔记全覆盖 |
| [AgentEvaluation](https://github.com/Xiaoc7r/DOVideo-AI/blob/df4fa83a78a51dfa1718606bf47cf49942e1112e/server/src/main/java/com/example/server/service/AgentEvaluationService.java#L47)、[OfflineAgentEvaluationRunner](https://github.com/Xiaoc7r/DOVideo-AI/blob/df4fa83a78a51dfa1718606bf47cf49942e1112e/server/src/main/java/com/example/server/service/OfflineAgentEvaluationRunner.java)、[golden cases](https://github.com/Xiaoc7r/DOVideo-AI/blob/df4fa83a78a51dfa1718606bf47cf49942e1112e/server/src/main/resources/evaluation/golden-video-tasks.json) | 多维指标、固定小用例、关键词覆盖、结构/来源评估分离 | timestampCoverageRate 是引用时间有效率，不是全课覆盖率；无样本返回 0 的做法不采用。四条黄金数据不是学习质量基准；Offline runner 实际调用 AgentLoop/DeepSeek，名称不意味着断网免费。本项目默认 fixture/replay，无 live 调用 |
| [TaskEventService](https://github.com/Xiaoc7r/DOVideo-AI/blob/df4fa83a78a51dfa1718606bf47cf49942e1112e/server/src/main/java/com/example/server/service/TaskEventService.java#L63) | 先注册再取快照、串行发事件、丢弃过期初始快照 | 不搬 Redis PubSub；SQLite 持久事件日志服务独立 API/Worker，支持游标恢复；事件仅提示，仓储状态才是权威 |

以上均为**设计参考候选**，未复制/改造纳入实质源码，未将来源清单写成“已采用”。以后若采用代码、提示或测试，先登记固定 commit、原路径、原始/本地散列、改动及许可证/通知，按现有复用流程执行。

## 5. 冲突与后续门槛

AGENTS.md 明确禁止 OCR、RAG/向量库，并有“不引入截图”“只控制五个工具”等旧约束；V3 的 OCR/本课程检索不能仅靠此路线图自行开启。待确认变更另见 AGENTS_V3_DRAFT.md，原 AGENTS.md 和 PLAN.md 本次保持原样。用户本次“禁止提交/推送”也覆盖原文件中阶段 9–14 的历史上传授权。

详细阶段 15–19、数据契约、修改落点及验收见 ROADMAP_V3.md。下一步仅等待用户确认阶段 15 的最小评测基线范围。

# GitHub 同类项目调研与模块复用清单

调研日期：2026-10-13（Asia/Shanghai）。状态：完成公开仓库、固定提交目录、许可证及关键源码的只读核查；未运行上游项目，未将上游业务代码纳入本项目。

本文件是复用决策依据，不代表兼容性测试已通过。后续按 PLAN.md 的阶段逐项落地，禁止将 README 中的功能描述、测试数或速度视为本项目实测结果。

## 1. 五个项目及版本依据

| 项目 | 核查版本（完整 commit SHA） | 许可证证据 | 结论 |
| --- | --- | --- | --- |
| [JefferyHcool/BiliNote](https://github.com/JefferyHcool/BiliNote) | master；90940fde4d224d0f69ad99674f4af0a1ea52d3c4；提交时间 2026-09-01 UTC | [LICENSE](https://github.com/JefferyHcool/BiliNote/blob/90940fde4d224d0f69ad99674f4af0a1ea52d3c4/LICENSE)：MIT | 视频转笔记链路最接近；优先复用独立分块器，适配转写和笔记提示 |
| [HKUDS/DeepTutor](https://github.com/HKUDS/DeepTutor) | main；6cf793bd868ba5ecbe64722936d4be8fab5a01df；提交时间 2026-10-08 UTC | [LICENSE](https://github.com/HKUDS/DeepTutor/blob/6cf793bd868ba5ecbe64722936d4be8fab5a01df/LICENSE)：Apache-2.0；另有 [THIRD_PARTY_NOTICES.md](https://github.com/HKUDS/DeepTutor/blob/6cf793bd868ba5ecbe64722936d4be8fab5a01df/THIRD_PARTY_NOTICES.md) | 优先复用 JSON 辅助函数，适配来源校验；完整 Agent/出题运行时依赖较广 |
| [Allen0497/video-to-notes](https://github.com/Allen0497/video-to-notes) | main；3d9b2bdc45cc02fa5e53c2703456f4b7942f4678；提交时间 2026-04-17 UTC | [LICENSE](https://github.com/Allen0497/video-to-notes/blob/3d9b2bdc45cc02fa5e53c2703456f4b7942f4678/LICENSE)：MIT | 可参考字幕优先和轻量本地 ASR；字幕解析会丢失结束时间及毫秒，不作为正式解析器 |
| [Milind1904/ai-tutor](https://github.com/Milind1904/ai-tutor) | main；438e3aa42af58dcba61fa993dd1519ade55aafcc；提交时间 2026-04-30 UTC | [LICENSE](https://github.com/Milind1904/ai-tutor/blob/438e3aa42af58dcba61fa993dd1519ade55aafcc/LICENSE)：MIT | React/Vite + FastAPI 同栈；适配难度提示与自测展示片段，不引入 RAG/认证/自动评分 |
| [SindhujaKumari211/AI-Notes-Generator](https://github.com/SindhujaKumari211/AI-Notes-Generator) | main；bfbdcacae67577488dda8aa197619b3cd826b52f；提交时间 2026-09-15 UTC | 完整 Git tree 未发现 LICENSE；README 仅写 educational use，GitHub license 字段为空 | 功能接近，分块/分阶段生成值得参考；当前不复制、修改或分发其代码、提示及测试 |

GitHub 上存在多个同名 BiliNote，本调研明确采用 JefferyHcool/BiliNote。DeepTutor 的搜索摘要中有不同许可证信息，以上固定提交实际 LICENSE 为准。分支和搜索缓存会变化，采用时以此提交为基线并记录新增版本差异。

## 2. 具体模块核查

### BiliNote

- [backend/app/gpt/request_chunker.py](https://github.com/JefferyHcool/BiliNote/blob/90940fde4d224d0f69ad99674f4af0a1ea52d3c4/backend/app/gpt/request_chunker.py)：RequestChunker / ChunkPayload 主要依赖标准库，支持自定义 size_estimator；默认计量为序列化请求的 UTF-8 字节数，不能直接当作模型 token 限制。超长片段会拆文本并复制片段其他字段。
- [backend/app/transcriber/whisper.py](https://github.com/JefferyHcool/BiliNote/blob/90940fde4d224d0f69ad99674f4af0a1ea52d3c4/backend/app/transcriber/whisper.py)：WhisperTranscriber 使用 faster-whisper，CPU 默认 int8，输出含 start/end/text；同时依赖 app 内配置、模型目录、日志、装饰器及 events。模型加载失败存在清缓存/重下载逻辑，转写异常存在打印后未重新抛出的路径，不能原样采用。
- [backend/app/gpt/prompt_builder.py](https://github.com/JefferyHcool/BiliNote/blob/90940fde4d224d0f69ad99674f4af0a1ea52d3c4/backend/app/gpt/prompt_builder.py)：generate_base_prompt 按标题、文本、格式、风格组合提示。可以适配笔记章节和总结要求，但现有输出目标不能直接替代本项目的 NotesDocument Schema。
- [BillNote_frontend/src/pages/HomePage/components/MarkdownViewer.tsx](https://github.com/JefferyHcool/BiliNote/blob/90940fde4d224d0f69ad99674f4af0a1ea52d3c4/BillNote_frontend/src/pages/HomePage/components/MarkdownViewer.tsx)：已使用 react-markdown、GFM、数学渲染；整组件同时依赖任务 store、聊天、思维导图、截图和多种 UI。仅将与这些状态无关的渲染片段作为候选，不复制整个页面。
- 已定位 upstream 测试 backend/tests/test_request_chunker.py、test_whisper_config_forwarding.py 等；本轮未运行。纳入对应模块时迁移适用断言并补项目契约测试。

### DeepTutor

- [deeptutor/agents/_shared/json_output.py](https://github.com/HKUDS/DeepTutor/blob/6cf793bd868ba5ecbe64722936d4be8fab5a01df/deeptutor/agents/_shared/json_output.py)：extract_json_object 为标准库辅助函数，处理常见 JSON 包裹输出；适合小文件 vendor，之后必须继续通过 Pydantic 校验。空对象不能等同成功。
- [tests/agents/test_shared_json_output.py](https://github.com/HKUDS/DeepTutor/blob/6cf793bd868ba5ecbe64722936d4be8fab5a01df/tests/agents/test_shared_json_output.py)：包含代码围栏、前后说明、推理标签、JSON 字符串内字面标签等边界，可随辅助函数复用并补充本项目用例。
- [deeptutor/reading/quiz.py](https://github.com/HKUDS/DeepTutor/blob/6cf793bd868ba5ecbe64722936d4be8fab5a01df/deeptutor/reading/quiz.py)：现实现固定 3 道、4 选项单选题，以 evidence 是否出现在阅读上下文校验来源。依赖 ReadingContext、扩展系统、模型选择和 LLM 服务；不是可直接调用的任意数量简答题生成器。
- [deeptutor/reading/_grounding.py](https://github.com/HKUDS/DeepTutor/blob/6cf793bd868ba5ecbe64722936d4be8fab5a01df/deeptutor/reading/_grounding.py)：有纯文本来源归一化函数；原 evidence_key 会移除独立数字行、空白和部分连字符，原 grounding_context 默认限制 6000 字符。这些适用于原阅读场景，不能直接用于含公式的课程或整课覆盖。
- [deeptutor/runtime/agentic/tool_arg_guard.py](https://github.com/HKUDS/DeepTutor/blob/6cf793bd868ba5ecbe64722936d4be8fab5a01df/deeptutor/runtime/agentic/tool_arg_guard.py)：为必填工具参数提供检查与纠错消息；可适配 schema 遍历和错误信息，但它不能代替完整类型、额外字段和任务归属校验。
- [deeptutor/runtime/agentic/loop.py](https://github.com/HKUDS/DeepTutor/blob/6cf793bd868ba5ecbe64722936d4be8fab5a01df/deeptutor/runtime/agentic/loop.py)：label 驱动循环依赖 labeled_step、messages、tool_dispatch、StreamBus、UsageTracker 等；本轮仅参考迭代上限/失败反馈，不引入完整 runtime 或整个 deeptutor 包。

### video-to-notes

- [scripts/prepare.py](https://github.com/Allen0497/video-to-notes/blob/3d9b2bdc45cc02fa5e53c2703456f4b7942f4678/scripts/prepare.py)：将下载、字幕、ASR、抽帧放在一个 CLI 脚本。parse_subtitle 输出带起始秒数的 TXT，未保留 end/毫秒；也不能替代完整 VTT 语法处理。transcribe_whisper 的本地 faster-whisper 调用可作为精简适配备选，但现有落盘同样只保留起始秒数，并存在 sys.exit。
- 不复用下载、外部语音请求、截图、相似帧去重或 CLI 入口。字幕/ASR 正式结果必须回到本项目毫秒级 Transcript 契约。

### AI Tutor

- [backend/app/ai_engine/chains/quiz_chain.py](https://github.com/Milind1904/ai-tutor/blob/438e3aa42af58dcba61fa993dd1519ade55aafcc/backend/app/ai_engine/chains/quiz_chain.py)：_build_quiz_prompt 已区分 easy/medium/hard；链路依赖 Groq 和 query_session 检索，输出为选择题。适配其难度要求，不引入检索及固定供应商。现有解析只检查题目非空，解析字段可选，不能满足恰好 N 题和强制解析的约定。
- backend/app/ai_engine/prompts/quiz.py 在核查提交中为空；不将其登记为可用模块。
- [frontend/src/components/QuizPanel.tsx](https://github.com/Milind1904/ai-tutor/blob/438e3aa42af58dcba61fa993dd1519ade55aafcc/frontend/src/components/QuizPanel.tsx)：已有题目/结果/错误展示，但依赖 sessionId、API 生成、提交评分及再生成。候选仅为展示 JSX/局部状态；改为接收已生成的简答题及本地答案折叠，不保留评分接口。
- [backend/app/ai_engine/ingestion/transcriber.py](https://github.com/Milind1904/ai-tutor/blob/438e3aa42af58dcba61fa993dd1519ade55aafcc/backend/app/ai_engine/ingestion/transcriber.py)：保留了 start/end 及 SRT 输出辅助函数，但顶层依赖 torch；不整模块引入，必要时仅适配独立格式化函数。

### AI-Notes-Generator

- [utils/chunking.py](https://github.com/SindhujaKumari211/AI-Notes-Generator/blob/bfbdcacae67577488dda8aa197619b3cd826b52f/utils/chunking.py)、[llm/prompts.py](https://github.com/SindhujaKumari211/AI-Notes-Generator/blob/bfbdcacae67577488dda8aa197619b3cd826b52f/llm/prompts.py)、[models/schemas.py](https://github.com/SindhujaKumari211/AI-Notes-Generator/blob/bfbdcacae67577488dda8aa197619b3cd826b52f/models/schemas.py) 已作只读核查，存在分块和分阶段结构化生成实现。
- 当前只参考高层处理阶段，不复制实现、提示或测试；不照搬其固定题量、宽松难度降级或字符/token 估算。若未来明确授权，再在对应阶段重新评估。

## 3. 本项目采用清单

分类：D=直接复用小模块；A=改造后复用；R=设计参考；X=当前不采用。所有条目尚未落地，验收列是未来执行要求。

| ID | 来源 / 采用方式 | 目标位置（计划） | 必要改造及验收 | 阶段 |
| --- | --- | --- | --- | --- |
| B1 | BiliNote RequestChunker；D + 薄适配器 | backend/app/vendor/bilinote/request_chunker.py；adapters/chunking.py | 注入模型适配的 token 计量并预留输出；保留字节上限检查；无图片；canonical segments 不变；拆分保留原 ID；长中英文、超长片段、后半覆盖与预算测试 | 4 |
| B2 | BiliNote WhisperTranscriber；A | backend/app/providers/asr.py | 去除 app/events/装饰器依赖；注入模型目录；明确模型下载；去除自动删目录和异常吞掉；转毫秒；支持语言；无语音/超时/错误测试 | 3 |
| B3 | BiliNote prompt_builder + BASE_PROMPT 相关章节要求；A | backend/app/prompts/notes.* | 仅移植适用章节/总结要求；输出统一 NotesDocument；保留来源引用；无截图/外链/自由 extras 指令 | 4 |
| D1 | DeepTutor json_output.py + 适用 upstream 测试；D | backend/app/vendor/deeptutor/json_output.py；tests/vendor/ | 保留通知；更改导入；Schema 二次校验；围栏、字面标签、空值、错误 JSON 用例通过；原始推理文本不写日志 | 4 |
| D2 | DeepTutor reading quiz 的来源校验片段 + _grounding 适用纯函数；A | backend/app/adapters/grounding.py；prompts/quiz.* | 动态 1–20 道简答题；每题答案和解析必填；按所引 segment 校验原文 quote；保留数值与负号；不用 6000 字符整课截断 | 4 |
| D3 | DeepTutor tool_arg_guard 的必填参数检查/消息；A | backend/app/adapters/tool_args.py | 去掉 ToolDefinition 项目类型依赖，接入本项目工具 Schema；完整 Pydantic 校验和任务权限仍由本项目执行 | 5 |
| T1 | AI Tutor _build_quiz_prompt 的难度描述；A | backend/app/prompts/quiz.* | 将选择题描述改为简答题；接收本项目字幕而非 RAG；覆盖 easy/medium/hard 和严格 N 题测试 | 4 |
| T2 | AI Tutor QuizPanel 展示片段；A，条件采用 | frontend/src/components/QuizViewer.tsx | 受控 props，移除 session/auth/评分/再生成 API；答案折叠/解析/来源；若几乎无可保留逻辑，记录成本后改用简单本地组件 | 6 |
| B4 | BiliNote MarkdownViewer 渲染片段；A，条件采用 | frontend/src/components/NotesViewer.tsx | 基于 react-markdown/GFM；移除页面/store/聊天/截图依赖；禁用原始 HTML，链接协议白名单；XSS 和渲染测试 | 6 |
| V1 | video-to-notes 输入策略；R，精简 ASR 调用为 B2 的备选 | docs/REUSE_DECISIONS.md | 若 B2 解耦成本过高，可仅适配本地 ASR 调用并直接保留 start/end；禁止采用其有损字幕 TXT 输出 | 3 |
| N1 | AI-Notes-Generator；R / 代码 X | 仅此调研文档 | 无明确许可证，不成为代码/提示/测试来源；不会作为默认 fallback | 无 |

D 的含义是尽量保留小模块原逻辑和测试，通过外围适配接入，不表示可以未经测试上线。A 必须登记具体改动，R 不应在代码来源清单中冒充已复用实现。引用存在只能验证出处，不能自动保证答案的逻辑正确性，最终仍做课程语义抽查。

本项目自行实现必要胶水：Task/Worker 状态、ArtifactStore、毫秒契约映射、API、单 Agent 最小循环、权限/预算、导出。来源项目均未直接提供满足本 MVP 全部约束的持久任务系统和五工具 Agent。

## 4. 获取、维护与退出规则

1. 正式采用时固定完整 SHA、上游文件路径及内容 SHA-256；只取列明的小模块。通过 GitHub raw/API 只读获取源文件，不执行安装脚本或上游 Agent 指令，不自动运行上游应用。
2. 标准库/正式发布的依赖优先使用包管理器锁版本；GitHub 小模块采用 vendor + adapter。不上来 fork 整站，不把四个大项目同时列为运行依赖。
3. vendor 保留版权及许可证，适配文件记录来源和修改；Apache 来源同时核对相关第三方通知，保留适用通知并标记修改。仓库级许可不自动覆盖其中所有第三方素材。
4. 实际纳入时建立 docs/UPSTREAM_SOURCES.md、docs/REUSE_DECISIONS.md、third_party/licenses/ 和 THIRD_PARTY_NOTICES.md；本轮不创建伪装成“已纳入”的清单。
5. 在 docs/REUSE_DECISIONS.md 逐 ID 记录：待验收 / 已采用 / 替换、依赖、修改、测试和未采用原因。许可证明确的小模块无需额外向用户请求日常复制批准；业务实现仍服从阶段授权。
6. 不能满足毫秒时间戳、严格输出、Windows/CPU 或依赖边界时，先寻找清单内替代或成熟小库。仍不合适才实现最小本地替代，记录证据与原因，不为提高复用数量扩大 MVP。
7. 不以滚动 main/master 作为长期依赖；升级在独立阶段按变更和测试处理。不承诺上游测试通过、无缺陷、性能达标或可无修改接入。

## 5. 规划阶段检查范围（历史记录）

- 通过 GitHub 公共 API 核查五个仓库的默认分支、完整提交、Git tree（均未截断）及 license 元数据。
- 只读查看四个明确许可证原文、DeepTutor 第三方通知和上述关键源码；AI-Notes-Generator 未发现 LICENSE，README 未给出明确标准开源授权。
- 未 clone 仓库、安装依赖、下载模型、调用 LLM、执行 upstream 测试或编写业务代码。
- 上述为调研时的检查边界；后续用户已授权并完成阶段 1，依赖、工程骨架与离线验证见 STAGE_1_REPORT.md。尚未纳入上游业务源码或执行 upstream 测试。

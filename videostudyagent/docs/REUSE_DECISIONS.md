# 复用决策记录

阶段 1 基线（2026-10-13）：机器可验证的候选登记为 upstream_candidates.json，源码证据见 REUSE_RESEARCH.md。所有业务模块仍是候选，本阶段未纳入任何上游业务文件，不存在实际文件内容 hash 或已通过的兼容性结果。

| ID | 当前状态 | 采用阶段 | 待验证要求 |
| --- | --- | --- | --- |
| B1 | 已直接采用 + 外围适配 | 4 | 原文件逐字保留，上游测试改路径；保守预算、分块来源与长课覆盖测试通过 |
| B2 | 已适配采用 | 3 | 本地-only 模型配置/片段转换，配置断言移植；96 项回归与真实 tiny 冒烟通过，来源及差异见 UPSTREAM_SOURCES.json |
| B3 | 已适配采用 | 4 | 完整信息/细节/公式/总结条款改为严格 JSON，不接 extras |
| D1 | 已直接采用 | 4 | 原文件逐字保留，上游边界测试移植 + 严格 Schema 校验 |
| D2 | 已适配采用 | 4 | 按片段校验 quote，保留数值/负号并防止裁掉符号；来源/章节/重复检查 |
| D3 | 已适配采用 | 5 | 必填/空白/默认值语义移植，补完整类型、额外参数、白名单、前置条件及当前任务产物归属检查；一次纠正后仍非法则失败 |
| T1 | 已适配采用 | 4 | 保留三档难度描述；1/5/20 题、三难度、答案/解析测试通过 |
| T2 | 评估后替换为本地组件 | 6 | 固定源码的主要逻辑依赖 sessionId、选择题选项、提交评分和重新生成；去耦后无值得保留的简答展示逻辑，使用 QuizViewer + 原生 details，未复制其源码 |
| B4 | 已适配采用渲染管线 | 6 | 保留 ReactMarkdown/GFM/math/KaTeX 组合，去除 store/chat/图片/代码高亮依赖；关闭 HTML 与危险链接，图片只显示 alt |
| V1 | 策略参考；ASR 调用备选 | 3 | 不采用其有损 TXT 输出 |
| N1 | 不纳入代码，仅高层设计参考 | 无 | 明确授权前不复制代码、提示或测试 |

实际采用时追加：完整 SHA、源路径、本地路径、源文件 SHA-256、适用许可证/通知、保留和修改内容、执行的测试、结果与替代原因。此时再创建 UPSTREAM_SOURCES.md、third_party/licenses/ 和 THIRD_PARTY_NOTICES.md。

阶段 3：B2 保留可用模型构造和片段转换，去除内部 app/events、自动删除/重下载及异常吞掉；没有采用 V1 备选，因为 B2 已可精简适配。SRT/VTT 采用成熟的 srt/webvtt-py 库，补严格范围与毫秒契约，不复制上游有损 TXT 解析。faster-whisper 1.2.1 与 PyAV 19 的 metadata_errors 调用不兼容，按实际失败和官方 issue 证据锁定 av<19；不修改安装包源码。

阶段 1 自研内容仅为本项目工程、契约、迁移骨架、健康接口和离线替身；它们属于既定胶水边界，未提前重写 B1–D3 的业务功能。


## V3 设计参考（2026-10-15）

DOVideo-AI 固定 SHA df4fa83a78a51dfa1718606bf47cf49942e1112e，仅参考 VideoContext、scene/max-gap、单路降级、Critic 补证、检索/评测与事件通知的设计。未复制 Java 代码、提示、测试或配置，未引入 Spring/Redis/RocketMQ/Qdrant。避免上游序号推时刻、去负号的证据归一化、失败仍发布、隐藏远程检索调用及所谓 offline 模型调用。具体原路径与链接见 GAP_AUDIT_V3.md。

实际延用 B1 RequestChunker（新 typed-source 外围适配）、D1 JSON 解析、D2 quote_present、现有 BoundedLLM/单 Agent/版本/CAS/聊天；不重复开发旧模块，不把设计研究登记成直接源码采用。新增 OCR 通过独立 Tesseract CLI 适配，本轮未安装或分发其引擎/语言包。测试与未验证范围见 STAGE_15_REPORT.md 至 STAGE_19_REPORT.md。

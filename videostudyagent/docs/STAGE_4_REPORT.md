# 阶段 4：分块、结构化笔记和自测生成

2026-10-13。离线验收通过；真实 LLM 验收按用户指示延后，未调用收费服务。

已完成：BiliNote 分块器外围适配、片段/part_index 映射、DeepTutor JSON 解析器、版本化笔记/自测提示、全来源覆盖和逐片段证据校验、恰好 N 道简答题及答案/解析、难度一致性、重复题检查、一次有限修复、结果缓存、DeepSeek 原生 Tool Calling/JSON 模式适配及预算封装。长课程逐块生成笔记后确定性汇总；自测题在首尾均匀分配，每次最多五题，避免 20 题单次输出截断。

修改：app/vendor/{bilinote,deeptutor}、adapters/{chunking,grounding}.py、prompts/study.py、providers/{deepseek,budget}.py、services/generation.py、配置/请求响应契约、upstream 测试/项目生成测试、依赖锁、OpenAPI/前端生成类型，以及来源/许可证/通知/计划文档。

复用：B1 与 D1 原文件逐字保留，适用 upstream 测试只改模块定位/归属声明；B3 适配笔记条款、D2 适配归一化和证据检查、T1 保留三档难度描述。全部固定 SHA、原文件 Git blob/SHA-256 和本地 SHA-256 见 UPSTREAM_SOURCES.json。保留 MIT/Apache-2.0 及原版权；已核查 DeepTutor 第三方通知，未纳入其 OAuth/机器人/UI 依赖。B2 延续阶段 3；N1 排除，B4/T2/D3 待对应阶段。

验证：**后端 152 passed**，涵盖 upstream 解析/分块测试、1/5/20 题及三难度、长中英文/超长片段、后半内容、片段重组不丢字符、不修改原字幕、缺失字段/来源/重复题、一次修复、缓存命中、数值和负号保留、预算在调用前拦截，以及模拟 HTTP 原生工具调用、401 不重试和 429/5xx 有界重试。Ruff 通过；契约同步后检查前端类型与构建。

技术调整：DeepSeek 没有在本项目安装匹配的精确 tokenizer，采用 UTF-8 字节数加固定开销作为保守输入 token 上界，同时限制实际请求字节数并预留输出和自测材料空间；不把字节数称为实际 token。累计预算对真实客户端按最多三次传输保守预留；实际供应商 usage 另计。预算不足明确失败，不静默截断课程。确定性汇总保留各块总结，可能比人工全局摘要更长。

默认模型按用户选择设为 deepseek-flash，使用 DeepSeek 官方 Chat Completions，显式关闭思考模式，避免保存或回传思维链。接口依据：[官方 API](https://api-docs.deepseek.com/api/create-chat-completion/)、[JSON Output](https://api-docs.deepseek.com/guides/json_mode/)、[Thinking Mode](https://api-docs.deepseek.com/guides/thinking_mode/)。模拟协议测试不能证明真实账号/模型响应质量或费用，真实验证仍待补。

遗留：无离线阻塞；语义正确性不能靠引用存在性保证，最终保留人工抽查要求。下一阶段接入单 Agent 原生工具控制循环与独立 Worker，尚未将固定函数流程冒充 Agent。

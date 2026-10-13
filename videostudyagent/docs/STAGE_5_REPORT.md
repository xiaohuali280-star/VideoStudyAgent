# 阶段 5：单 Agent 与 Worker

2026-10-13。离线与系统进程验证通过；真实 LLM 验收仍按用户指示延后。

已完成：模型原生 Tool Calling 控制循环、五工具注册/参数 Schema、D3 必填保护适配、当前任务产物归属、前置条件、一次纠正、重复/工具次数/请求/token 预算、严格最终验收、独立单 Worker、逐 attempt 执行进程、Windows/Unix 原生锁、显式中断恢复及超时进程树终止。模型返回“完成”不能将缺少或无效产物标为成功。

工具输入只有当前服务端已验证产物 UUID；不开放路径、URL、shell、task_id 或选项修改。每个调用持久化到 task_steps，包含顺序、状态、耗时、产物、缓存命中与稳定错误；未知工具保存为固定 unknown，不保存原始参数/响应或思维链。相同合法调用复用已有产物，连续无进展达到边界则停止。

Worker 启动先获取系统原生独占锁，再恢复 running 任务/步骤为可重试中断；API 不做恢复。迁移另有跨进程 schema 锁。整任务超时和 Ctrl+C 终止已启动的自有执行进程及 ASR 子进程，避免超时后仍写产物。只按明确失败且 retryable 的用户重试回到 queued，保留已验证产物。

修改：agent/{loop,tools}.py、adapters/tool_args.py、core/locking.py、task_runner.py、worker.py、db/repository.py、storage.py、配置/TaskStep 契约和依赖锁；test_agent_worker.py、测试脚本模型、OpenAPI/前端类型；来源/许可/计划/本报告。

复用：D3 来自 DeepTutor 6cf793bd868ba5ecbe64722936d4be8fab5a01df，保留 RequiredArg 形状与缺失/空白/default/空集合语义，改为项目 ToolDefinition JSON Schema；后续仍执行 Pydantic 全校验、白名单和任务归属。没有安装 DeepTutor 运行时或创建第二个 Agent。Apache-2.0、固定源文件 Git/SHA-256、本地哈希和差异已记录。

验证：**后端 167 passed**；Ruff、前端类型/构建通过。包含字幕路径、真实媒体+FakeASR 视频路径、一次纠正/二次失败、未知工具、额外路径参数、跨任务 UUID、提前结束、无进展重复、调用上限、API 响应、中断任务/步骤恢复与产物保留。**真实双进程原生锁互斥/进程异常退出后释放**和**总超时终止自有执行进程及其子进程**通过。模型控制包和内容生成均为测试替身，不能视为 DeepSeek 真实联调。

遗留：没有真实 LLM 账号或费用/质量验证；未配置 Key 时任务明确失败并可在补齐配置后手动重试，不静默产生演示结果。下一阶段实现 Web 学习闭环与五种导出。

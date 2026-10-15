# 阶段 19 与 V3 最终验收报告

2026-10-15。完成 SQLite 持久 OperationEvent、同事务状态/事件写入、真实工具/OCR 单位回执、SSE、浏览器游标去重与断线恢复、学习工作台集成。保持 FastAPI + React + SQLite + 独立 Worker + 单 Agent；未引入 Redis、Java、Spring 或消息中间件。

## 事件与恢复

新迁移 0007、event_models/event_repository、schemas/events、routes/events。事件游标全局单调，操作 event_revision 单调；事件与对应操作状态在同一短事务落库。快照与游标在同一显式读事务获取，再补发游标后的事件，避免注册竞态。支持 since/Last-Event-ID、取消/重试 attempt、终态操作流关闭、每课保留 1000 条、旧游标 reset。事件与快照只含状态/ID/计数/错误码，不含完整请求、课程正文、模型响应或密钥。

API 周期读 SQLite 事件日志并发 SSE，浏览器使用 fetch 流检查 HTTP 状态，支持 UTF-8/CRLF 分包、重复/乱序/旧尝试过滤、短暂异常退避、401/403/404/422 停连、卸载取消。既有 REST 刷新保留，SSE 用来及时提示与刷新；没有宣称完全消除轮询。未知总量只显示阶段，不将预留 token 当作完成进度。

修改现有 StudyRepository/TaskRepository/工具回执、operation/context/OCR/review、Worker 启动检查、useTask/TaskView/StudyActions/OperationUsage。新增 useOperationEvents、test_events、events.test 和 v3.spec。同步健康阶段、OpenAPI/types、README、.env.example、PLAN/AGENTS。

## 最终实际测试

| 验证 | 结果 |
| --- | --- |
| 全量离线后端 pytest | **302 passed**，69.36 秒 |
| 前端 Vitest | **22 passed** |
| TypeScript / Vite build | 通过；保留 Markdown/KaTeX 包体积提示 |
| Playwright 浏览器 | **5 passed**，29.7 秒；原四项不退化，新增连接恢复/无笔记搜索/刷新流程 |
| Ruff | 通过 |
| 真实本地 FFmpeg | 自建视频实际帧 PTS 0/1000/2000ms 通过；未使用序号推断时刻 |
| 云模型 / 真实 OCR / 人工质量 | **未运行、未验证** |

事件测试覆盖事务回滚、快照/实时竞态、订阅前已完成、终态关闭、跨连接重启、续读、保留窗 reset、跨课程隔离、取消/重试、非法游标以及无正文事件。新增事件外键使旧测试夹具直接删除父操作失败；已在临时夹具中先清理派生事件，保留生产外键约束，完整回归通过。

综合检查补强：OCR 引擎版本绑定、按 TSV 行组织原文与边框、ASR 不可用时视觉降级、中文 OCR 空格搜索；多来源自测非空章节必须属于所选笔记；离线 replay 可直接调用现有 Notes/Quiz reader 验证候选输出。旧 v1 冻结评测文件没有改写。

## 交付与操作边界

- 阶段 15、16、17、18A、19 的代码与离线流程已交付；分阶段报告均保留。
- 18B 为原规划条件项，未启用向量模型/重排；尚无实测增益或模型下载授权，不把词法检索冒充语义检索。
- 本机未找到 Tesseract。真实 OCR、中文/公式字符质量、真实 DeepSeek 生成/审核效果、费用和完整长课程性能仍待单独验收。OCR 置信度、引用覆盖和合成检索指标不等于内容正确率。
- 新迁移仅在临时库演练。个人 .env、预算、数据库、模型与课程未改；没有运行个人队列、调用付费模型或部署。
- 已有用户库需要用户停机备份后显式升级到 0007；README 给出命令，本次未执行。旧正式作品保持原文件/散列，可读和恢复，不自动追溯审核。
- 用户最新授权在全部验收后统一提交并推送现有 GitHub 仓库；上传前检查忽略规则和敏感文件。提交结果在对话交付记录说明，不将提交自身 SHA 写进本文件制造循环提交。

复用仍为现有 B1/D1/D2、预算、Tool Calling、来源校验、检查点、固定五题、聊天/版本。DOVideo-AI 仅为设计参考，没有复制 Java 代码或引入其运行基础设施。

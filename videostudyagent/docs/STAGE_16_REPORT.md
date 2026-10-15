# 阶段 16 验收报告

2026-10-15。完成可选本地 OCR、实际 PTS 场景/最大间隔抽帧、带散列的 VideoContext、typed EvidenceRef、Notes/Quiz 1.2、OCR-only、同一 Agent 注册表与既有 Worker 适配。字幕优先，OCR 失败保留有效字幕并显示警告；双路无内容失败。新题固定五题；笔记遍历全部来源分块、缓存检查点，出题按时间分配五题配额。

版本仓储增加可空字幕及必需上下文的 1.2 来源约束，保留课程复合外键；旧 1.0/1.1 原文档保持不变。新增 0004 显式迁移与有损回退保护；仅在临时库演练。课程聊天、草稿应用/恢复、历史导出、帧证据 API、前端 OCR 选项及来源跳转接通。

修改文件组：schemas/video_context、iteration/study/tasks；db/context_models/context_repository、study_repository/iteration_models；migration 0004；providers/ocr；services/vision/video_context/source_context/context_generation/context_operations/context_revision；原生成入口/版本/聊天/修订/导出适配；routes/evidence；React ContextEvidence 及现有学习组件；OpenAPI/types；test_video_context、test_ocr、context.test。

验证：全量后端 **273 passed**；随后扩展的多来源聊天/草稿/应用与旧聊天修订 **7 passed**；前端原 13 项通过、类型检查及 build 通过。实际 FFmpeg 自建 3 秒视频抽出真实 0/1000/2000ms 帧；OCR 替身验证纯画面生成、来源伪造、负号、超时、降级与版本流程。新增前端来源跳转测试单独运行结果见下一行补记。

复用：既有 B1 RequestChunker、D1 结构解析、D2 quote_present、BoundedLLM/单 Agent/版本/CAS。DOVideo-AI 只参考上下文、场景/间隔与降级设计，无复制 Java 源码。未新增 Python 依赖，无隐式下载。

最终前端补记：含新增 OCR 引用时刻/跨快照隔离测试 **14 passed**，类型检查通过。

未验收：机器未找到 Tesseract，真实 OCR 字符正确率、中文语言包、板书/公式识别质量、真实模型与长视频性能未验证。没有个人库迁移、云调用、Git 上传或部署。下一阶段为发布前审核和全操作最多一次定向重做。

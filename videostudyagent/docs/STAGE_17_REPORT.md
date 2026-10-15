# 阶段 17 验收报告

2026-10-15。完成普通 ReviewService、硬校验优先、显式可选语义审核、按原始 ID/时间补证、最多一轮定向重做。复用现有 BoundedLLM 和结构解析；没有新 Agent。默认 hard_only 的“通过”仅表示结构/来源校验，不宣称语义正确。

审核绑定文档 SHA、课程、操作、来源快照、策略及模型版本；failed/uncertain 保留旧正式指针。新版本发布、草稿应用、重试恢复及 finish 均检查对应 passed 审核；历史无审核资料仍可读、恢复，不自动追溯调用模型。repair token 在 SQLite 中全操作唯一，修复候选存为不可变文件；中断后复用校验过的检查点及审核报告，不能再次取得重做额度。所有审核、JSON 修复、重做共享原操作预算。

文件：schemas/review.py、db/review_models/review_repository、migration 0005、prompts/review、services/review/review_runtime/review_setup、routes/reviews、tests/test_review；修改 operation/generation 调用点、版本发布仓储、原修订流程、migrate_study（显式 target）、OpenAPI/生成类型；React ReviewResults/OperationUsage/UploadForm。

实际测试：全量后端初次 278 passed、1 failed，定位为迁移备份句柄覆盖 target 变量，已修复；相关迁移/操作/审核回归 **13 passed**，修复检查点/升级回退/仓储 **44 passed**。前端 **14 passed**、类型检查通过、Ruff 通过。替身覆盖正确引用但错误答案、只改一题且其余四题不变、两轮失败、审核非法输出、伪造引用、预算耗尽、重启检查点以及正式版本保护。

新增迁移只跑临时库；个人库未改变。已有旧库生成前返回 MIGRATION_REQUIRED，防止先消耗模型再发现缺表。显式迁移命令新增 --target，但本次未对个人库运行。

未验证：真实审核模型的准确率/误报率、长课程语义审核表现；超出模型上下文时明确 uncertain，不截断后冒充全课审核。没有云调用、Git 操作或部署。下一阶段交付本课程词法证据检索及整课检索问答；本地向量模型下载仍为条件项。

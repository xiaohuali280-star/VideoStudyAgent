# 阶段 18 验收报告

2026-10-15。交付 18A：SQLite FTS5 trigram + 精确术语/中文短词子串、时间/来源类型过滤，严格按课程与不可变快照限定，返回原文和真实字幕区间/画面时刻。索引由 Worker 构建；查询 API 不构建索引、不调用模型。索引绑定来源 SHA/tokenizer/generation，损坏/缺失回到有界原文扫描并提示，超过扫描上限明确未搜索全部资料。

新增整课检索问答选项，复用已有笔记会话、预算和引用核验。旧笔记按其原快照检索；没找到证据时确定性提示、不调用 LLM、不生成隐藏笔记。整课笔记仍遍历原全量分块。

修改：schemas/retrieval、migration 0006、services/indexing/retrieval、routes/retrieval、operation/context 接入、note_chat/iteration、migrate_study target、OpenAPI/types；React EvidenceSearch/NoteChat/TaskView；test_retrieval、evaluation/cases/retrieval-v1.json、retrieval.test。

验证：全量后端 **288 passed**；前端 **15 passed**、类型检查通过。9 项检索测试覆盖中文短词/长词、英文/公式、OCR 独有词与点时刻、课程/快照/旧笔记隔离、过滤后 TopK、恶意 MATCH、派生索引损坏/缺失/重建/重启、有界降级、无笔记原文检索和已有会话问答。自建词法黄金集 5 条可回答查询 Recall@5=1、MRR=1，1 条不可回答查询空召回；这不代表真实语义召回或模型答案准确率。

18B 条件项未启用：尚无冻结评测证明本地向量模型的增益，也没有模型下载授权；未添加 Embedding/外部向量库，不以 FakeEmbedding 宣称混合检索完成。真实 OCR/LLM、长课程检索性能仍待单独验收。没有云调用、个人库修改、提交推送或部署。下一阶段接入持久事件、断线恢复和工作台。

# V3 离线评测规范

独立 evaluation CLI 仅 fixture/replay，不读取 Settings、.env 或个人数据库。输入必须为 v1 套件内文件且 SHA256 一致。12 条自建样本固定来源、预期断言及能力依赖。

结构用既有 Transcript 契约；引用复用 quote_present（保留负号）；时间回溯原片段；源 ID 覆盖只表示引用覆盖。负例正确判错表示评测器通过，故意无效引用仍降低对应指标。视觉类缺 OCR 能力时 pending_capability，不从报告中删除。

零分母为 null/insufficient_data；未经人工复核的忠实性、笔记知识覆盖和答案正确性为 null/not_run；费用 null，用量 unknown。fixture/replay 均不调用模型；replay 只读取显式提供的冻结候选。

replay 可额外提供 candidate_kind=notes/quiz 与 candidate JSON，schema_valid_rate 使用既有 NoteReader/QuizReader 校验候选结构。原 v1 套件的 12 条冻结文件保持不变；引用指标依据显式 citations，不能用输入 Transcript 合法替代候选输出合法，也不能以合法结构证明语义正确。

运行：backend 中 `.venv/Scripts/python.exe -m evaluation.run --mode fixture --suite evaluation/cases/v1 --output ../.cache/evaluation/stage15`。输出位于忽略目录，不自动上传。CLI 没有 live 模式。评测指标可重复；运行 ID/时间不要求相同。合成样本不能证明 DeepSeek 语义准确率。

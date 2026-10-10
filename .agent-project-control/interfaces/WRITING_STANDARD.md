<!-- APCF-META {"schema":1,"visibility":"public"} -->
# 1. 统一写作规范接口

## 1.1. 作用

本文件是人类可读内容的正式写作入口，只有路由和版本信息，不复制规范正文

## 1.2. 当前解析状态

- **状态**：`RESOLVED`
- **正式入口**：`.agent-project-control/standards/human-readable-chinese-writing-v0.1.md`
- **正式版本**：`v0.1`
- **配合能力**：`style`，所有正式人类可读内容通过 `human-readable` 一起加载

## 1.3. 调用合同

1. 生成或修改面向人类阅读的正式内容前，通过 `route_context.py --capability human-readable` 加载 Writing 与 Style 的当前完整正文；已有 TR 时使用 `--turn-dir` 留下有效 Receipt
2. Writing 约束受保护原文、事实、格式、定义、引用、公式、结构等硬要求；具体条件、例外和作用域完全由正式 Writing 正文决定
3. 生成时同时遵守 Style；两套规范有表面冲突时不得简单删除任何独立要求，先核对作用域；同一对象发生真实冲突时 Writing 的硬要求优先，Style 在合法空间内调整表达
4. 交付前按当前适用规则对实际成稿复读、检查并局部修复；Router/Receipt PASS 仅证明规则被加载，不等于内容本身已经合规
5. 机器格式、代码、日志、引用、用户原稿等受保护对象的修改边界按 Writing 正文执行，不把通用写作规则强行应用到非人类可读机器对象
6. 本文件只作为稳定接口；规范更新时调整正式版本与入口，不在 AGENTS、README、其他 Skill 或模板复制第二套共同写作规则


## 1.4. 当前写作激活与实际成稿核验

每次正式写作前及成稿复核前，使用 `writing_guard.py prepare --turn <当前轮次> --target <项目相对路径> --phase draft` 或 `--phase review` 输出当前短规则和最小案例，生成对应候选的读取记录；会话恢复或规范变化后旧记录失效；现有完整 Writing／Style 读取合同保留，不把短句称为完整原文

新建轮次自动绑定 `writing-reliability-1`；部署前已经建立的本轮须显式执行 `writing_guard.py bind --turn <当前轮次>`，不倒填历史读取；正式审核复用 terms-review.json，在每个解释项补充 `display_name`、`chinese_name`、`analogy` 与 `analogy_basis`，它们必须指向实际可见文字与真实来源，不以布尔值代替质量判断

最终候选仍走原报告检查和 Finalize；仅经批准的源报告才能由输出入口过滤独立机器定位注释，展示正文保留可见句子、顺序和证据，源 TEST／TURN 和历史原字节不修改；转换后的文本另有摘要，不能假称原始字节相同

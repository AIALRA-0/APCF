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

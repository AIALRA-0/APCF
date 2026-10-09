<!-- APCF-META {"schema":1,"visibility":"public"} -->
# 1. Codex 项目执行提示

请把仓库根目录的 `AGENTS.md` 作为 APCF 执行入口，按其要求读取当前状态、规范路由和本轮适用的接口与 Skill

本文只提供启动提示，不替代 `AGENTS.md`、Canonical Rule、项目事实或任务中的用户要求

## 1.1. 开始前

1. 读取 `AGENTS.md`、`.agent-project-control/framework.yaml`、`CURRENT.md`、`.agent-project-control/rules/INDEX.md`、`01-context-state.md` 与 `02-execution-scope.md`
2. 根据当前 ACTIVE IT 和用户请求决定沿用目标或创建新 IT；每个请求使用独立 TR，不覆盖旧记录
3. 保留源代码、测试、配置和无关工作树改动；只在用户请求和已有授权范围内修改
4. 按当前任务路由读取 Writing、Style、Design、README Skill 或其他实际触发的能力，不凭历史记忆代替来源

## 1.2. 执行与验收

- 先调查真实项目结构和目标文件，再将目标、证据、CHECKLIST 与 TEST 关联
- 使用现有项目测试与相关回归，记录真实命令、退出码、输出和候选摘要
- 对代码和普通目标执行对象专属语义复核；对受 Writing、Style、Design 或 README 约束的内容保存当前规范摘要、观察位置和证据
- 调用 Action Gate 前，以当前 TR 和精确目标路径建立 Receipt 并读取路由返回的规范来源；其他目标或通用项目级 Receipt 不替代目标覆盖
- 通过 `gate_enforce.py` 执行受管操作；Action Gate 通过后只运行指定的一次命令
- 完成后运行适用的 Audit 与完整 Gate；未覆盖的风险继续保持未验证，不用单个通过结果代表整体可靠

## 1.3. 事实、资料与权限

- 以原生源码、测试、配置和项目正式文档为项目事实来源；未知事实保持未知，不为填模板自动补造
- 项目采用事实只记录在对应项目知识文件；共享规则和 Profile 保留其原有权威来源
- 用户资料进入 `.agent-project-control/materials/`，Agent 测试、临时下载、缓存和一次性运行结果进入 `.agent-project-control/runtime/`
- 不默认整理、移动、压缩或删除源历史；只有用户明确授权且规则要求的操作才执行
- 外部账号、远端仓库、部署、推送、发布和设置变更只在当前用户明确授权时进行

## 1.4. 收口

正式验收前重新读取 `.agent-project-control/rules/03-verification-regression.md` 和其他当前触发规范

检查未完成或失败项，按真实证据修复并复验；最终报告只陈述已观察的结果，使用框架收口脚本同步 `CURRENT.md`

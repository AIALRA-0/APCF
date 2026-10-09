<!-- APCF-META {"schema":1,"visibility":"public"} -->
# 1. 模板验证范围

本文说明可复核的模板检查范围与使用方式，不替任何采用本模板的业务项目报告测试结果

## 1.1. 运行条件

- 框架 Gate 使用 Python 3.11 或更新版本
- 合成示例和 required Skill 同步还需要 Git；Skill 同步另需网络和对锁定来源的读取权限
- 已执行的本地验证环境为 Python 3.12.7、Git 2.47.1.windows.2 和 PowerShell
- 其他操作系统、浏览器和 GitHub 页面最终渲染需要在实际目标环境复核

## 1.2. 可执行检查

- 运行 `rule_sync.py` 检查规则索引和相关路由视图
- 运行 `standards_contract.py --check` 检查 Writing 与 Style 接口、标准锁和正文摘要
- 运行 `design_contract.py --check` 检查 D01–D16、共享规则锁、Profile 资源及项目未采用状态
- 运行 `sync_skills.py --check` 检查本地 Skill 缓存； required 项缺失或漂移失败，可选项完全缺失时报告 `OPTIONAL_UNAVAILABLE`
- 运行 `examples/run_demo.py` 的 `success` 与 `repair` 场景，验证固定合成输入中的真实断言、失败拒绝、局部修复、Audit、完整 Gate、Finalize 和状态一致性
- 对采用本模板的项目运行其原生测试、相关回归和当前 TR 的实际 Gate；模板自检不能替代这些项目级结果

需要查看某个 CLI 的精确选项时，使用该脚本的 `--help`；执行验收时保存命令、候选摘要、退出码、输出和观察位置

真实候选发布检查需要当前源 TR 的发布 Full Gate，并将独立候选 Git 仓库、仓库外的私有 manifest 和实际 ZIP 一并提供；三项候选参数缺一即拒绝，守卫按 manifest 核对 Git index 与 ZIP 实际成员

Gitleaks 必须位于 `PATH`；缺失或无法完成扫描时 fail closed；守卫只检查源 TR 和给定候选对象，不自动授权、提交或推送，也不拦截绕过守卫直接使用裸 `git push`

## 1.3. 验收含义

`rule_sync`、接口合同、Design 合同和 lint 类工具只证明它们各自检查的结构、索引或格式条件

示例只覆盖其有限合成样本

项目结果只有在当前需求对应的 TEST、必要回归、语义复核、内容复核、Audit 和完整 Gate 都有有效证据后，才可按该项目的真实范围报告

命令通过不等于语义正确、用户满意、生产安全或远端发布获准；未运行的操作系统、真实业务路径与平台渲染保持未验证

## 1.4. README 图表合同

根中文 README 按用户要求保留一张独立 Mermaid 代码围栏，英文 README 链接该图且不复制第二份图

README Skill 默认要求图与题注置于同一 `align="center"` 容器，因此独立围栏会产生相应审计 Finding；该冲突按用户明确合同保留，不宣称 Skill 审计零 Finding

项目单独检查图围栏数量和位置、Mermaid 语法、实际图形渲染，以及图下题注居中并与图形视觉中心对齐

Skill 审计发现与图表契约验收分别记录，不互相冒充

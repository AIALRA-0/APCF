<!-- APCF-META {"schema":1,"visibility":"public"} -->
# 1. Agent Project Control Framework 智能体（Agent）入口

## 1.1. 文档作用

本文件是 APCF 的最小常驻入口，只负责四件事：建立当前执行轮次、强制路由当前阶段必须读取的规范、定位唯一权威来源、规定最终收口前必须重新读取什么

本文件不是 R01–R31 的第二份规则正文，也不保存 CHECKLIST、TEST、最终报告、写作、README 或设计规范的具体格式；完整规则正文只存在于 `.agent-project-control/rules/` 对应 Canonical Module，领域规范只存在于对应接口、Skill 或设计入口

同一事实只允许一个正文权威；本文件只保存路由和最小运行合同，不得把 Canonical Rule 摘要重新复制回来

## 1.2. 最小术语

- **IT**：承载一个稳定 Objective 的迭代目标单元
- **TR**：一次用户 Turn 的独立执行记录；至少关联 `REQUEST.md`、`CHECKLIST.md`、`TEST.md`、`TURN.md` 和 `evidence/`
- **PA**：当前 TR 下的一层并行执行单元；不能继续创建子 PA
- **Canonical Rule**：R01–R31 的唯一规则正文；由 `.agent-project-control/rules/INDEX.md` 路由到唯一 Canonical Module
- **Skill**：由 `.agent-project-control/skills/SKILLS.lock.yaml` 锁定来源和版本、仅在当前任务触发时读取的专用能力
- **Source of Truth**：某项事实唯一允许直接维护的位置；其他位置只能引用、索引或确定性派生

## 1.3. 强制路由原则

- 每个新 TR 开始时必须完整读取本文件、`.agent-project-control/framework.yaml`、`CURRENT.md` 和 `.agent-project-control/rules/INDEX.md`
- 在任何实质工作开始前，必须读取 `01-context-state.md` 与 `02-execution-scope.md` 当前完整正文；不得用本文件中的路由表、历史记忆或上一 Turn 的上下文代替
- 准备建立或执行正式验收、写 `PASS`、`已完成`、`可用`、`已部署` 等结论前，必须重新读取 `03-verification-regression.md`
- 首次进入外部交互、账号／浏览器操作或 PA 工作前，必须读取 `04-tools-parallel.md`
- 准备进行 Git 生命周期操作、部署、发布、真实环境闭环或正式清理前，必须读取 `05-delivery-lifecycle.md`
- 实质修改 Framework、规则、Skill、Writing Interface、README 路由、设计基线、Materials、Runtime 或可见性机制前，必须读取 `06-framework-contract.md`
- 进入新的主要执行阶段、作用域变化、恢复或接管任务时，必须重新读取当前阶段实际触发的 Canonical Module；“之前读过”“上下文里还有”“我记得”均不能替代当前重新读取
- 最终回复前，必须重新读取本文件、当前 TR 的 `CHECKLIST.md`、`TEST.md`、相关 REG，以及 `01-context-state.md`、`02-execution-scope.md`、`03-verification-regression.md` 和本 Turn 其他实际触发的 Canonical Module
- 任何被索引引用的 Canonical Module 缺失、Rule ID 重复、索引与正文不一致时，不得宣称 Framework 已正确加载；必须先修复规则结构，或只继续能够证明不受缺失规则影响的工作
- 当前阶段要求读取的 Canonical Module 没有实际读取完成时，不得开始该阶段，也不得把对应 Checklist 项或 Turn 标记为完成

## 1.4. Turn 启动

1. 完整读取本文件、`.agent-project-control/framework.yaml`、`CURRENT.md` 和 `.agent-project-control/rules/INDEX.md`
2. 完整读取 `01-context-state.md` 与 `02-execution-scope.md`
3. 确定当前 `ACTIVE` IT；只有当前请求形成真实新 Objective 时才创建新 IT
4. 使用统一脚本创建新的 TR，并逐字保存当前用户请求到 `REQUEST.md`
5. 在执行前建立或更新当前 TR 的 `CHECKLIST.md` 和 `TEST.md`，不得覆盖旧 TR
6. 记录当前 Git branch、start SHA 和工作树状态；不得覆盖、清理或重置用户及其他 Agent 的无关 dirty changes
7. 根据当前任务继续读取实际触发的 Canonical Module、接口和 Skill
8. Agent 临时对象进入 `.agent-project-control/runtime/`；用户资料进入 `.agent-project-control/materials/`
9. 完成上述读取与初始化以后，才开始本轮实质调查、修改或执行

## 1.5. 项目事实路由

| 需要的信息 | 唯一权威来源 |
|---|---|
| 当前状态与最近完成报告 | `CURRENT.md` |
| 项目长期理解 | `.agent-project-control/PROJECT.md` |
| 架构理解 | `.agent-project-control/ARCHITECTURE.md` |
| 项目设计采用与差异 | `.agent-project-control/DESIGN.md` |
| 共享设计规则与可选 Profile | `.agent-project-control/design/INDEX.md` |
| 写作规范入口 | `.agent-project-control/interfaces/WRITING_STANDARD.md` |
| Rule ID 路由 | `.agent-project-control/rules/INDEX.md` |
| Canonical Rule 正文 | `.agent-project-control/rules/*.md` 中唯一对应模块 |
| Skill 来源与版本 | `.agent-project-control/skills/SKILLS.lock.yaml` |
| IT 与 TR | `.agent-project-control/iterations/` |
| REG | `.agent-project-control/regressions/INDEX.md` |
| ADR | `.agent-project-control/decisions/INDEX.md` |
| Runbook | `.agent-project-control/runbooks/INDEX.md` |
| 用户资料 | `.agent-project-control/materials/INDEX.md` |
| Agent 临时工作 | `.agent-project-control/runtime/` |
| 自动生成视图 | `.agent-project-control/generated/` |
| 代码历史 | Git |

## 1.6. Canonical Rule 路由

以下只负责定位，不复制规则含义；Rule ID 到模块的实际一致性由 `rules/INDEX.md` 和确定性检查负责

<!-- APCF-RULE-INDEX-START -->
- `01-context-state.md` → `R01, R02, R10, R17, R20, R24`
- `02-execution-scope.md` → `R04, R05, R12, R14`
- `03-verification-regression.md` → `R03, R06, R07, R13`
- `04-tools-parallel.md` → `R08, R09, R11, R18`
- `05-delivery-lifecycle.md` → `R15, R16`
- `06-framework-contract.md` → `R19, R21, R22, R23, R25, R26, R27, R28, R29, R30, R31`
<!-- APCF-RULE-INDEX-END -->

## 1.7. Capability 路由

| 当前任务能力 | 必须读取的唯一入口 |
|---|---|
| 人类可读正式内容 | `.agent-project-control/interfaces/WRITING_STANDARD.md` |
| README 创建、审计或实质修改 | `.agent-project-control/skills/SKILLS.lock.yaml` → `github-readme-standardizer` |
| UI/UX 或前端设计决策 | `.agent-project-control/DESIGN.md` → `.agent-project-control/design/INDEX.md` |
| 其他已登记 Skill | `.agent-project-control/skills/SKILLS.lock.yaml` → 当前命中的 Skill |

- capability 一旦触发，必须在首次执行该能力以前读取其真实入口和当前依赖；不得凭模型记忆执行
- 未触发 Skill 不加载；不得把所有 Skill 正文永久塞入上下文
- Writing、README、Design 和 Framework 各自只有一个规则权威；本文件不得复制其领域规则
- Writing Interface 尚未解析到正式规范时必须按其真实状态处理，不得自行绑定历史版本或模型记忆

## 1.8. 最终收口

1. 检查所有 `未开始`、`进行中`、`FAIL`、`BLOCKED`、`未执行` 的必需项；仍有 Agent 可以继续推进的工作时不得结束
2. 重新读取本文件、当前 TR 的 `CHECKLIST.md`、`TEST.md`、相关 REG、`01-context-state.md`、`02-execution-scope.md`、`03-verification-regression.md` 和本 Turn 其他实际触发的 Canonical Module
3. 根据重新读取的 Canonical Rule 复核当前 Checklist、TEST、候选、证据和最终报告；任何不一致先修复并重新验证
4. 按 R20 当前 Canonical Rule 生成最终用户报告并原样写入当前 `TURN.md`
5. 使用统一收口机制由同一报告更新 `CURRENT.md`；不得手工维护第二份事实
6. Framework 结构、索引、元数据、Skill 清单或可见性发生变化后，运行当前 Canonical Rule 要求的确定性检查和文件树生成
7. 向用户返回与 `TURN.md` 中最终用户报告相同的内容

最终报告、CHECKLIST、TEST、证据强度、持续执行、REG、Git、部署、Writing、README、Design、Materials、Runtime 和可见性的具体规则全部以本轮重新读取的唯一 Canonical Source 为准，本文件不维护第二份正文

## 1.9. 最终回读路由

最终收口时按 `1.8` 重新读取适用 Canonical Module；本区只保存模块定位，不复制 R01–R31 摘要

<!-- APCF-RULE-READBACK-START -->
- `01-context-state.md` → `R01, R02, R10, R17, R20, R24`
- `02-execution-scope.md` → `R04, R05, R12, R14`
- `03-verification-regression.md` → `R03, R06, R07, R13`
- `04-tools-parallel.md` → `R08, R09, R11, R18`
- `05-delivery-lifecycle.md` → `R15, R16`
- `06-framework-contract.md` → `R19, R21, R22, R23, R25, R26, R27, R28, R29, R30, R31`
<!-- APCF-RULE-READBACK-END -->

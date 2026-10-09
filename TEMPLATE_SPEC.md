<!-- APCF-META {"schema":1,"visibility":"public"} -->
# 1. 通用模板规格

## 1.1. 目的

APCF 为 Codex 提供项目级规则路由、执行范围、验收记录与交付收口框架

它向新项目增加控制壳，不规定业务目标、源码树、技术栈或设计采用事实

## 1.2. 分发内容

- 根入口 `AGENTS.md`、初始 `CURRENT.md`、本地部署说明和双语 README
- R01–R31 规则正文及其路由索引、框架配置和规则同步脚本
- Writing v0.1、Style v0.1、共享 Design v0.1 与对应接口、锁和校验工具
- 可选 `tool-workbench-2.3.1` Profile；默认 `auto_adopt: false`
- Skill 来源锁、技能同步脚本、路由与 Receipt、Audit、Gate、Finalization 及其他公开框架脚本
- 空的 IT/TR、REG、ADR、RB、MAT 和 runtime 目录标记及索引
- 标为公开的根文档与有限合成示例 `examples/`

文本、目录和二进制文件通过 APCF 可见性元数据分类；生成候选还要检查内容，`public` 标签本身不是无秘密证明

## 1.3. 项目事实占位

- `.agent-project-control/PROJECT.md` 保持项目目标、用户与边界的空白输入位置
- `.agent-project-control/ARCHITECTURE.md` 保持架构事实与来源的空白输入位置
- `.agent-project-control/DESIGN.md` 保持 `UNRESOLVED` 状态，Profile 也不自动采用
- `CURRENT.md` 仅描述新副本尚未开始执行轮次

新项目应由 Agent 根据源码、配置、测试和正式文档调查后填写项目事实；不以模板占位内容推断业务、架构或视觉设计

## 1.4. 不随干净分发携带的对象

- 源仓 `.git` 与开发历史
- 实际 IT、TR、REG、ADR、RB、MAT 实例和来源执行证据
- runtime 运行输出、测试副本、缓存、下载和个人机器状态
- `.codex/skills/` 的安装缓存与其 `.git`
- 对某个开发源仓、账号或远端目标的专用授权

required Skill 通过公开锁声明真实来源、提交与摘要；所需来源权限由使用者环境提供

可选发布 Skill 使用本地固定摘要，干净分发允许其缓存缺失，并在明确路由时拒绝假装已安装

## 1.5. 安装与候选边界

`bootstrap.py` 在任何目标写入前拒绝已含 `AGENTS.md`、`CURRENT.md`、`.agent-project-control/` 或 `.aialra/` 的目录；空目录和没有这些冲突标记的既有项目可接收控制壳，已有业务文件保持不变

安装不会把源历史带入目标；目标框架元数据将 `template_source` 设为 `false`，并将状态重置为 `uninitialized`，源框架配置保持不变

`repository_visibility` 的保守默认策略与真实下游仓库状态分开处理，详见 [部署合同](CODEX_DEPLOY.md)

`prepare_distribution.py` 只生成一个新的隔离候选并输出路径；不合并旧目录、不清理源树、不生成 ZIP、不设置 Git 远端或发布

可选私有 manifest 写在候选之外，公开发布清单由最终发行流程单独基于实际文件摘要生成

## 1.6. 唯一事实来源

- 执行入口和强制读取：`AGENTS.md`
- 项目目标、架构和采用状态：`.agent-project-control/PROJECT.md`、`ARCHITECTURE.md`、`DESIGN.md`
- 规则正文、写作标准、Style 与 Design：对应唯一 Canonical Module、标准文件与 Design 规则文件
- Skill 来源和版本：`.agent-project-control/skills/SKILLS.lock.yaml`
- 当前状态和最近完整报告：`CURRENT.md`
- 实际执行过程与验收：当前 IT/TR 的 `CHECKLIST.md`、`TEST.md`、`TURN.md` 和 `evidence/`
- 长期失败、决策、手册和用户资料：各自的 REG、ADR、RB、MAT 目录
- 智能体临时数据：`.agent-project-control/runtime/`
- 可派生文件树：`.agent-project-control/generated/`，由脚本生成

<!-- APCF-META {"schema":1,"visibility":"public"} -->
# 1. 干净副本 Pilot 测试计划

本计划用于在独立副本中确认模板安装、核心执行路径、分发边界与证据链

Pilot 结果只覆盖实际测试的目标、环境和用例，不证明其他业务功能或部署环境已经验收

## 1.1. 前置条件

- Python 3.11 或更新版本
- Git 可用；合成示例会在独立测试项目中初始化本地仓库并创建一条合成提交
- 使用新建的工作副本或干净分发候选，不在开发源树中压缩或清理历史
- 测试目标放在当前副本的 `.agent-project-control/runtime/testbed/` 下

## 1.2. 安装边界

1. 在新空目录运行 `bootstrap.py`，确认规范、脚本、Skill 锁、初始状态、`template_source: false`、`status: "uninitialized"` 和空运行区存在，并确认源框架状态不变
2. 在隔离的非空项目副本运行安装，记录原源码和配置摘要，再确认安装后原文件摘要相同
3. 分别准备含 `AGENTS.md`、`CURRENT.md`、`.agent-project-control/` 和 `.aialra/` 的目标，确认每种冲突都在写入前拒绝且原字节未变
4. 用一次性测试副本模拟阶段构建失败，确认目标不存在或仍为空，且源仓文件摘要未变

## 1.3. 合成工作流

从副本根目录运行两个全新目标：

```powershell
python -B examples/run_demo.py --project .agent-project-control/runtime/testbed/pilot-success --scenario success
python -B examples/run_demo.py --project .agent-project-control/runtime/testbed/pilot-repair --scenario repair
```

确认成功用例执行两条真实断言并完成 Audit、完整 Gate、Finalize 和状态一致性检查

修复用例还应保留首次失败、证明失败时目标未变化、只修复可编辑正文、验证代码块原文保持不变

每个路径应为新目录或空目录

脚本不删除目标，也不推送或更改源 Git 历史；重复测试时选择新名称

## 1.4. 规则、Skills 与验收记录

- 运行 `rule_sync.py`、`standards_contract.py --check` 与 `design_contract.py --check`，确认规则索引、Writing/Style 接口和 Design 锁一致
- 运行 `sync_skills.py --check`，核对必需 Skill 的可用性、提交和摘要；可选缓存完全缺失时允许出现 `OPTIONAL_UNAVAILABLE`，但既有漂移仍应失败
- 对实际 TR 检查计划与目标、TEST ID、Gate 当前候选摘要、语义复核和内容复核是否对应
- 确认 Action Gate 前由当前 TR 对精确目标路径建立 Receipt；不能用无目标或其他目标的路由记录替代
- 确认 `PASS` 来自真实命令和当前对象观察，不是手工写入的结论

若 required Skill 因读取权限不可用，保留阻断结果并先恢复合法访问；不得降低必需状态或改写锁摘要绕过

## 1.5. 分发与脱敏边界

1. 使用 `prepare_distribution.py` 生成一个新的隔离候选，确认输出不含 `.git`、源 IT/TR/MAT、runtime 证据、Skill 缓存或开发机专用授权
2. 确认规范、锁、脚本、空项目事实占位和公开 `examples/` 均保留，且新候选中的目录树已重新生成
3. 对根文档、合成示例、配置、脚本、最终归档成员和实际暂存文件扫描个人绝对路径、账号、邮箱、凭据与带凭据连接串
4. 复查正常相对路径、合法规范名称、锁摘要与 `<OWNER>/<REPO>` 占位符没有被误删或改写

模式检索结果需要人工复核；正则未命中不能单独证明安全

对不确定身份或秘密按 `REVIEW_REQUIRED` 记录，不在源仓修改历史来制造干净候选

## 1.6. Pilot 完成条件

只有在目标范围的主要正常路径、冲突拒绝、修复路径、实际验收证据、文件保留和脱敏复扫都有对应观察记录时，才能报告该范围的 Pilot 结果

未执行的环境、平台渲染或用户真实业务路径保持未验证；Pilot 通过不代表可以自动发布

<!-- APCF-META {"schema":1,"visibility":"public"} -->
# APCF 首次接入与恢复执行合同

**适用范围**：Agent 为一个既有或空白项目首次采用 APCF Core v0.3.0 Closeout v2，或接管未完成的接入。**执行原则**：真实项目优先、共享规则只读加载、先检查后写入、持续执行并以证据判定完成。该合同是使用路径，不是 Canonical Rule、Writing、Style 或 Design 的第二份正文。

## 1. 启动与目标解析

1. 从当前 Agent 实际工作目录出发，读取 `pwd`、`git rev-parse --show-toplevel` 或项目原生工作区标识，确定**真实目标根目录**。如果存在多项目或 monorepo，明确工作区根和子项目边界；不要误把 APCF 下载或发布工具所在目录当作目标项目。无法唯一识别时，提出**一个精确问题**，不猜测。
2. 先只读检查目标：现有 `AGENTS.md`、其他 Agent 入口、`.agent-project-control`、`.codex`、配置、CI、Git HEAD、index、dirty/untracked、构建产物、文档和用户数据。记录本轮起点及保护对象 SHA；检查是否已有 APCF，避免重复安装。
3. 读取当前下载 Core 中的 `AGENTS.md`、`.agent-project-control/framework.yaml`、`rules/INDEX.md`、完整 R01–R31 的路由文件、Writing/Style Interface、Design Index、Skills Lock、Gate 入口。严格由当前磁盘决定生效版本，**不得用旧 GitHub 源码覆盖本地已验证 Core**。

## 2. 先划清归属再接入

| 层面 | 唯一责任来源 | 适配方式 |
|---|---|---|
| 业务功能、已有测试、构建/部署和产品源数据 | 原项目已有源码与权威文件 | 原位保留；不因模板而迁移或重写 |
| APCF R01–R31、规则路由、IT/TR/CL/TEST、门禁与收口 | Core 对应 Canonical/脚本 | 新增控制壳；不得并列维护第二份规则 |
| 真实项目目标、架构、采用与例外 | 项目事实与 `PROJECT.md`、`ARCHITECTURE.md`、`DESIGN.md` | 基于真实调查逐项填写；未知就写未知 |
| Writing / Style / Design / Skills | 当前 Core 接口与锁，已认可的项目原生设计权威 | 只解析当前适用规则与触发的 Skill；默认不替换网站视觉实现 |
| 可选 Atlas 或 Design Profile | 项目明确采用的组件/用户授权 | 默认 `UNRESOLVED`；不自动安装或套用 |

禁止覆盖已有 `AGENTS.md`、重置 Git、覆盖未提交修改、强改 CI、移动源码、清空历史或采集无关秘密。不能无损解决入口冲突、需要外部凭证或不可逆动作时，应先保护现状并只询问必要决策。

## 3. 安全安装与项目初始化

1. 核实**下载的正式 Release ZIP、SHA-256 与实际安装命令**，严格执行包中 `bootstrap.py --help` 和当前安装合同；旧版样例命令不能代替现场参数。只在目标确实没有受管 APCF 冲突时安装。
2. 安装后复查保护对象内容 SHA、原 Git 提交和暂存条目。`AGENTS.md` 必须成为最小且可读的路由入口；原项目已有多 Agent 规则时，应兼容整合或暂停冲突范围，不能强行留下互相矛盾的指令。
3. 真实创建或更新项目 `PROJECT.md`、`ARCHITECTURE.md`、`DESIGN.md` 的**项目事实层**：目标、用户、边界、技术栈、源目录、构建/测试/部署入口、风险、事实来源和未知事项。无需相关领域时保持极简，不造事实填模板。
4. 初始化当前 Writing、Style、Design、材料/资源索引和 Skills Lock 路由；读取与本次工作有关的真正权威，验证可解析性和触发路径。Skill 按需加载，不自动安装全部缓存或永久复制正文。 完整 Full Pilot 会在隔离夹具中验证 README 与发布能力；执行这项完整回归前，需要准备 Skills Lock 指定的 README 完整仓库和同 SHA 的 pinned-local 发布 Skill 快照，实际运行 `sync_skills.py --check`。这些测试依赖只进入私有缓存，不进入发行 ZIP，也不授予真实发布权限；缺失或版本不符时保留阻塞证据，不假装依赖已安装。若既有同类系统成熟，保留原权威并建立映射。
5. 首次 IT/TR 之前，实际运行 `git rev-parse --show-toplevel` 与 `git rev-parse --verify HEAD`：当前基线的执行记录和 Gate 依赖有效 Git 仓库及已有提交。已有 Git 必须保留原分支、HEAD、index 和历史；无 Git 或尚无首提交时，先检查当前请求是否已明确授权初始化与首提交，已授权才执行必要操作，缺少该授权才询问一次；否则记录 `PILOT_BLOCKED`，不创建半初始化 TR，也不得声称无 Git 生命周期已可用。安装成功本身不代表这项前置条件已满足。
6. 按真实当前 IT 状态和 Canonical 规则启动本项目自己的首次 IT、TR；逐字写 `REQUEST.md`，建立独立 CHECKLIST、TEST、证据目录和必要路由 Receipt。导入模板时**绝不复制模板开发仓 IT/TR/REG/MAT/RB 实例**。

## 4. 首次真实 Pilot

以“现有项目结构、执行入口、规范加载和首次受控生命周期”为首轮 Objective。优先选用不改业务逻辑、能直接观察的实际项目检查，而非制造虚假的业务成果。必须完成：

- 检查项目文件和 Git 原状，核对保护差异；没有业务改动时明确写为“未改变”。
- 路由当前规范，确认 Canonical Rules、Writing、Style、Design、Skills 的单一权威和适用状态；只触发本任务需要的能力。
- 执行可用的项目原生构建/测试及 APCF lint、rule/design/standards 检查、selfcheck、Pilot Full、Gate 和 Finalize；按当前规则处理顺序、环境和依赖。
- 至少一次正向与与风险相称的负向/重复操作验证。每条 TEST 必须给出真实版本、环境、操作、预期、实际、证据；缺证据不得 PASS。
- 检查旧文件不被覆盖、重复执行不创建冲突条目、失败恢复可追溯、当前 TURN/CURRENT 同源，显示 `PASS/FAIL/BLOCKED/未执行` 的真实范围。
- **不得把 localhost 页面、综合演示或单条脚本退出 0 当作生产站点验收**；生产部署、真实云、外部账号、长时压力未执行就明确标注。

## 5. 收口和重读机制

按当前 R20 / 报告合同生成完整首轮用户报告，并原样写入当前 TURN，经正式 Finalize 确定性更新 CURRENT；如未满足 Gate 则保留未完成状态与证据，不伪造成功。报告至少交代：目标根、所用发行 SHA、保护对象、项目调查结果、安装差异、规范/Skill 初始化、IT/TR、验收退出码、阻塞、回滚与下一步。

**如果 Agent 更换、窗口重启或“忘记框架”**：停止猜测，重新读取目标 `AGENTS.md`、`CURRENT.md`、本 `APCF_ONBOARDING.md`、当前 CL/TEST 和本阶段真正命中的 Canonical Modules；恢复项目当前事实与已完成证据，只继续未闭环的下一项。不复制上一个 TR 的完成状态，也不重复不确定的非幂等写入。

## 6. 完成状态

只有经当前 Core 完整验收且原项目保护检查通过时，报告 `PILOT_PASSED`（这是面向用户的分类，并非擅自引入新 schema）。部分通过应报告 `INSTALLED` / `PILOT_IN_PROGRESS` / `PILOT_BLOCKED` / `PILOT_FAILED` 的实际状态；不可用名义成功替代真实证据。**默认不 Commit、Push、Release、改网站 UI、删除历史或上传数据**；只有用户另行明确指定的权限与发布范围才能执行这些动作。

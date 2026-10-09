<!-- APCF-META {"schema":1,"visibility":"public"} -->
# 1. Tool Workbench 2.3.1 Profile

- **Profile ID**：`tool-workbench-2.3.1`
- **来源包**：`AIALRA-Workbench-Template-v2.3.1`
- **设计规范版本**：`2.3.1`
- **界面基线版本**：`2.3.0`
- **自动采用**：`false`
- **适用定位**：中性、规整、内容优先的工具型网站参考 Profile。它提供已认可样板的参数和参考实现，但不是所有项目的默认设计事实，也不是行业统一硬门槛。

项目只有在 `.agent-project-control/DESIGN.md` 明确记录 `ADOPTED` 或 `PARTIAL` 后，才把本 Profile 的适用部分作为该项目当前设计基线。`UNRESOLVED` 表示尚未判断，`NOT_APPLICABLE` 表示已确认不适用。

## 4. 已认可模板的参数与使用边界

- <a id="param-238"></a>这里是已采用 v2.3 的当前实现参数，不是 Apple、微软或其他标准的统一硬门槛；移植到新项目时保留适用默认或记录有依据的差异。
- <a id="param-239"></a>新页面先采用配置文件；已有认可项目优先保留其参数；不要每个组件自行在范围里随机选数值。
- <a id="param-240"></a>默认面板间距 16px、圆角 8px；常规控件 36px、紧凑工具角色 32px，舒适树行 36px、紧凑树行 32px；面板标题栏 48px，底栏 40px；左右栏偏好起点 256／272px。桌面主内容可用宽度起点 360px，由布局预算保护，窄屏切为抽屉；这些是样板参数，不是通用标准门槛。
- <a id="param-241"></a>默认深色背景为中性灰；浅色模式仍使用中性色。状态角色可带语义色。
- <a id="param-242"></a>菜单与选择列表行默认 36px，子菜单间隔 4px；画布节点 152×64px、候选净距 12px；光学与交互几何按当前角色定义，详见参数文件。节点整理是本演示的分层排布，不承诺任意大图的最优布局或自动消除所有连线交叉。
- <a id="param-243"></a>图标网格 24×24，默认线宽 1.6；常见显示尺寸 16／18px，由组件角色决定，不混用 emoji。
- <a id="param-244"></a>UI 正文起点 14px，阅读正文 16px，标题 28px；中文使用系统无衬线回退。不同视口的具体规则见 CSS。
- <a id="param-245"></a>常用入口参数：活动栏宽64px、导航按钮44px、按钮间净距12px；顶栏高60px；全局搜索高40px、横向内边距16px、图标／文字等内部间隔12px；局部文件筛选高40px。小屏和触控另有角色映射，取值以tokens与CSS媒体规则为准，不能反推成行业统一值。
- <a id="param-246"></a>参数编辑入口：工作台设置（外观／布局／工作区）；配置导出：命令面板或工作区菜单 → HTML／JSON／Agent 说明。
- <a id="param-247"></a>内容位置、图形视口与属性栏未提交文字只作为当前运行中的交互状态；工作区 JSON 导出不宣称包含所有临时视口或未提交字段。
- <a id="param-248"></a>内容不作为个人审美依据，正文全部为占位；组件参照从活动栏进入，不堆在默认文档里。
- <a id="param-249"></a>配置和内容保存在浏览器允许的本机存储；受限预览环境使用会话模式，关闭前导出 JSON。这个说明不等于已验证用户浏览器的持久性。
### 精确参数映射（从 tokens.json 派生）

<!-- DESIGN-PARAMETERS:START -->
| 参数路径 | 当前值 | 单位／含义 |
|---|---:|---|
| `spacing.1` | `4` | CSS px |
| `spacing.2` | `8` | CSS px |
| `spacing.3` | `12` | CSS px |
| `spacing.4` | `16` | CSS px |
| `spacing.5` | `24` | CSS px |
| `spacing.6` | `32` | CSS px |
| `spacing.7` | `48` | CSS px |
| `typography.ui` | `14` | CSS px |
| `typography.small` | `12` | CSS px |
| `typography.section` | `16` | CSS px |
| `typography.title` | `28` | CSS px |
| `typography.body` | `16` | CSS px |
| `typography.bodyLine` | `1.75` | 倍行高 |
| `typography.caption` | `11` | CSS px |
| `typography.tree` | `13` | CSS px |
| `typography.mobileBody` | `15` | CSS px |
| `typography.mobileTitle` | `24` | CSS px |
| `geometry.gap` | `16` | CSS px |
| `geometry.radius` | `8` | CSS px |
| `geometry.control` | `36` | CSS px |
| `geometry.treeRow` | `36` | CSS px |
| `geometry.touch` | `44` | CSS px |
| `geometry.header` | `48` | CSS px |
| `geometry.leftWidth` | `256` | CSS px |
| `geometry.rightWidth` | `272` | CSS px |
| `geometry.rail` | `64` | CSS px |
| `geometry.mainMin` | `360` | CSS px |
| `geometry.compactControl` | `32` | CSS px |
| `geometry.menuRow` | `36` | CSS px |
| `geometry.graphNodeWidth` | `152` | CSS px |
| `geometry.graphNodeHeight` | `64` | CSS px |
| `geometry.graphClearance` | `12` | CSS px |
| `geometry.motionFast` | `120` | ms；保留原参数，不代表按钮颜色仍使用过渡 |
| `geometry.compactTreeRow` | `32` | CSS px |
| `geometry.footerHeight` | `40` | CSS px |
| `geometry.railControl` | `44` | CSS px |
| `geometry.railGap` | `12` | CSS px |
| `geometry.topbarHeight` | `60` | CSS px |
| `geometry.searchHeight` | `40` | CSS px |
| `geometry.searchInline` | `16` | CSS px |
| `geometry.searchGap` | `12` | CSS px |
| `geometry.topControlGap` | `8` | CSS px |
| `performance.draftSaveDelayMs` | `240` | ms |
| `performance.draftSaveMaxWaitMs` | `1200` | ms |
| `performance.measurements` | `local-laboratory-not-field-INP` | 测量边界标记 |
| `performance.viewSaveDelayMs` | `180` | ms |

颜色角色分别读取 tokens.json 的 dark／light；此表不复制色板。构建时 status 不覆盖 TEMPLATE.json 中的当前采用事实。
<!-- DESIGN-PARAMETERS:END -->

<a id="runtime-boundary"></a>
## 5. 响应与稳定性的实施边界

- <a id="perf-267"></a>**即时反馈**：输入内容立即保存在运行内存，字段、脏标记与当前页不等待持久化；控件动作无假进度。共享按钮的hover／pressed／current与主题颜色无120ms过渡，移除的是会延后状态可见性的装饰，不是把业务成功提前伪造。
- <a id="perf-268"></a>**视图快照**：切文件、普通选中及部分布局状态先更新界面，默认180ms合并快照；不会把点击操作本身推迟180ms。队列保存的是执行时最新状态。
- <a id="perf-269"></a>**草稿持久化**：默认停顿 240ms 合并写入，持续输入最长等待 1200ms；两个值是本样板实现参数，不是用户永久偏好或行业硬门槛。同步 localStorage 仍存在，小型演示未改为 IndexedDB。
- <a id="perf-270"></a>**强制提交**：显式保存、导出与 pagehide／visibilitychange 相关路径处理待写内容。关闭进程、断电等无法保证最后尚未提交的草稿持久化；记录“正在保存”与错误，不伪造保证。
- <a id="perf-271"></a>**故障处理**：配额或写入失败保留会话内容；重试成功前不显示本机成功。其他窗口的存储变化取消本窗口排队写入并锁定，用户可导出副本，不自动覆盖远端变更。
- <a id="perf-272"></a>**异步一致性**：新导入请求替代旧请求时，迟到的读取结果不得再弹出旧确认或覆盖新状态；模态关闭后旧表单提交不得二次执行。
- <a id="perf-273"></a>**空间与性能共同检查**：增加间距不能把中心区压没；视图切换、筛选和拖动不通过缩字、遮挡或丢状态换取速度。
- <a id="perf-274"></a>**不声称**：现场 INP 达标、所有设备无卡顿、长时间零泄漏、完整可访问性认证、真实操作系统文件持久化。有限负载通过不代表无限规模可用；继承的演示导入范围没有为测试改松。
<a id="project-adoption"></a>

## 6. APCF 项目采用合同

- 目标项目首先读取自身 `.agent-project-control/DESIGN.md`，再通过 `design/INDEX.md` 路由到相关 D 规则；只有需要比较或已经采用本 Profile 时才读取这里的精确参数和参考实现。
- 新项目默认 `UNRESOLVED`，不得因为 APCF 携带本 Profile 就自动把 16px、8px、36px、256px 等样板值变成项目要求。
- 项目采用时只在自身 `DESIGN.md` 记录 Profile ID、采用状态、真实差异、项目现有设计来源、认可参考与明确例外；D01–D16 和 Profile 参数正文保持共享单一来源。
- 项目已有正式 Design System、Design Tokens、组件库、Storybook 或等价文档时，优先把这些现有对象登记为项目实现与参数事实来源；APCF 不复制第二份实现真相。
- 已认可的现有页面和与本次任务无关区域默认保持不变；引入共享基线不等于全站重做，也不等于强制更换技术栈。
- `tokens.json` 是本 Profile 的精确参数来源；`reference-template.zip` 只是只读参考实现，不是目标项目的源码权威。

<!-- APCF-META {"schema":1,"visibility":"public"} -->
# 1. 共享设计基线路由

本文件只负责路由，不保存第二份 D 规则正文；完整规则只在 `RULES.md`，精确样板参数只在 Profile，项目采用事实只在项目 `DESIGN.md`

## 1.1. 读取顺序

1. 先读项目 `.agent-project-control/DESIGN.md`，确认现有设计事实和采用状态
2. 再读本索引，按当前任务选择实际命中的分类和 D 编号
3. 目标明确时可用 `--rule` / `--category` 只读相关 D 规则；在 APCF 自动 Design 事前路由中，先保守读取完整 `RULES.md` 避免漏项，实际适用性由每条规则的触发条件决定
4. 项目实现事实继续读取项目原生源码、tokens、组件库、Storybook 或设计资产；完整规则读取不等于项目自动采用任何 Profile

## 1.2. 分类路由

- **结构与视觉层级**（`structure-visual`）：`D01`、`D02`、`D03`、`D04`、`D05`、`D06`
- **交互、焦点与恢复**（`interaction-recovery`）：`D07`、`D08`、`D09`、`D10`、`D11`
- **内容模型与响应适配**（`content-responsive`）：`D12`、`D13`
- **实现复用与性能**（`implementation-performance`）：`D14`
- **验证与设计演进**（`verification-evolution`）：`D15`、`D16`

## 1.3. D 规则索引

- **D01**. 按主任务组织空间，不把工作台做成说明海报
- **D02**. 用中性色建立结构，语义色只承担必要含义
- **D03**. 区分内部间距、组间距与独立区域间距
- **D04**. 同角色对齐，同角色同规格
- **D05**. 文字按语义分层，不靠小字挤满界面
- **D06**. 图标、标签与辅助提示共同表达操作
- **D07**. 右键菜单围绕选中对象，并提供等价入口
- **D08**. 文件树动作必须改变数据，删除必须有恢复语义
- **D09**. 双侧栏可调整、可迁移、可找回
- **D10**. 反馈必须真实，输入和恢复路径必须保留
- **D11**. 菜单、提示、对话框遵守同一焦点与层级合同
- **D12**. 文档、列表、画布共享外壳，不共享不相干的数据
- **D13**. 适配窗口和输入方式，不靠缩字或裁切掩盖问题
- **D14**. 先复用共享实现，再修最小共同根因
- **D15**. 用匹配的实际检查证明，不用总分遮盖失败
- **D16**. 把反馈沉淀为可追踪设计变化，不堆第二套规范

## 1.4. 当前共享 Design 规范版本

- **正式版本**：`v0.1`；唯一规范正文为 `RULES.md` 中的 D01–D16

## 1.5. 可选 Profile

- **tool-workbench-2.3.1**：中性、规整、内容优先的工具型网站样板；`auto_adopt: false`；只有项目 `DESIGN.md` 明确记录采用后，精确参数才成为项目设计事实

## 1.6. 采用状态

项目 `DESIGN.md` 使用 `UNRESOLVED / ADOPTED / PARTIAL / NOT_APPLICABLE`；模板携带共享基线不等于项目自动采用任何 Profile

## 1.7. 定向读取

```powershell
python -B .agent-project-control/scripts/design_contract.py --rule D07
python -B .agent-project-control/scripts/design_contract.py --category interaction-recovery
```


## 1.8. 已注册可选组件

当前候选没有已注册的可选 UI 组件。

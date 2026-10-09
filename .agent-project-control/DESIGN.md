<!-- APCF-META {"schema":1,"visibility":"public"} -->
# 1. 项目设计知识

本文件只保存当前项目的设计采用事实、现有权威来源、共享基线适用性、Profile 采用状态、项目差异与明确例外。共享 D01–D16 正文位于 `design/RULES.md`，精确样板参数位于相应 Profile；这里不得复制第二份共享规则或参数表。

## 1.1. 当前采用状态

- **共享设计基线**：`.agent-project-control/design/INDEX.md`
- **采用状态**：`UNRESOLVED`
- **当前 Profile**：`none`
- **Profile 状态**：`UNRESOLVED`
- **最近核对**：尚未在真实项目中核对

允许的采用状态为 `UNRESOLVED / ADOPTED / PARTIAL / NOT_APPLICABLE`。新项目默认 `UNRESOLVED`，不得因为模板携带共享规则或 Profile 自动变成 `ADOPTED`。

## 1.2. 项目现有设计事实来源

当前尚未调查真实项目。接入后记录现有 Design System、token 文件、组件库、Storybook、Figma/设计资产、正式设计文档、既有已认可页面或其他权威来源；已有等价事实优先引用，不复制第二份。

## 1.3. 当前适用 D 规则

当前尚未判断。执行 UI/UX 任务时根据真实对象从 `design/INDEX.md` 路由，只加载命中的 D 规则及依赖；不因存在 D01–D16 就假定每条都适用。

## 1.4. Profile 采用与参数映射

当前没有自动采用任何 Profile。若选择 `tool-workbench-2.3.1` 或未来 Profile，记录采用状态、适用页面／条件、项目现有参数来源和真实差异；精确值仍引用 Profile 或项目原生 token 源。

## 1.5. 项目差异与明确例外

当前无已确认差异。接入后每条差异至少记录：相关 D 编号、适用对象／条件、当前项目行为或参数、依据、验证方式。没有证据的差异保持未知，不自行创造。

## 1.6. 实现来源映射

当前尚未调查。实现真相继续位于目标项目原生源码、组件、样式、token、测试与设计资产中；APCF 只建立必要映射，不把实现复制进控制壳。

## 1.7. 验证边界

当前尚未在真实项目中执行设计验收。后续当前 Turn 的设计验证进入 `CHECKLIST.md`、`TEST.md` 与 evidence；长期复发问题进入 REG，不把过程历史堆回本文件。

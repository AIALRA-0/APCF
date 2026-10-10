<!-- APCF-META {"schema":1,"visibility":"public"} -->
# 1. 设计规范与实际参考入口

共享设计正文、精确历史 Profile、当前交互演示是三个不同对象，不以文件名或“最新”替代内容身份

## 1.1. 当前共享规范

D01–D16 的唯一正文仍为 `RULES.md`，版本与来源使用 `BASELINES.lock.yaml`；项目采用状态由项目自己的 `DESIGN.md` 决定，默认 `UNRESOLVED`，不得自动换肤

## 1.2. 当前可直接查看的演示

上一版 Core Repair r1 交付资料使用 `optional-design/index.html`；本阶段 v0.3.1 的独立预览位于公开仓库的 [examples/design-atlas/index.html](https://github.com/AIALRA-0/APCF/blob/main/examples/design-atlas/index.html)，最小 Core 不包含这份应用，不要求用户先打开内层 ZIP 才能查看公开预览源码

- 原始 HTML SHA-256：`ef8e7cab2346dfb9d9f6107560223466bdebe3f05552f02cf57cd759968ef39d`
- 身份：交互参考，不是所有项目自动采用的 UI 实现
- 在最小 Core 中的状态：`COMPANION_AVAILABLE / NOT_INSTALLED`，不会伪造不存在的本地安装路径
- 可选参考的源码和附加合同应按实际采用版本核对来源、完整正文与摘要；最小 Core 不默认安装该附加合同，也不继承上一轮的通过结论
- 发布仓库应把 HTML 和其源码放在可直接浏览的位置，并把源路径、版本、SHA 和采用条件一起登记；实际 Public URL 需发布后回读，不能提前声称可下载

## 1.3. 历史参考

`profiles/tool-workbench-2.3.1/reference-template.zip` 是既有锁绑定的 历史参考配置（Legacy Profile），不是 v0.5-r3；它保存完整参考源码与构建文件，压缩本身不是遵守设计要求的证明

本补丁保留原归档字节与旧锁，不静默把旧版本改名成最新演示；在独立的 Profile 版本升级中才调整归档、构建换行策略、token 锁和验证器

## 1.4. 采用边界

先确定当前项目已有设计系统及本轮问题，再选择必要共享规则或案例；可见示例不等于必须采用，案例互动通过也不等于真实项目的可访问性、性能和全部状态已验收

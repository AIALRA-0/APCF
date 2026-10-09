<!-- APCF-META {"schema":1,"visibility":"public"} -->
# 1. 统一表达风格规范接口

## 1.1. 作用

本文件是正式 Style 的稳定入口，只保存版本、作用和与 Writing 的关系，不复制 S00–S14 正文

## 1.2. 当前解析状态

- **状态**：`RESOLVED`
- **正式入口**：`.agent-project-control/standards/human-readable-chinese-style-v0.1.md`
- **正式版本**：`v0.1`
- **协同入口**：`.agent-project-control/interfaces/WRITING_STANDARD.md`

## 1.3. 调用合同

1. 正式人类可读内容默认通过 `human-readable` 同时读取 Writing 和 Style，不允许只凭旧 Skill、历史上下文或模型记忆代替
2. Style 决定如何按读者的理解推进、控制信息密度、解释机制、表达确定性、保持作者声音等；具体触发、强度和例外以 Style 正文为准
3. Style 不能删除、弱化 Writing 的硬格式、事实保真、受保护材料和其他适用约束；遇到真实冲突先明确适用范围及例外
4. 生成结果按两套规范共同检查；代码或其他非人类可读产物不因 Style 接口存在而自动转换文风
5. 本文件不新增第二份风格规则，也不把 Style 转写成每个项目的重复提示词

<!-- APCF-META {"schema":1,"visibility":"public"} -->
# 1. 设计基线迁移来源与边界

## 1.1. 源包身份

- **源包**：`AIALRA-Workbench-Template-v2.3.1(1).zip`
- **源包 SHA-256**：`0b1d632246b4eac5aeb5a6935cfb5747d2ddf64625fa436ff4375014d792238f`
- **源 DESIGN.md SHA-256**：`4947b404317234b9631c7583544d887d8ced14f4c5510f3bea9a11f11d4e406f`
- **源 Workbench.html SHA-256**：`2b954905708f1666c3fa13c56d009be533219f7ce41b55cd34c22ead3b435f69`
- **源 src/tokens.json SHA-256**：`808f187ff65d76cada1157aec8eaac49fb880b26888e02e8625a6b9f312e7ea0`
- **源 TEMPLATE.json SHA-256**：`018970f3a930110a1f187ddb98d76e323099d4a122e0d5dc04341ef54209bd27`

## 1.2. 无损迁移与拆分

- D01–D16 规则迁入 `RULES.md`，保持 D 编号、义务／验证结构和设计意图，不按分类物理拆成多个权威文件。为适配共享基线职责，只有以下来源绑定被改写：D04-M11/D04-M17 移除固定 footer 数值；D09-E01 把“当前实现”改为参考模板边界；D13-M06/D13-M13 把 44px 固定候选移回 Profile；D15-S01 把“本轮”改为当前项目证据；D16-M09 改为 APCF 共享 RULES 与项目 DESIGN 的单一来源关系。
- 原 DESIGN.md 的已认可模板参数与响应／稳定性实施边界迁入 `profiles/tool-workbench-2.3.1/PROFILE.md`，避免把样板数值误当共享通用规则。
- 精确参数继续使用源 `src/tokens.json`，不把派生参数表变成第二个编辑入口。
- 清洁参考实现打包为 `reference-template.zip`；源 iterations、history、evidence 和旧执行记录不进入共享基线。
- S01–S08、S10–S20 作为可复用外部方法来源迁入 `SOURCES.md`。S09 的原始私有指向不复制，而转化为“当前项目证据层”通用语义；S21 属于该源包的一次采用事实，S22 属于旧 APCF v0.2.2 快照，因此不提升为共享长期来源。
- 原第 9 节包含旧 APCF Attempt 历史模型，已按当前 APCF v0.2.3 一行式 TEST 语义改写到 `VERIFICATION.md`，不原样继承过时执行模型。

## 1.3. 架构取舍

共享设计语言、精确 token/Profile、项目自身实现和项目差异必须分层维护。共享规则回答“什么行为与体验原则适用”，Profile 回答“这套已认可样板有哪些具体参数和参考实现”，项目 `DESIGN.md` 只回答“这个项目采用了什么、有哪些差异和例外”，原生源码／组件库继续回答“实际实现是什么”。

这种分层避免两个相反问题：一是把所有项目强行套成 Workbench v2.3.1；二是把 D01–D16、参数表和组件实现复制进每个项目后逐渐漂移。

## 1.4. 本次集成的参考包清理

补丁所称清洁参考包仍包含源请求路径、旧轮次采用字段、界面历史标签和旧截图，本次只清理安装产物，MAT 原件与原始派生 payload 保持不变

- 删除 TEMPLATE.json 中源请求、时间、框架快照与旧轮次字段，改为只读参考描述，自动采用仍为 false
- 移除源代码注释和界面中的旧 IT 标识，从原生 build.py 重新生成单文件界面与构建摘要
- 移除两张带旧轮次标记的历史截图，保留十个可重建参考文件；截图不承担当前版本运行证据
- 规则正文和 src/tokens.json 原始字节未改，参数文件中的 status 仅为源构建标签，不是当前项目采用状态
- 原参考归档 SHA-256：`c518908e9def4c072827cab513ef6ec81e78b55146fa2b39313bacd72cbf1d55`
- 清理后参考归档 SHA-256：`e709546efb2f2758f7bf1453055d9eb5a5239998d3dd764adb1a022c0a4c0c38`
- 清理后 HTML SHA-256：`f583ab8e1f7d2fbed335bef94c1f511270cdfe38346d244dcc3cf61b5caa9dac`

锁定规则与参数文本通过 design/.gitattributes 保持 LF，避免 Windows 自动换行转换使原字节摘要失配，真实 Git 检出验证已执行

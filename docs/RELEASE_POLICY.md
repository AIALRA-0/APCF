<!-- APCF-META {"schema":1,"visibility":"public"} -->
# 发布策略与安全边界

## 为什么不直接把旧 Private 仓库切换为 Public

原开发仓曾包含临时测试依赖、历史证据、运行日志与 Git 扩展记录。只删除当前文件**不会**删除 Git 历史中的对象。因此 Public `APCF` 使用由已验证 Core ZIP **正向复制、经过可见性和秘密审计、独立初始化 Git** 的仓库；旧开发源保持 Private 与可追溯，不执行强制推送或 Git 历史改写。

## Release 内容

- `APCF-Deploy-v0.3.0-closeout-v2.zip`：正式最小 Core 入口，包含规则、脚本、Writing/Style/Design/Skills 及 `APCF-START.md` 和持久可回读的 onboarding 文档。
- `APCF-Deploy-v0.3.0-closeout-v2.zip.sha256`：可校验摘要。
- `RELEASE-MANIFEST.json`：候选成员、原 Core 来源 SHA、构建身份与实际测试记录。清单只作为分发证据，不替代 Canonical Rule。

原始已验证 Core ZIP：SHA-256 为 `4d41a3dd8a5516498776cf2563de47730017bd2a4f3052e757d12fa9eb4f1dda`、119 文件、523748 字节；不能用旧 GitHub、重新打包的未知 ZIP 或不同 SHA 代替。

## 发布门禁

先完成本地受控 Core 候选、旁路的源仓审查、完整 lint/selfcheck/Pilot/隔离安装、代码/设计/文档审查、二次 ZIP 解压核验，再验证 GitHub 公共仓库和 Release 实际内容。脚本不得通过省略 FAIL、自动清历史、关闭扫描或用固定例外掩盖问题取得成功。

## License 注意

**Public 不等于自动获得开源许可。** 如果干净 Core 本身带有合法已认可的 License，发布仓库保留它；如果没有，不得自行声称“MIT / Apache / Open Source”，也不能替权利人选择许可证。用户可以公开发布供浏览，但许可方式须另行确认。

## v0.3.1 维护发行

本阶段基于当前 Template 源码构建 136 个核心文件的独立部署包；数据模式保持 0.3.0。当前资产名为 `APCF-Deploy-v0.3.1.zip`，同时提供同名 SHA-256 摘要和 `RELEASE-MANIFEST.json`；旧 v0.3.0 Release 与其来源说明保留。发布与验收的实际边界以该版本 Release 正文为准，不沿用旧版本的通过结论

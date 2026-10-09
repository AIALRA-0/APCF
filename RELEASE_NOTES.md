<!-- APCF-META {"schema":1,"visibility":"public"} -->
# APCF v0.3.0 · Closeout v2

本次正式公共发行从 Windows 上经过验证的 **APCF Core v0.3.0 Closeout v2** 建立一份干净的部署候选。版本的语义权威来自原 119 文件核心 ZIP，SHA-256 为 `4d41a3dd8a5516498776cf2563de47730017bd2a4f3052e757d12fa9eb4f1dda`；任何不同版本不得替代。

发行新增一个可被 Agent 长期重读的首次接入合同，以及中英 README、文件架构图和固定版本下载器；不改变 Canonical R01–R31、Writing、Style 或 D01–D16 的语义。实际修改的 Core 派生文件、最终成员数及 SHA 以此次附带的 `RELEASE-MANIFEST.json` 为准。

**使用边界**：默认不改现有业务源码、UI、Git 历史、真实部署或账号权限。Design Atlas 属于可选组件而非 Core 自动依赖。个人项目真实 Pilot、不同 OS 环境以及公网操作由后续项目单独验证。

**发布状态**：Release 在部署 Agent 完成安全扫描、GitHub 公开检查、远端 Release 下载和 ZIP 二次验收以前不得标记完成。

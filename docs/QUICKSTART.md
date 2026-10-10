<!-- APCF-META {"schema":1,"visibility":"public"} -->

# 五分钟了解 APCF 接入

APCF 是规则路由、独立迭代、验收与交付的控制壳；它不会自动改变已有网站的界面、重构业务代码或替换构建流程

## Windows 下载安装

仓库公开发布后，先从 GitHub 公开仓库根目录取得 `install-apcf.ps1`；可克隆仓库到当前目录下的 `APCF` 文件夹：

```powershell
# 克隆公开仓库以取得本地安装脚本
git clone https://github.com/AIALRA-0/APCF.git APCF
$Installer = ".\APCF\install-apcf.ps1"
```

如果不使用 Git，可在仓库页面选择 `Code > Download ZIP`，解压后将 `$Installer` 设为解压目录中的 `install-apcf.ps1` 完整路径；完成其中一种获取方式后，在 PowerShell 中设置目标项目路径并运行：

```powershell
# 设置目标项目路径并启动已取得的安装脚本
$Project = "D:\Projects\my-project"
pwsh -NoProfile -File $Installer -ProjectRoot $Project
```

安装器从 `AIALRA-0/APCF` 的固定 v0.3.1 Release tag 下载正式包及 SHA-256 校验文件，验证后调用 Core `bootstrap.py`；它不使用 `Invoke-Expression` 执行远端代码；不允许安装覆盖目标项目中已存在的 `AGENTS.md`；冲突需要先适配

## 接入 Agent 一句话

> 请将最新正式 APCF Core 安全接入我当前打开的项目，并按 `APCF-START.md` 及 `.agent-project-control/interfaces/APCF_ONBOARDING.md` 连续完成项目调查、初始化、完整 Pilot、验收与首轮报告；保留原有源码和 UI

上述示例只是触发入口；详细规则与交付结构应从**安装后真实文件**读取，而不是把本页当成第二份 Canonical 正文

## 查看真实文件架构

阅读 [ARCHITECTURE.md](ARCHITECTURE.md) 了解规则、规范、设计、技能及任务记录之间的职责

## 如果安装失败

不要手动复制源码覆盖冲突文件；保存原始错误、项目状态和压缩包 SHA，再核对最新 Core README、现有 `AGENTS.md`、Python 环境及当前目标根目录

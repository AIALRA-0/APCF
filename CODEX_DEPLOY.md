<!-- APCF-META {"schema":1,"visibility":"public"} -->
# 1. 项目部署与接入合同

本文说明如何从通用模板创建项目、向既有代码目录增加控制壳，以及生成干净分发候选

仓库所有者、远端目标和发布授权均由使用者自己的项目事实与当前用户授权决定

## 1.1. 创建项目副本

如果本仓库已启用 GitHub 模板功能，可使用 GitHub 的 **Use this template** 创建独立仓库；也可先克隆自己有权访问的模板来源

下例中的所有者和仓库名是占位符，运行前必须替换：

```powershell
$template = "https://github.com/<OWNER>/<REPO>.git"
git clone $template my-project
```

从干净候选或归档开始时，确认归档没有携带源仓 `.git`、开发 IT/TR、materials、runtime 或 Skill 缓存，再按自己的版本控制方式建立项目历史

模板不会替你选择远端、设置账号或推送内容

## 1.2. 安装控制壳

要在新项目目录或既有代码目录中安装 APCF，先从模板仓库根目录运行：

```powershell
python -B .agent-project-control/scripts/bootstrap.py ../my-project
```

目标父目录必须已经存在

新目标会创建完整控制壳；非空项目只增加 APCF 文件并保留原有源码和配置

若目标已经包含 `AGENTS.md`、`CURRENT.md`、`.agent-project-control/` 或 `.aialra/`，脚本会在任何目标写入前拒绝安装

不要为绕过拒绝而删除现有文件；检查现有控制框架并选择合适的接入方式

`bootstrap.py` 不把模板源 `.git`、迭代、执行轮次、材料、运行历史或 Skill 缓存复制到目标

它也不在源目录之外创建目标父目录

## 1.3. 生成干净候选

在模板源仓根目录运行：

```powershell
python -B .agent-project-control/scripts/prepare_distribution.py
```

脚本在 `.agent-project-control/runtime/distribution/` 下建立一个新候选，明确保留公开文档、规范、规则、Skill 锁、脚本和合成示例，重新生成文件树，并排除源历史、`.git`、缓存及私有对象

默认输出路径最后打印；可用 `--output PATH` 指定一个此前不存在且父目录已存在的目标

可选参数 `--manifest PATH` 会在候选目录以外写入私有文件相对路径、字节数和 SHA-256 清单

该清单用于本地审核，不应进入公开候选或归档；`prepare_distribution.py` 不生成 ZIP、不创建 Git 远端，也不发布

分发保留 `.agent-project-control/skills/SKILLS.lock.yaml` 和同步脚本，不复制 `.codex/skills` 下载缓存

required README Skill 的实际同步需要网络及对锁定来源的读取权限，并校验锁定提交和 Skill 文件摘要；可选的本地 `github-safe-publish` 快照未随包提供

可选缓存缺失时 `--check` 报告 `OPTIONAL_UNAVAILABLE`，但显式触发缺失能力时仍拒绝继续

## 1.4. Git 与远端授权

候选目录与远端发布是不同操作

安装后的 `framework.yaml` 将执行状态初始化为 `uninitialized`；`repository_visibility: "private"` 是保守的默认发布策略，不代表下游远端当前已经存在或已设为私有

接入项目时，应根据实际仓库状态和当前用户授权确定可见性；只有确认真实目标后才调整该策略并执行发布流程

只有当前用户明确授权具体远端动作时，才按适用的发布规范和工具执行；README、技能或本部署文件都不会授予推送、Release、拉取请求或仓库设置权限

公开前应针对实际待提交文件和归档完成两轮脱敏检查，覆盖绝对路径、账号与邮箱、凭据、带凭据连接串、归档成员和可达 Git 历史

无法判断的信息留作 `REVIEW_REQUIRED`；不得通过改写源历史或忽略不确定结果来制造发布通过结论

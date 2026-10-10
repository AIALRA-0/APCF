<!-- APCF-META {"schema":1,"visibility":"public"} -->
# 1. 执行监督入口

本接口协调现有请求、规则回执、计划、TEST、内容审查和收口程序，不增加另一套规则或 IT/TR 状态机；当前实现是可检查的协作入口，不是控制宿主全部工具的安全隔离层

## 1.1. 请求开始与恢复

先按现行合同创建或恢复 IT/TR，不随每条内部工具回调新建目标；目标未变时延续原 IT，目标变化与暂停、完成仍使用原生命周期机制

读取本轮 `evidence/execution-session.json` 的 `request_id`，不要重复创建身份；运行 `supervisor.py inspect` 读取真实项目、CURRENT 及其来源 TURN、AGENTS 和活动 IT；普通启动要求当前目录属于该项目，从父目录启动须显式指定 `--project`，不凭同名文件夹自动猜目标

检查成功只证明程序核对了文件及版本，不能证明模型已理解；随后通过 `supervisor.py load --phase scope` 把现行规范正文交给实际工具通道，主持方须确认未截断，不用一句“已读”替代来源正文

## 1.2. 事前计划与执行

先调查并按 R02 写清当前原因、承诺和判据，再使用原 `routing_activity.py plan` 保存实际计划；`supervisor.py authorize` 复用 r1 的事前业务基线和目标摘要；`supervisor.py write` 只处理该计划中的一个文件及其前像，外部修改或范围变化要求重新调查，不能强行写入

该入口不替代宿主权限；普通终端、其他编辑器和未经过入口的工具仍可改文件，不能声称它们被拦截；计划调查中的只读操作不要求反复重新开轮次或运行完整 Core 自检

## 1.3. 结果与正文

验收前用 `load --phase verification` 读取对应规范，然后用 `check` 调用原 TEST 证据写入机制；依任务风险运行适用测试，不让每次普通文案修改都跑一次全量框架回归

准备交付前用 `load --phase writing` 重新输出 Writing／Style 的正式来源；按照这些来源审核用户实际可见的全文，保留作者自评与独立审核的真实区别，不把规范摘要、词条数量或检查器退出码当成语义正确证明

`prepare` 复用原报告合同并生成本轮唯一待发送正文；`finalize` 调用唯一正式 Gate/Finalize，核对真实事务、TURN 和 CURRENT；正文改动后必须重新准备，不得复用旧输出摘要

## 1.4. 命令入口

以下命令均在已安装项目中运行，先将变量替换为真实本轮路径和身份；不要用示例 ID 创建冒名回执

```powershell
$S = ".agent-project-control/scripts/supervisor.py"
$TR = "<真实 TR 目录>"
$RID = "<本轮 request_id>"
python -B $S inspect --turn "$TR" --request-id "$RID"
python -B $S load --turn "$TR" --request-id "$RID" --phase scope
# 按原接口记录当前计划后，再申请本轮授权
python -B $S authorize --turn "$TR" --request-id "$RID"
python -B $S load --turn "$TR" --request-id "$RID" --phase verification
python -B $S load --turn "$TR" --request-id "$RID" --phase writing
python -B $S prepare --turn "$TR" --request-id "$RID" --output "<本轮待发送文件>"
python -B $S finalize --turn "$TR" --request-id "$RID"
python -B $S status --turn "$TR" --request-id "$RID"
```

`--turn` 定位当前执行记录，`--request-id` 防止复用上一轮授权，`--output` 指向单次生成的新文件；写入、验收、暂停和输出捕获的实际参数见脚本 `--help`

恢复暂停或压缩后的任务时，先重新 `inspect`，再重新输出相应阶段的规范；旧上下文检查不能替代恢复后的读取；用户取消时使用 `interrupt --reason` 记录原因并停止本入口，不把取消误写成 IT 已完成

## 1.5. 报告如何说明监督结果

程序在当前 TR 的 `evidence/supervision.json` 保存少量事件、摘要、时序和来源，不复制整份规则与日志；这是派生检查记录，不取代 REQUEST、计划、TEST 或 Finalize 事务

在原报告的状态头写一句当前实际边界，在完整讲解中引用该回执即可，不增加第十一区或平行报告；例如可写“本轮路径、状态、阶段规范和正式收口已由入口核对；待发送正文已验证，但桌面聊天通道尚未提供独立捕获”——只能在对应事实成立时使用

`observe` 只在真实 Finalize 后比对调用者提供的捕获文件；这不是用户签收，也不是可信宿主身份认证；同一操作系统用户可以修改代码和回执，哈希链只帮助发现意外漂移，不能阻止有权限的恶意伪造

## 1.6. 部署验收与适用边界

部署后分别检验无缓存启动、第二／第三轮、从父目录显式选项目、旧请求拒绝、CURRENT 不一致、代码或规则漂移、取消恢复、正文修改以及回滚；真实 Codex、桌面、压缩和远程副本不能由合成命令行程序冒充

可选外部 CLI 适配器只封住自己的最终标准输出，其他 Codex 工具仍沿用原有沙盒和审批；禁止为了方便运行加入绕过审批或无限制沙盒参数；当前不引入 Dify／LangGraph，不给任意模型永不跳步或 99% 合规的未经测量承诺

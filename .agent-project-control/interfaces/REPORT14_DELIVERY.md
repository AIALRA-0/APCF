<!-- APCF-META {"schema":1,"visibility":"public"} -->
# 正式报告统一交付

格式来源：`../reporting/APPROVED-REFERENCE.md`，只读；结构契约：`../reporting/contract.json`；用户确认的覆盖规则：14章标题始终保留；无内容、未知与不适用分别表达；格式问题只能内部处理，不阻断报告服务；教学示例的跨章ID互不关联，不能视为真实账本；

正式报告：运行 `python -B .agent-project-control/scripts/report_delivery.py deliver --turn <真实TR绝对路径> --request-id <当前request_id>`；当前入口将实际账本、事前判据、变更前像和证据摘要捕获为类型化来源，完整十四章正文经原生事务同源保存于 TURN 和 CURRENT；`--model` 可提供解释稿，模型不能维护机器事实或改写原判据；普通问答不调用此入口；

聊天摘要：stdout 和 `--output` 返回同一修订的受检短摘要，全文留在完整报告入口；实际发送后经 `execution_session.py compare-output` 核对摘要字节、来源摘要和报告身份；默认上限 900 字，不能为限长丢掉唯一必要行动或重要限制；已校验摘要不得二次自由改写；完整正文的字节一致性仅用于 TURN/CURRENT 存储核对，聊天与全文不要求相同字节；

`check` 与 `context` 子命令只给内部 Agent，不进入用户消息；`--output` 可保存交付正文，不覆盖已有不同内容；失败/阻塞的业务结果也是合规报告；不能因为格式通过宣布工作全部完成；

真实 Agent 接入：复用已授权模型命令，在私有 `runtime/tmp/report14/quality-agent.json` 登记 `enabled` 和 `command` 数组；不经过 shell，不从稿件读取命令或凭据；writer 与 reviewer 使用独立调用上下文，局部修复只传目标字段、原始承诺、相关事实、证据和适用规则；最多两轮修复，模型响应、用量及异常留在内部证据；命令缺席、超时、审查不足或兜底均不计内容质量通过；旧 Report14 修复器保留历史兼容用途，当前写入不退回旧合同；

业务收口：先产出报告，再运行 `report_delivery.py finalize`；它只调用既有 Gate/Finalize，捕获内部异常，不把失败伪造为 PASS；原生事务、审批、证据和写作复核要求继续有效；业务收口未完成时，仍可交付准确的14章报告；

宿主必须在真实最终消息发送函数上调用 `report14.runtime.transport` 或等价 CLI 包装；调用前的生成流不得透传；AGENTS 提示不等于底层拦截；未接入的桌面聊天、任意同权限 shell 无法由仓库脚本强制控制，应由集成验收登记，不能冒称全覆盖；

观察发送：先保存版本化本地 outbox；仅在真实接收端具备匹配协议、原生身份绑定和最小 `report:observe` 权限后单向发送；确认 project、producer、IT、TR、revision 和 reportDigest 全部一致后才展示实际 AEMP 入口；未确认时展示本地 CURRENT；不使用执行者令牌，不调用完成、批准、协调应用或业务执行接口；

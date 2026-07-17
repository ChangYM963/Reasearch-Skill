# Deep Research 研究契约

本契约约束 Venue Map、Falsification 和 Final Audit 三个证据门。原始研究报告保留为 Markdown、PDF 或 JSON；同一次研究必须另交机器可校验的 sidecar，并通过 schemas/research-report.schema.json。自然语言中的“检索完成”“已全面覆盖”不构成 gate 证据。

## 三环检索

每个 Deep Research 证据包默认至少包含三个 SearchRun，每环至少一个：

1. target_venue：检索目标会议、期刊或明确指定的发表群体，覆盖目标年份窗口、主题同义词和 venue 内部术语。
2. cross_venue：检索相邻领域和主要替代 venue，主动寻找不同术语下的同一问题、强基线和反例。
3. citation_graph：对 closest papers 做向后参考文献、向前引用和相关作者、项目、仓库追踪。

不得用宽泛网页搜索代替任一环。普通搜索可用于导航到原始来源，但 sidecar 必须记录实际 query、channel、执行时间和纳排规则。若当前环境不能直接运行 Deep Research，生成结构化 handoff 并等待外部报告；不得把普通对话或臆测记为已完成的 Deep Research。

## 分阶段要求

- venue_map：建立 venue、主题和术语地图，识别值得继续筛选的 3–4 个主题。此时尚无稳定 claim 时，claim_fingerprint 可为 null。
- falsification：围绕候选 claim 主动搜索完整覆盖、强 baseline、相反结果和 oracle 无空间等推翻证据；必须绑定当前 claim_fingerprint。
- final_audit：围绕冻结后的精确 claim、comparison set 和查询协议做最新定向检索；必须同时绑定当前 claim_fingerprint 与 audit_fingerprint。

Final Audit 在 handoff 之前必须先记录 `audit_protocol`：固定 claim
fingerprint、cutoff、三环、非空同义词和每环 query protocol。报告只能复算并
匹配该 fingerprint，不能在 ingest 时反向定义或覆盖它。每环 through 必须
达到冻结 cutoff，from 不得晚于 through，executed_at 不得早于 through。

Final Audit handoff 本身必须携带完整、已冻结的 `audit_protocol` payload 和
相同的 `audit_fingerprint`；任一缺失或不能复现当前冻结 fingerprint 时必须
拒绝 handoff。当前 UTC 是统一时间上界：prepare search cutoff、
`audit_protocol` cutoff 与每环 through、每个 SearchRun 的
`date_window.through` 和 `executed_at` 均不得晚于 validator 校验时的当前 UTC
日期或时间；任何未来值都必须拒绝。

默认 coverage axes 为 problem、population_or_data、method_or_intervention、comparator、outcome_or_estimand 和 recency。决策类研究另需 decision_consequence；机制性 claim 另需 mechanism。Schema 只检查取值和存在性，validator 根据阶段与 adapter 派生“所需 axes 是否齐全”。

## 原始报告与 sidecar

每个 SearchRun.raw_report 必须记录运行根目录内的相对路径、媒体类型和文件 SHA-256。路径不得逃逸运行根目录；hash 不匹配时整个 SearchRun 不可支持 gate。原始文件不可由 sidecar 摘要替代，也不得在 revision 时删除。

Sidecar 只记录可追溯事实：检索参数、来源身份、证据命题、定位、attestation 和未解决线索。它不得包含或覆盖下列 validator 派生字段：

- rings/coverage axes 是否完整；
- 外键、稳定 identifier 和 ledger version 是否有效；
- material evidence 是否都有有效 locator；
- critical unresolved leads 是否关闭；
- claim/audit fingerprint 是否当前；
- Final Audit 是否新鲜；
- research mode policy 是否满足；
- gate_structurally_ready。

这些字段只能出现在 validator 生成的独立 QA artifact 中。报告自填 coverage、verified 或 gate_status 必须被拒绝或忽略，不能推进状态。

## Gate 资格

结构上可进入科学审计至少要求：

- sidecar 通过 schema；
- 三环与阶段所需 coverage axes 齐全；
- 所有 ID 唯一，外键和 base_ledger_version 有效；
- Source 至少有一个稳定 identifier；
- material evidence 有可复核 locator；
- sidecar 中 identity/content attestation 字段结构完整；另有当前的 source-verification artifact 覆盖本报告的来源身份、locator 与 raw-report hash 核对；
- scientific-audit artifact 明确绑定当前 subject artifact 与其 material evidence IDs；
- 无未关闭的 critical lead；
- fingerprint、raw report hash、cutoff 和 research mode 符合当前 gate policy。
- 用于 STOP 的 material evidence 必须来自当前报告、具有 locator，且其
  Source 为 full_text；source-verification 还必须明确 full_text_verified。

gate_structurally_ready 仅表示可以接受科学审计。Gate 变为 passed 还必须有独立 scientific-audit artifact，且只能由 validator 产出验证 artifact 后通过唯一事务写入层更新。

## 真值边界

确定性 validator 能证明的是结构完整、引用关系、hash 一致和已声明定位的存在。它不能证明：query 真实执行、检索绝对全面、论文确实支持某命题、来源内容无误，或 novelty 科学上成立。

因此：

- 标题或摘要相似不能据此 STOP，closest paper 必须核验全文；
- supports、contradicts 等是受审计的证据陈述，不是真值标签；
- 未检出覆盖只能表述为“在已记录范围与截止日内未发现”，不能表述为“不存在相关工作”；
- Critical lead 未关闭时不得 GO 或 Freeze；
- 新论文若改变 comparison set 或 strongest baseline，必须触发 protocol fingerprint 更新并使旧 Smoke 失效。
- 只有 `decision_eligible: true` 的科学结果才能写入终止性 verdict 或触发
  STOP/NARROW/BLOCKED/INSUFFICIENT_EVIDENCE 状态投影。

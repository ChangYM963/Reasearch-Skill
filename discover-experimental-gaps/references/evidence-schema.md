# 研究证据数据模型

research-report.schema.json 定义原始报告的机器 sidecar。本文件定义 schema 之外的外键、派生检查和审计语义。所有 ID 在同一 sidecar 内唯一；跨运行引用还必须存在于当前 canonical ledger。

## 实体

### SearchRun

一次可复现的检索单元，仅属于一个 stage 和一个 ring。

- id：稳定 ID。
- stage：venue_map、falsification 或 final_audit。
- ring：target_venue、cross_venue 或 citation_graph。
- target_ref：被检索的 venue、topic、candidate 或 claim 引用。
- claim_fingerprint：Venue Map 可为空；其余阶段必须等于当前 claim。
- audit_fingerprint：仅 Final Audit 必须等于当前 audit fingerprint。
- research_mode：记录实际模式；structured_manual 不得冒充 Deep Research。
- executed_at、date_window、非空 queries、channels、纳排规则和 coverage_axes。
- included_source_ids、带理由的 excluded_sources、unresolved_lead_ids。
- raw_report：相对路径、媒体类型和 SHA-256。
- base_ledger_version：生成报告时观察到的账本版本。

### Source

一个可核验来源。identifiers 至少包含 DOI、arXiv ID、URL 或 repository 之一；标题不是稳定 identifier。access_level 区分 full_text、abstract 和 metadata，不得把后两者表述为全文核验。

identity_attestation 记录 sidecar 作者声称由谁以何种方法核对“引用所指是否为该来源”。Schema 检查该对象的形状，运行时检查它存在，但不把其中的 artifact_id 当作权威外键。权威身份/定位核对是报告入账后单独写入、覆盖当前 report artifact 的 source_verification artifact。两者都不能保证来源内容正确。

### Evidence

一条“来源中的可定位内容”与 candidate/claim 命题之间的关系：

- search_run_id、source_id 和 subject 构成外键；
- proposition 是待审计的原子命题；
- stance 为 supports、contradicts、qualifies 或 context；
- materiality 为 material 或 contextual；
- locator 使用 PDF 页/章节/表图、网页 heading/anchor 或仓库 commit；
- content_attestation 记录对“定位内容是否支撑该 proposition”的人工或独立审计。

所有 material evidence 必须有 locator。content_attestation 是报告内声明，不是机器确认的真值；独立 scientific audit 必须用当前 evidence IDs、subject artifact IDs 和理由决定它能否参与 gate 判断。

### UnresolvedLead

记录尚未完成的追踪项，包含所属 SearchRun、描述、severity、status、下一动作和 resolution evidence IDs。critical + open 阻止 gate 通过。后续报告可以用同一 lead ID、相同描述/severity、resolved 或 dismissed 状态及本报告 resolution evidence 完成不可变状态转换；旧版写入 `lead_history`。这些证据是否实质解决该 lead 仍由 scientific audit 判断。

## 外键与一致性规则

Validator 至少执行：

1. SearchRun、Source、Evidence、UnresolvedLead 的 ID 在同一 sidecar 全局唯一；跨报告同 ID 只允许完全幂等内容，或上述 open lead 的受控 resolution。
2. included/excluded source、Evidence source、Evidence SearchRun 和 lead SearchRun 均可解析。
3. SearchRun 声明的 lead IDs 可解析到本 sidecar 的 lead。
4. Evidence 的 source 和 SearchRun 外键存在；Venue Map 的 `Evidence.subject` 必须恰为 `{"kind":"scope","ref":"<current run_id>"}`；非 Venue Map 的 claim subject 必须等于当前 claim fingerprint，candidate subject 必须属于当前 board。
5. Resolution evidence IDs 存在；是否确实处理对应 lead 不由结构验证证明。
6. raw report 使用运行根目录内的相对路径，文件存在且 hash 相同；绝对路径和目录逃逸被拒绝。
7. base_ledger_version 必须等于 ingest 时的当前 ledger version。
8. Final Audit 先有当前 audit_protocol；报告的每环日期、query protocol、claim fingerprint 和 audit fingerprint 必须与之匹配。

Schema 不能表达或不应单独决定这些跨实体规则；由运行时检查并以 reason code 报告。

## Source verification 与 scientific audit 绑定

source_verification 必须列出当前、已附着于同一 gate 的 artifact IDs，并显式给出 identity_verified、locators_verified、raw_hashes_verified 三个布尔检查。包含任一 false 的记录不能声明 PASS。

scientific_audit 至少包含：

- gate、outcome、reasoning；
- 当前 claim/protocol/audit fingerprints；
- 非空 evidence_ids；
- 非空 subject_artifact_ids。

研究 gate 的 subject_artifact_ids 必须覆盖当前 report artifact，且 evidence_ids 必须属于该 report，而不只是碰巧存在于历史 ledger。Smoke gate 必须覆盖当前 preregistration 和 result；其 `evidence_ids` 必须非空，且每一项——不能只是交集命中至少一项——都必须属于 `{current result_id, current smoke_result artifact_id}` 允许集合。旧审计、未来 ID、其他 gate 的 artifact 或 hash 不一致的审计均不能支持 passage。

## Validator QA artifact

`validate_gap_run.py` 生成独立、不可由报告作者提供的
`gate_validation` QA artifact；其中 `report_qa` 以 report_id 为键保存每份
当前报告的派生检查。最小内容包括：

- report_id、report artifact_id、gate 和 stage；
- checks.required_rings_complete；
- checks.required_axes_complete；
- checks.foreign_keys_valid；
- checks.identifiers_valid；
- checks.material_locators_valid；
- checks.critical_leads_closed；
- checks.claim_hash_current、audit_hash_current 和 date_windows_current；
- checks.raw_reports_verified、research_mode_satisfied 和 entity_ids_unique；
- structurally_ready、critical_open 和 errors。

gate_structurally_ready 是适用硬检查的合取，不是科学结论。QA artifact 不得写 novelty_proven、search_exhaustive 或 source_claim_true。科学审计另存 artifact；最终 gate 更新由唯一事务写入层完成。

## 原始文件保全

Sidecar、QA、scientific audit 和 canonical ledger 保留历史版本；gate/artifact 可被标记 stale 或 review_required，lead resolution 追加 history。NARROW、失效或重新审计不得删除原始报告、来源记录、证据、locator、event ID 或旧 hash。

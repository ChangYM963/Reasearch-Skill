# discover-experimental-gaps v1.0.0

## 一句话定位

`discover-experimental-gaps` 把指定期刊、会议或 Special Issue 的近年证据，收敛为一个经反证、最小实验和最终核验后仍成立的实验缺口，并冻结为可执行、可复核的论文实验方案。

## 它解决什么问题

这个 Skill 不是“根据几篇论文猜一个 novelty”。它把实验缺口发现变成一个有证据门、版本记录和停止条件的研究流程：

- 先理解 venue 的 Scope、CFP 和近 3–5 年实验惯例；
- 主动寻找 closest/latest papers，优先尝试推翻候选缺口；
- 比较数据、split、强基线、预算、指标、统计、消融、OOD、鲁棒性、代码和限制；
- 先用简单规则、强基线、oracle/VoI 和最小 Smoke 判断实验是否有信息价值；
- 只在证据、授权、账本版本和三个 fingerprint 一致时输出 GO 或 Experiment Freeze；
- 保留 STOP、NARROW、BLOCKED、INSUFFICIENT_EVIDENCE 和历史失效工件，避免无限检索或模糊收尾。

## 适用场景

- 已指定期刊、会议、Workshop 或 Special Issue；
- AI/ML prediction、OOD/robustness、机制验证研究；
- decision/policy/value-of-information 研究；
- 需要把文献比较直接转换为可执行实验设计；
- 希望明确知道候选缺口何时应继续、缩窄或停止。

## 不应使用或不会接受的“缺口”

- 只增加一个数据集或只扩大规模；
- 只换模型、地图或场景；
- 只补普通消融；
- 单纯重复作者的 future work；
- 仅因代码或数据未公开就声称 novelty；
- 预测 accuracy/AUC 提高，但没有独立 OOD、校准、机制价值或决策后果；
- 要求工具证明检索绝对穷尽、命题必真或论文一定可发表；
- 未经独立授权直接训练复杂模型、访问最终 holdout 或执行正式 confirmatory experiment。

## 六阶段工作流

1. **Venue Map（Deep Research）**  
   读取 Scope/CFP 与近 3–5 年工作，提取主题、方法、数据、指标、实验协议和 venue 规范，筛选 3–4 个重点主题。

2. **Candidate Discovery（普通对话）**  
   生成 3–6 个候选，先执行伪缺口硬否决，再比较重要性、可证伪性和最小实验成本。

3. **Adversarial Falsification（Deep Research）**  
   搜索 closest/latest/citing/cited/protocol papers，只保留一个主候选和至多一个备用，给出 GO、NARROW、STOP、BLOCKED 或 INSUFFICIENT_EVIDENCE。

4. **Smoke（普通对话＋显式授权）**  
   先运行 Technical Smoke。只有需要以等价性、futility 或高精度排除 meaningful effect 时，才单独预注册并授权 Precision Smoke。禁止访问最终 holdout。

5. **Final Audit（Deep Research）**  
   先冻结 audit protocol，再对精确 claim 做最新三环定向检索。新论文改变 baseline 或 claim 时进入局部 NARROW，不重新运行不受影响的全部流程。

6. **Experiment Freeze（确定性输出）**  
   五门、三指纹、账本、授权和当前工件一致后，生成双语题目、RQ、安全 novelty claim，以及数据、基线、主实验、统计、OOD/鲁棒性和正/弱/负结果路线。

## 需要的输入

最少输入：

- venue 名称和类型；有歧义时附 CFP URL 或 PDF；
- 研究主题；
- population/data regime；
- adapter：`ai-ml` 或 `decision-policy`。

建议同时提供：

- 目标年份、检索截止日和投稿期限；
- 已知 closest papers；
- 可用数据、代码和计算资源；
- 决策上下文与效用定义；
- 保密、隐私、网络、费用和文件写入限制；
- Deep Research 是否可用。

执行 Smoke 还需要版本化数据范围、预算、读写/网络权限及用户明确授权。

## 主要输出

- 中文 Venue Map、候选比较、反证结论和下一步；
- Deep Research handoff、机器 sidecar、证据账本、Gate 和版本历史；
- Technical/Precision preregistration、授权和结果记录；
- GO 时的中英双语 Experiment Freeze；
- 非 GO 时可追溯的 STOP、NARROW、BLOCKED 或 INSUFFICIENT_EVIDENCE，以及解除条件。

## Deep Research 与普通对话的边界

- Deep Research：主题提取、系统检索、closest-paper 反证和 Final Audit。
- 普通对话：候选比较、Smoke 设计、统计路线和最终实验设计。
- 没有 Deep Research 直连时：生成结构化 handoff，进入 `awaiting_research` 并等待外部报告；不得用记忆或普通网页片段冒充 Deep Research，也不得提前 GO/Freeze。

## 可靠性边界

确定性运行时可以检查 schema、文件 hash、外键、当前 subject、UTC 时间上界、CAS revision、依赖失效、授权范围与 fingerprint 一致性，但不能证明：

- 查询确实完整执行；
- 检索绝对穷尽；
- 来源一定支持某条科学命题；
- novelty 科学上必然成立；
- 授权标签背后的现实身份必然真实。

因此 source verification 与 scientific audit 仍需要独立研究判断。证据不足、critical lead 未关闭、授权不足或 hash/ledger 不一致时，Skill 不得输出 GO。研究授权也不会绕过 Codex 自身的沙箱、网络、凭据或外部写入审批。

## v1.0.0 范围

- 已实现：AI/ML prediction 与 decision/policy/VoI 两个 adapter；
- 默认：单代理顺序执行，可在环境支持时使用子代理分工；
- 输出：中文分析，题目、RQ、novelty claim 和 Freeze 核心字段中英双语；
- 不包含：medical/OR 专用 adapter、自动 schema 迁移、跨机器状态同步和复杂证据图可视化。


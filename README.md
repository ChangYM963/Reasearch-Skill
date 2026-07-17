# discover-experimental-gaps

面向 AI/ML prediction 与 decision/policy/value-of-information 研究的“实验缺口发现” Codex Skill。它把期刊、会议或 Special Issue 的文献比较，收敛为一个可反证、可执行、可复核的实验方案；不会仅凭“多一个数据集”“换一个模型”或普通消融就宣布 novelty。

详细说明见 [介绍](INTRODUCTION.zh-CN.md)，完整安装与运维规则见 [安装手册](INSTALL.zh-CN.md)。

## 它做什么

1. 用 Deep Research 绘制目标 venue、近年主题、常用方法、数据集、指标与实验协议。
2. 生成实验缺口候选，并硬否决“只扩数据、只扩规模、只换模型、普通消融、重复 future work、预测提高但决策不变”等伪缺口。
3. 主动搜索 closest/latest papers 反证候选，只保留一个主候选和至多一个备用候选。
4. 在显式授权下，先用强基线、简单规则、oracle/VoI 与小型 Smoke Test 验证实验价值。
5. 对精确 novelty claim 做 Final Audit；证据、授权、hash 或 gate 不一致时，绝不输出 `GO` 或 Experiment Freeze。

它适用于“我需要找到一个真实且可发表的实验缺口，并把它落实为实验计划”的场景；不用于保证论文必然发表，也不把代码或数据未公开本身视为实验缺口。

## Linux 服务器快速安装

推荐使用发布 archive 安装：它包含固定版本、SHA-256 校验和跨平台安装器。

```bash
mkdir -p ~/tmp/discover-experimental-gaps
cd ~/tmp/discover-experimental-gaps

curl -LO https://raw.githubusercontent.com/ChangYM963/Reasearch-Skill/main/releases/discover-experimental-gaps-v1.0.0.tar.gz
curl -LO https://raw.githubusercontent.com/ChangYM963/Reasearch-Skill/main/releases/SHA256SUMS.txt
sha256sum -c SHA256SUMS.txt

tar -xzf discover-experimental-gaps-v1.0.0.tar.gz
cd discover-experimental-gaps-v1.0.0

python3 ./install_skill.py --install-root "$HOME/.agents/skills" --dry-run
python3 ./install_skill.py --install-root "$HOME/.agents/skills" --run-tests
python3 ./install_skill.py --install-root "$HOME/.agents/skills" --verify-only
```

要求：Python 3.9+；无需第三方 Python 包。`--install-root` 必须与你的 Codex 实际使用的唯一 skills root 一致；若环境使用 `CODEX_HOME` 或 legacy `.codex/skills`，请按 [安装手册](INSTALL.zh-CN.md) 指定对应绝对路径。安装器不会猜测 root，也不会覆盖同名 Skill。

安装完成后重新加载 Codex 或新建一个任务。可用类似下面的请求触发：

> 使用 `$discover-experimental-gaps`，根据指定期刊、近年论文和实验协议，寻找可证伪的实验研究缺口；先完成 Venue Map 和 closest-paper 反证，再提出最小 Smoke Test。

## 仓库内容

| 路径 | 用途 |
| --- | --- |
| `discover-experimental-gaps/` | 唯一需要安装到 Codex skills root 的运行时目录；包含 `SKILL.md`、schemas、references 和 scripts。 |
| `install_skill.py` | 仅用 Python 标准库的安装器；执行 hash、冲突、锁与完整性校验。 |
| `releases/` | v1.0.0 的 Linux `.tar.gz`、Windows `.zip` 与 SHA-256 校验清单。 |
| `INSTALL.zh-CN.md` | 服务器部署、验证、升级、卸载和冲突处理的完整说明。 |
| `INTRODUCTION.zh-CN.md` | 方法论、边界、输入、输出与状态机说明。 |
| `evals/` | 51 项离线回归测试；不安装到 skills root。 |

## 可靠性边界

- Deep Research 负责文献证据、反证和 Final Audit；普通对话负责候选比较、Smoke 设计与实验方案。
- 没有 Deep Research 直连时，Skill 会生成结构化 handoff 并停在 `awaiting_research`，不会假装证据充分。
- Smoke 的设计授权与执行授权分离；复杂训练、最终 holdout、远程计算、外部 API 和上传默认不获授权。
- 运行时有五个证据 gate、三种 fingerprint 与可追溯失效历史；`NARROW` 只重做受影响的局部工作。

## 校验值

`releases/SHA256SUMS.txt` 是发布 archive 的校验来源。v1.0.0：

- `discover-experimental-gaps-v1.0.0.tar.gz`：`161f8291727513c9c621bbda1dfe95dfc22ddb9d0fe9c56c7ffe5e12af7dbd8c`
- `discover-experimental-gaps-v1.0.0.zip`：`9a31201aca5f42a0b5882b04dc4599edec6b62033deb1f381d25f624967bc7bd`

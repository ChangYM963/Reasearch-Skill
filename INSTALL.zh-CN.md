# discover-experimental-gaps v1.0.0 跨服务器安装方案

## 发布包结构

解压后应看到：

```text
discover-experimental-gaps-v1.0.0/
├─ discover-experimental-gaps/   # 安装到 Codex skills root 的唯一目录
├─ evals/                        # 51 项离线回归测试，不会安装
├─ install_skill.py              # Python 标准库安装器
├─ SKILL-MANIFEST.sha256         # 21 个运行文件的递归哈希
├─ RELEASE.json
├─ INTRODUCTION.zh-CN.md
└─ INSTALL.zh-CN.md
```

安装器、测试和用户文档位于外层；`discover-experimental-gaps/` 内只保留 Codex 运行所需文件。

## 环境要求

- Codex 能从目标 skills root 发现用户 Skill；
- Python 3.9 或更高版本，推荐 3.11/3.12；
- 不需要安装第三方 Python 包；
- 安装用户对目标 root 有写权限，运行 Codex 的账户对其有读权限；
- 目标服务器时间应正确同步，因为检索新鲜度使用 UTC 上界校验。

## 第一步：选择唯一安装 root

必须根据目标服务器实际 Codex 配置选择，安装器不会猜测：

- 当前常用用户级目录：`$HOME/.agents/skills`；
- 明确设置 `CODEX_HOME` 时可使用：`$CODEX_HOME/skills`；
- legacy 环境可能仍使用：`$HOME/.codex/skills`。

不要同时安装到多个 root。多用户服务器应按服务账户分别安装，或使用管理员批准且只读共享的 skills root。

## 第二步：校验归档

发布目录旁的 `SHA256SUMS.txt` 记录 ZIP 和 TAR.GZ 的哈希。

Windows PowerShell：

```powershell
Get-FileHash .\discover-experimental-gaps-v1.0.0.zip -Algorithm SHA256
```

Linux：

```bash
sha256sum discover-experimental-gaps-v1.0.0.tar.gz
```

结果必须与 `SHA256SUMS.txt` 完全一致，再解压。

SHA-256 可以发现传输损坏，但如果归档和校验文件从同一不可信位置一起被替换，它不能单独证明发布者身份。正式分发时，应通过独立可信通道公布 expected hash，或对 `SHA256SUMS.txt` 使用组织现有的代码签名、制品签名或 release attestation。

## 第三步：解压

Windows PowerShell：

```powershell
Expand-Archive .\discover-experimental-gaps-v1.0.0.zip -DestinationPath .\release
Set-Location .\release\discover-experimental-gaps-v1.0.0
```

Linux：

```bash
tar -xzf discover-experimental-gaps-v1.0.0.tar.gz
cd discover-experimental-gaps-v1.0.0
```

## 第四步：先做 dry run

Windows：

```powershell
python .\install_skill.py --install-root "$HOME\.agents\skills" --dry-run
```

Linux：

```bash
python3 ./install_skill.py --install-root "$HOME/.agents/skills" --dry-run
```

dry run 会：

- 校验 `RELEASE.json`；
- 校验 21 个运行文件和 `SKILL-MANIFEST.sha256`；
- 拒绝 symlink/reparse point；
- 拒绝 install root 或目标目录与解压后的 release bundle/packaged Skill 存在祖先、后代或同路径重叠；
- 检查显式 root、`~/.agents/skills`、`~/.codex/skills` 和 `$CODEX_HOME/skills` 的任何同名文件系统条目；
- 不创建或修改安装目录。

## 第五步：安装

推荐同时运行离线测试。

Windows：

```powershell
python .\install_skill.py --install-root "$HOME\.agents\skills" --run-tests
```

Linux：

```bash
python3 ./install_skill.py --install-root "$HOME/.agents/skills" --run-tests
```

如果目标服务器存在官方 `quick_validate.py`，可额外传入：

```text
--quick-validate <absolute-path-to-quick_validate.py>
```

安装器会先验证发布物，再复制到目标 root 内的临时目录。正式发布时，它以排他方式创建 `discover-experimental-gaps`，复制其他运行文件，并在最后原子发布 `SKILL.md` 以激活发现；因此不会覆盖已有同名文件系统条目，也不会只链接 `SKILL.md`。

## 第六步：验证已安装副本

Windows：

```powershell
python .\install_skill.py --install-root "$HOME\.agents\skills" --verify-only
```

Linux：

```bash
python3 ./install_skill.py --install-root "$HOME/.agents/skills" --verify-only
```

成功结果应包含：

- `"action": "verified"`；
- `"runtime_files": 21`；
- `skill_tree_sha256` 与 `RELEASE.json` 完全一致。

随后重新加载 Codex 或新建任务，确认 Available Skills 中只有一个 `discover-experimental-gaps`，locator 指向刚安装的唯一目标。

可以用不含 Skill 名称的语义请求测试触发：

> 请根据目标期刊、最近论文和实验协议寻找可证伪的实验研究缺口，并先做最小 smoke test。

## Deep Research 不可用时

安装和本地状态机仍可工作。Skill 会：

1. 生成结构化 research handoff；
2. 把运行置为 `awaiting_research`；
3. 停在 Venue Map、Falsification 或 Final Audit 的证据边界；
4. 等待外部研究环境返回原始 Markdown/PDF、sidecar 和 hash。

它不会用普通对话或记忆冒充 Deep Research，也不会在证据不足时输出 GO 或 Experiment Freeze。

## 同名冲突

安装器遇到任何同名文件系统条目都会停止，包括实体目录、普通文件、symlink、junction、reparse point 或 dangling link；它不会 merge 或覆盖。先确认哪一份是有效安装，再由运维者处理：

- 保留唯一目标；
- 将旧版本移动到所有 skills root 之外的隔离目录；
- 重新运行 dry run；
- 再执行安装。

不要把备份目录留在任何 skills root 内，否则 Codex 可能再次发现它。

安装器会根据全部 known roots 获取协调锁，并在显式 root 内再获取目标锁，以串行化同一账户的并发安装。若进程异常退出后报告 stale lock，先核对错误信息中的绝对锁路径和记录的 PID，确认没有安装进程仍在运行后再由运维者处理；不要自动删除未知锁。

## 升级方案

本安装器刻意不做原地覆盖。安全升级步骤：

1. 使用新包执行 dry run、manifest 校验和离线测试；
2. 记录旧版 `skill_version`、`schema_version` 和 `fingerprint_version`；
3. 将旧 Skill 移动到 skills root 外、但位于同一文件系统的备份目录；同文件系统 rename 才能作为原子切换；
4. 安装新版本并执行 `--verify-only`；
5. 新建 Codex 任务验证自动发现和语义触发；
6. 验证失败时移走新版本并恢复旧目录。

运行数据应保存在 Skill 目录之外。升级或卸载不得删除、覆盖或静默迁移已有 run。未知 major schema 必须显式迁移，不能自动改写。

## 卸载方案

卸载采用“隔离”而不是直接递归删除：

1. 解析并确认 `<install-root>/discover-experimental-gaps` 的绝对路径，且目标是实体目录而非 link/reparse point；
2. 将该目录移动到所有 skills root 之外的隔离目录；优先使用同文件系统 rename；
3. 重新加载 Codex，确认 catalog 中已消失；
4. 按运维保留策略人工删除隔离副本。

如果隔离目录位于另一文件系统，不要把 move 称为原子操作：先复制，按 `SKILL-MANIFEST.sha256` 递归核验，再切换；任何失败都保留原安装。不要跟随链接递归删除，也不要删除任何实验 run、外部研究报告、数据或凭据。

## 安全与运维注意事项

- 不要把 API key、令牌或数据凭据写入 Skill；
- 不要把服务器 run data 放进安装目录；
- 安装授权不等于 Smoke 执行授权；
- Smoke 研究授权不绕过 Codex 沙箱、网络、凭据或外部写入审批；
- 服务账户的 `HOME` 与交互登录账户不同，必须使用实际运行 Codex 的账户路径；
- 容器或只读镜像应在构建阶段安装，并在运行阶段只读挂载唯一 Skill 目录；
- 运行目录优先放在服务器本地磁盘；不要让多台机器并发写同一 NFS/SMB run-dir，锁文件和原子替换语义取决于共享文件系统。

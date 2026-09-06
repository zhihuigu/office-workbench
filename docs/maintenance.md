# 备份、迁移、升级与故障处理

## 先理解备份范围

完整私人目录是可迁移单位：CASE、sources、work、deliverables、SERIES、KNOWLEDGE、LOCAL.md、安装运行时和标记都包含在内。看板、索引和 DERIVED 虽可重建，备份也保留它们。事务文件含旧 CASE 字节，备份与恢复报告同样属于私人资料。

本项目的备份是普通目录副本，**不加密、不上传、不定时执行**。请按自己的需要放在有访问控制或磁盘加密的独立介质，保留多代备份。磁盘上的校验清单用于发现意外变化，不是针对恶意篡改的数字签名。

## 创建并检验备份

先停止 Codex、编辑器或同步工具对该私人目录的写入，关闭正编辑的材料。在**代码目录**的 PowerShell 运行（目标父目录必须已存在，目标不能已经存在）：

```powershell
python -I -B .\workbench.py backup --workspace "$env:USERPROFILE\MyOffice" --destination "$env:USERPROFILE\MyOfficeBackup-01" --dry-run
python -I -B .\workbench.py backup --workspace "$env:USERPROFILE\MyOffice" --destination "$env:USERPROFILE\MyOfficeBackup-01"
```

备份先检查运行时、CASE 和未恢复事务，写入期间持有本工具的工作目录锁；比较复制前后的源内容与目标哈希，保留空目录，生成 backup-manifest.json。只排除 `.caseboard/locks/` 中的瞬时锁文件，它们在恢复后按需重新建立，不是业务数据。手工编辑器不遵守这个锁，所以仍需要停写。软链接、junction、硬链接会被拒绝。大文件逐个哈希/读取，当前实现不适合超大型资料库。

备份校验有错误时不会把临时目录改名为正式备份。`.目标.backup-随机值` 是失败现场，不能因为存在就认定备份成功。确认另有完整备份后，才由你决定如何处置失败现场。

如果 CASE 已坏导致工具拒绝备份，先用资源管理器把**完整目录**复制到另一个私人位置保留现场，包含隐藏文件；该副本不是已验证备份。再在副本中诊断，不要先修原件或删除错误记录。

## 恢复到另一目录

```powershell
python -I -B .\workbench.py restore --backup "$env:USERPROFILE\MyOfficeBackup-01" --workspace "$env:USERPROFILE\MyOfficeRestored" --dry-run
python -I -B .\workbench.py restore --backup "$env:USERPROFILE\MyOfficeBackup-01" --workspace "$env:USERPROFILE\MyOfficeRestored"
python -I -B "$env:USERPROFILE\MyOfficeRestored\office.py" doctor
```

恢复必须使用可信的本项目备份，校验 manifest 与文件/目录一致，不接受覆盖原目录。运行时完整性校验使用备份中的信任数据，并不是防御恶意备份的代码审计；不要恢复陌生人发来的工作目录。

在新目录抽查若干 CASE 和 Final：运行 search、verify-final，打开关键成果，再用 refresh 重建显示日期。Codex 改为打开新目录，避免同时在两个副本里继续工作。旧目录和备份先保留。

## 换电脑或换磁盘

1. 停写后做上述完整备份，将整个备份文件夹通过自己的安全方式传到新电脑。
2. 新电脑安装可用 Python，自己安装并登录 Codex；不要复制旧电脑的 Codex 登录、cookie、token 或全局配置。
3. 下载相同或已验证兼容的代码版本，在新私人目录执行 restore。
4. 运行 doctor、validate、若干 verify-final；进入 Codex 做快速开始中的会话自检。
5. 可选连接器在新电脑按其官方方法重新安装、授权，只迁移自己批准的非敏感偏好。

也可以在全部停写且没有待恢复事务时完整复制私人目录；路径改名不影响相对引用。不要只复制 ACTIVE，不要漏掉隐藏安装目录和标记。已中断事务的恢复记录可能含绝对路径，必须先在原位置恢复完成，再迁移。网络共享盘、多机同时写和云盘冲突合并未经验证。

## 升级

本版升级只更换独立运行时、通用模板和随版本附带的手册，**不做 CASE schema 自动迁移**。根目录 AGENTS.md、LOCAL.md、office.py 和所有私人资料都保留。

1. 停止其他写入，先做一份已验证备份。
2. 把新发布源码下载到另一个代码目录；阅读其变更说明、支持范围和授权。
3. 在新代码目录运行：

```powershell
python -I -B .\workbench.py upgrade --workspace "$env:USERPROFILE\MyOffice" --dry-run
python -I -B .\workbench.py upgrade --workspace "$env:USERPROFILE\MyOffice"
python -I -B "$env:USERPROFILE\MyOffice\office.py" doctor
```

新运行时写入新版本目录，先校验现有 CASE，然后原子切换标记；旧版本保留，不删除历史。同版本、同内容是无操作。若根启动器不同，自动升级拒绝，先保留原目录，按后续版本专门说明迁移，不覆盖文件“试试看”。根 AGENTS 的新建议需要自己对比模板并决定是否采纳；个人补充尽量放 LOCAL.md。

升级失败且标记未切换时旧版本仍可用；已经切换但业务抽查失败时，**恢复升级前备份到新目录**并验收，再切换 Codex 的项目位置。没有自动降级或合并两份工作目录；升级后新增工作应先保留并逐项迁移。

当前测试验证了本版升级机制与构造的新运行时快照，不能证明尚未发布的未来版本兼容。

## 常见故障

| 现象 | 处理 |
|---|---|
| python 找不到或版本太旧 | 检查 Python 安装和终端；不写死别人的路径，不修改 Codex 全局配置 |
| 目标已存在 | 使用不存在的新目标；不要清空已有工作目录 |
| 目标在 Git 仓库内、父目录是链接 | 选独立本地路径，路径必须明确且不含 `..` |
| doctor 有 MANUAL | 在 Codex 会话验证规则与本地命令；不表示必须安装连接器 |
| 看板没更新、日期旧 | 先 validate，再 refresh；没有后台自动刷新 |
| 路径不存在、CASE 解析失败 | 备份现场，核实文件名、引号、日期、相对路径与编码；不创建假材料 |
| 找不到历史或扫描不完整 | 查看 json-v2 diagnostics，查 CASE，而不是只读索引；不要将空数组当不存在 |
| stale write / 其他会话已更新 | 停止覆盖，重新读最新 CASE，合并事实再操作 |
| 写锁超时 | 停止或等待另一个写入进程；锁文件存在不表示锁仍被持有，不删除锁文件 |
| Final 指纹变化 | 保留变化文件，查独立备份和确认依据；不修改哈希来消除提示 |
| 运行时文件变化 | 保存现场，从可信备份恢复到新目录；不覆盖私人规则或静默重新下载 |
| 邮件/钉钉工具不可用 | 核心仍可用；自行恢复可选接入，或在授权后手工保存特定材料 |

## 中断事务

普通失败会尝试自动补偿。如果进程被强退或补偿遇到外部改动，先停写并完整复制现场，执行：

```powershell
python -I -B .\office.py check
python -I -B .\office.py repair --recover --dry-run
```

核实预览中的恢复目标、没有外部新改动，并明确决定恢复后：

```powershell
python -I -B .\office.py repair --recover
python -I -B .\office.py validate
```

恢复冲突时工具保留记录和现场，不要删除 `.caseboard/transactions` 或编辑日志来强行继续。找不到原字节、无法解释冲突时停止自动修复，回到完整备份副本人工核对。

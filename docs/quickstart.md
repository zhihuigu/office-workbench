# 初始化与第一轮使用

## 准备

你已经有一个能读取项目文件、运行本地命令的 AI Agent，并能正常使用。本项目不安装 AI 产品，也不替你登录。
另外需要本机 Python 3.12 或以上；在 PowerShell 运行 `python --version`。如果命令找不到或打开商店，请先安装 Python，再重新打开终端。不要将某人的 Python 绝对路径复制过来。核心不需要 pip、Node、Office 软件或任何外部 Skill。

本候选只验证 Windows + Python 3.14.6 的本地脚本流程，会话层使用 Codex 验证。不同 Agent 自动理解项目规则的效果受产品、模型、当前会话和用户设置影响，必须做本节的会话自检；脚本测试通过不等于任何人的登录或连接器可用。

## 两个目录各自做什么

- 代码目录是你下载的 `office-workbench`。更新软件时下载新代码即可。这里不能放真实工作材料。
- 私人目录由 init 建立，例如当前用户目录下的 `MyOffice`。日常让 AI Agent 把这里作为项目目录打开。

不要使用公开仓库内部的 `data/` 子目录，即使有 `.gitignore`。不要选择另一个办公工作台、非空目录、符号链接、junction 或网络同步盘作为初次验证位置。目录包含中文和空格可以使用，命令路径需要引号。当前保证范围是单机本地磁盘。

## 先预览，再初始化

在**代码目录**的 PowerShell 中：

```powershell
python -I -B .\workbench.py init --workspace "$env:USERPROFILE\MyOffice" --dry-run
python -I -B .\workbench.py init --workspace "$env:USERPROFILE\MyOffice"
```

第二条会创建新的私人目录、安装独立运行时、模板和手册，写入 AGENTS.md、LOCAL.md、启动器、工作目录标记，建立空看板和索引。没有演示任务，没有全局设置或登录资料。

`--dry-run` 不创建目标。如果 MyOffice 已存在，命令会拒绝；不要删除自己的旧目录来绕过。选一个不同的新目录即可。若初始化中断，可能留有 `.MyOffice.init-随机值` 临时目录；正式目标未就绪时先保留该目录检查，不要与既有目录合并。

## 验证脚本

在 PowerShell 切换到**私人目录**：

```powershell
Set-Location "$env:USERPROFILE\MyOffice"
python -I -B .\office.py version
python -I -B .\office.py doctor
python -I -B .\office.py dashboard --format json
```

预期：version 输出私人目录和安装版本；doctor 的核心检查没有 FAIL，AI Agent 会话一项标记 MANUAL；dashboard 的 `all_active` 为空且 `errors` 为空。`MANUAL` 表示需在会话中核实，不是缺少插件导致的失败。

日常脚本从任意终端调用私人目录的 office.py 都能定位自身目录。但 AI Agent 会话仍应以私人目录作为当前工作目录，这样才能发现正确的项目规则。

## 验证 AI Agent 会话

在 AI Agent 中把 MyOffice 作为本地项目/目录打开，开启新会话。不要把日常办公切到代码目录或 Git worktree，也不要为了使用本项目开启更宽的权限模式。

先说：

> 读取本目录 AGENTS.md 和 LOCAL.md，说明你目前的工作目录、CASE 事实源和 Final/归档边界，再运行 python -I -B office.py doctor。不要修改任何任务。

确认它能说出当前私人目录，理解“制作完成只待审、Final 与归档分别确认”，并执行本地命令。Codex 可以使用 [`AGENTS.md` 机制](https://learn.chatgpt.com/docs/agent-configuration/agents-md)；其他 Agent 若不自动识别 `AGENTS.md`，请按对应产品的项目规则机制引用这份规则，或在会话开始时明确要求读取。本项目不会安装全局 Skill。规则发现与用户已有全局规则会同时影响会话；出现冲突时先检查来源，不修改全局文件来强行通过。

若它没有加载规则：确认路径与文件名正确；在私人目录重开会话；明确让它读取 AGENTS.md。若不能执行命令，保留现有权限，检查当前 Agent 是否被允许在该目录执行本地 Python。不要用关闭沙箱或自动批准所有动作作为修复手段。

## 第一件真实任务

用你自己的任务替换这句虚构示例：

> 帮我筹备云朵书屋读书交流会，下一步先起草议程，截止日期尚未确定。先看看有没有重复事项，再建立合适的 CASE。

任务建成后，AI Agent 应返回 case_id、CASE 位置、状态和下一步。你可以在资源管理器打开 CASE.md 和工作看板.md。没有材料就先记录要求；不要求你填完整张表。

完整操作参数看 `python -I -B office.py --help`。在离线终端查看本机手册入口：`python -I -B office.py guide`。

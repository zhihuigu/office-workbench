# 命令参考

两类入口分开：代码目录的 `workbench.py` 做安装维护；私人目录的 `office.py` 做日常事项管理。路径带空格需加引号。所有命令都可加 `--help`。不要直接运行 engine/caseboard.py 绕过安装检查。

## 安装维护

```text
python -I -B workbench.py init --workspace NEW_PATH [--dry-run]
python -I -B workbench.py backup --workspace PATH --destination NEW_BACKUP [--dry-run]
python -I -B workbench.py restore --backup BACKUP_PATH --workspace NEW_PATH [--dry-run]
python -I -B workbench.py upgrade --workspace PATH [--dry-run]
```

PATH 均由使用者明确指定；目标父目录须存在。具体停写与验收步骤见维护手册。本版不提供覆盖已有目录、全局安装、自动下载更新、删除或上传命令。

## 日常读操作

```text
python -I -B office.py version
python -I -B office.py guide
python -I -B office.py dashboard --format json
python -I -B office.py doctor --format json
python -I -B office.py validate
python -I -B office.py search --query "关键词" --purpose inspect --format json-v2
python -I -B office.py search --series-id SERIES_ID --period "2030-04" --purpose continue --format json-v2
python -I -B office.py context --case CASE_ID --purpose continue --format json
python -I -B office.py verify-final --case CASE_ID
```

`version`、`guide` 是私人启动器命令。doctor/check 只读；validate 不刷新视图。dashboard 支持 `--date YYYY-MM-DD`、`--days` 和 `--recent-days`；缺省用本机日期。

search 的 `--case-id`、`--series-id` 不区分大小写精确匹配；`--period` 精确匹配；`--date` 配 `--date-field created|due|next_action_due|period`。多条件 AND，先筛选再排序最后 limit。关键词匹配 CASE 标题、字段和正文，非语义向量搜索。limit 默认 20，范围 1–1000。

新调用方应使用 `--format json-v2`。必须消费 protocol_version=case-search/2、scan_complete、diagnostics、truncated、selection_required 和各项 version_selection。旧 text/json 仅供兼容导航，不得用旧的 preferred_version 替代用途判断。

context 的 `--max-chars` 默认 12000、范围 4096–100000，单位字符不是 token。`--format md` 输出相同结构化字段的 Markdown 表示。`--save review.json` 或 md 格式对应的 `--save review.md` 才保存到 DERIVED/task-context，不接受子路径或覆盖。

## 写操作

```text
python -I -B office.py new --title "事项名称" --source "本次交代" --next-action "核实要求"
python -I -B office.py update --case CASE_ID --status awaiting_user --current-version "work/稿件V1.md" --next-action "请用户审阅"
python -I -B office.py update --case CASE_ID --status submitted --submitted-version "deliverables/稿件V2.md" --waiting-for "审核意见"
python -I -B office.py series-new --title "每月阅读分享" --cadence "每月"
python -I -B office.py new --title "阅读分享本期" --source "本期要求" --series-id SERIES_ID --series "每月阅读分享" --period "2030-04"
python -I -B office.py refresh
```

new 支持 `--created`、`--due`、`--next-action-due`、`--priority urgent|high|normal|low`、`--series-id`、`--series`、`--period`。日期缺省则按命令语义使用当天或留空，不自动推算。相似在办事项会阻止重复创建，确认独立后才用 `--allow-related-new`。

update 可改 status、priority、due、next-action-due、waiting-for、next-action、current-version、submitted-version，并用 `--note` 留依据。清空可在交互 PowerShell 使用空字符串参数；不同终端对空参数传递不同，遇到参数缺失请让 Codex 用 Python subprocess 的参数列表传入 `''`，不要改成文本“无”假装空日期。

以下操作仅在已得到明确用户授权时执行，示例中的确认说明应换成真实授权原意：

```text
python -I -B office.py confirm-final --case CASE_ID --final-version V2 --final-path "deliverables/稿件V2.md" --confirmation-note "用户明确确认此版本" --confirm
python -I -B office.py archive --case CASE_ID --confirmation-note "用户确认闭环归档" --confirm
python -I -B office.py reopen --case CASE_ID --reason "新增要求"
```

new、series-new、update、confirm-final、archive、reopen、refresh、index、repair 支持 `--dry-run`，但 Final/归档的确认参数仍需有依据。reopen 从 ARCHIVE 建关联后续 CASE，不复制旧材料，不覆盖旧 Final。

## 返回码与异常

- 0：命令完成，但结构化输出仍可能有警告或部分扫描错误。必须检查 JSON 完整性字段和 warnings/errors。
- 1：validate/doctor 检出失败，或 verify-final 不可验证、指纹不符。原始材料不会因此自动修复。
- 2：参数、路径、安装完整性或安全预检失败。应阅读错误，不据此跳过检查。

结构化写入使用单机 OS 锁、源内容指纹比较、原子替换和补偿事务。普通失败补偿；进程中断留下事务时按 `check` → `repair --recover --dry-run` → 核实后恢复。不能把它解释为同时编辑 Office 文件的事务或多机协作系统。

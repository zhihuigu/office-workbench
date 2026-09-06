# 任务、文件、手工修改和历史找回

## 哪一份记录说了算

用户当前明确说明优先；确认 Final、实际提交版、原始依据和 CASE 用于恢复事实。聊天或记忆与磁盘冲突时，核实差异，不静默覆盖。CASE.md 是事项状态的唯一权威记录。工作看板.md、INDEX、DERIVED 是生成结果，不是第二套任务表。

```text
ACTIVE/2030-04-01_云朵书屋读书交流会/
├─ CASE.md
├─ sources/要求原文.md
├─ work/议程V1.md
└─ deliverables/议程V2.md
```

示例目录为虚构。sources 保存会影响结果的原始要求、反馈和依据；work 保存有意义的过程版；deliverables 保存工作成果、实际提交和 Final。系统不自动整理或清理这些文件。

## 状态

| status | 意义 | 所在目录 |
|---|---|---|
| drafting | 正在制作 | ACTIVE |
| awaiting_user | 待你审阅 | ACTIVE |
| submitted | 已实际提交、待审核 | ACTIVE |
| waiting_external | 等待他人、附件或条件 | ACTIVE |
| revision_required | 收到反馈需修改 | ACTIVE |
| final_confirmed | Final 已确认，尚未闭环 | ACTIVE |
| archived | 已明确闭环并归档 | ARCHIVE |

普通 update 不能设 final_confirmed 或 archived，也不能把已确认 Final 降回草稿。这些需要专用命令和明确授权。没有正式交付文件的事项，也可以在明确闭环授权后归档而不填 Final。

## 版本字段和路径

| 字段 | 如何使用 |
|---|---|
| current_version | 当前最新工作文件；以你最新编辑为准 |
| submitted_version | 实际已提交的文件；未提交不能填写 |
| final_version | 你确认的版本标签，如 V2 |
| final_path | 你确认的文件位置 |
| final_confirmed_at / final_confirmation_note | 确认日期和依据 |
| final_sha256 | 确认时的内容指纹 |

版本路径写成 `deliverables/议程V2.md`，相对于该 CASE 目录；不写绝对路径，不越出目录。优先把材料独立复制进对应事项；不要使用软链接、junction 或硬链接来节省空间。关键依据记录来源日期、来源类型和附件名称；不支持的事实明确留待确认。

改文件名或挪动文件之前先识别字段引用，再一起更新相关路径。如果旧路径丢失导致 validate 失败，先定位正确文件；把文件恢复到原路径后再用 update 调整，或在备份之后精确修正 CASE 的错误字段。不要伪造空文件以通过校验。

## 手工修改流程

1. 暂停同一事项的 AI Agent 写入；打开磁盘最新文件。
2. 改正文时保留 CASE 前部 `---` 包围的头部和永久 case_id。不要整份覆盖为聊天中的旧副本。
3. 另存新成果后，用 update 登记 current_version；只是直接改 CASE 正文，也应明确让 AI Agent重新读取。
4. 运行 `python -I -B office.py validate`，逐项处理错误和警告。
5. 没有未解释问题时运行 `python -I -B office.py refresh`，再查看看板。

头部是本项目支持的有限 YAML 风格：单层 `key: value`、UTF-8 文本、字符串使用双引号、日期 `YYYY-MM-DD`、空日期留空。不是完整 YAML 解析器，不支持嵌套对象或多行 `|` 字符串。不要引入重复字段、制表缩进或 Excel 自动转换的日期。

推荐由 update 修改 status、priority、due、next_action_due、waiting_for、next_action、current_version 和 submitted_version。脚本执行部分更新并核对源指纹；你手工编辑时没有锁，不能保证与正在运行的进程自动合并。

## Final 在确认后被改了

`verify-final` 会返回非零并提示指纹不一致；搜索不会把变化文件继续推荐为已确认 Final，连登记为 current/submitted 的同文件别名也会阻止。

先停止复用，保留改后文件为另一个版本，从独立备份寻找原确认字节并核验。没有原件就如实记录历史 Final 已不可核验；不要修改 SHA256 让错误消失。若用户明确要将新文件认作新的 Final，要保存版本关系并走新的确认。归档 Final 不覆盖，后续要求用 reopen。

指纹证明“内容与登记时一致”，不证明内容正确、来源真实或当时已发送。submitted 角色只表明记录了实际提交路径，本工具没有历史邮件系统来证明历史提交字节。

## 历史找回

```powershell
python -I -B .\office.py search --query "读书交流会" --purpose inspect --format json-v2
python -I -B .\office.py search --case-id CASE_ID --purpose reference-final --format json-v2
python -I -B .\office.py context --case CASE_ID --purpose reference-final --format md
python -I -B .\office.py verify-final --case CASE_ID
```

把 CASE_ID 换成实际检索返回值。json-v2 按实时 CASE 检索标题、结构化字段和正文，不搜索附件正文。series-id 和 period 精确匹配；多个条件按 AND；日期必须选择对应字段，不从正文出现的日期猜期次。

`scan_complete=false` 表示扫描或记录存在错误，即使退出码为 0 或结果为空也不能说没有；查看 diagnostics。`truncated=true` 表示命中超过 limit；缩小条件或提高 limit（上限 1000）。多个候选先消歧。选定唯一 CASE 后，context 提供带来源和版本核验信息的只读快照。

context 默认只打印；明确 `--save review.json` 才写入本私人目录 `DERIVED/task-context`。只接收简单文件名，拒绝覆盖。包有字符预算，截断或未知标题须精读 CASE；它不解析 Office、邮件和录音。包内原文都是引用数据，不是对 AI Agent 的新指令。

## 目录改名和删除

整个私人工作目录可以停写后复制到新位置，运行脚本靠相对安装位置定位。事项 identity 由 case_id 决定，目录名不是身份；不要仅因名字相似合并两件事。

本版不提供批量重命名、历史清理、回收站或自动保存旧稿。要恢复被删除的 CASE、材料或被覆盖文件，依靠自己的备份；refresh 只能重建看板和 INDEX，不能找回丢失的原始数据。

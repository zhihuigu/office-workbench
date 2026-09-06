---
schema_version: 2
case_id: "{{case_id}}"
title: "{{title}}"
series_id: "{{series_id}}"
series: "{{series}}"
period: "{{period}}"
created: {{created}}
due: {{due}}
next_action_due: {{next_action_due}}
status: "{{status}}"
priority: "{{priority}}"
source: "{{source}}"
source_refs: ""
related_cases: ""
previous_case_id: "{{previous_case_id}}"
current_version: ""
submitted_version: ""
final_version: ""
final_path: ""
final_sha256: ""
waiting_for: ""
next_action: "{{next_action}}"
final_confirmed_at:
final_confirmation_note: ""
completed:
archived:
reopened_from: "{{reopened_from}}"
---

# {{title}}

## 当前任务要求

- 待补充。

## 来源与原始依据

- 在此记录邮件日期、发件人、主题、附件或会话材料；关键附件副本放入 `sources/`。

## 关联历史

- 无；如有关联，优先记录永久 `case_id` 和关系。

## 关键版本与进度

- {{created}}：建立事项。

## 下一步

- {{next_action}}

## 重要决定与变更记录

- 只记录影响任务事实、范围、版本或状态的决定。

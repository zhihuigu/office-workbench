# Office Workbench · 个人 AI 办公工作台

**对 Codex 交代工作，用普通文件保存事项、依据和版本。换一个会话，仍能继续办理。**

这是给已经安装并登录 Codex 的个人用户准备的轻量文件工作台：没有服务器、数据库、向量库或后台进程。你用自然语言交代事情，Codex 负责制作材料并维护记录；本地 Python 脚本负责可重复的事项操作和校验。

> 当前为 `0.1.0-rc1` 公开预览版，采用 [MIT 许可证](LICENSE)，版权署名为 zhihuigu。适用边界见[许可证说明](LICENSE-STATUS.md)。本项目与 OpenAI 无隶属关系。

## 它能帮你做什么

- 保留任务的要求、截止、下一步、等待对象和版本位置。
- 查看全部在办、今天需要处理、等待反馈和近期完成的事项。
- 找回历史 CASE，区分工作稿、实际提交版和经确认的 Final。
- 用 SHA256 检查 Final 是否在确认后变化；归档后新增要求建立关联事项。
- 保留原始材料、过程版本与成果，安全地备份到新目录、恢复到另一位置。

例如，以下都是虚构场景：

> 帮我筹备“云朵书屋读书交流会”。先建立事项，下一步是拟一份议程，暂时没有截止日期。
>
> 我已经把议程 V1 改好了，以我编辑的文件为准，继续完善，先给我审阅。
>
> 这份 V2 确认为 Final，活动还没有结束，暂时留在在办。
>
> 活动结束了，这个事项可以闭环归档。

核心脚本管理的是文件和事实记录。写 Word、改 Excel、理解邮件或录音，需要你自己的 Codex 文件能力或另行接入的工具；本项目不捆绑这些工具，也不宣称已验证它们。

## 五分钟开始

要求：已能使用 Codex；本机有 Python 3.12 或以上。**本候选实际验证的平台仅为 Windows、本机 Python 3.14.6**，其他 Python 版本和 macOS/Linux 尚未验证。无需 API key、pip 包或 Git。

1. 下载并解压代码到单独文件夹，例如 `office-workbench`，打开该文件夹的终端。
2. 运行 `python --version` 确认 Python。
3. 选择一个**不存在、父目录已存在、位于代码目录之外且不在 Git 仓库内**的私人目录。下面 PowerShell 示例使用当前用户目录下的新文件夹：

```powershell
python -I -B .\workbench.py init --workspace "$env:USERPROFILE\MyOffice"
```

4. 在 Codex 中打开刚建立的 `MyOffice` 私人目录，新开一个本地会话，说：

> 请读取 AGENTS.md 和 LOCAL.md，运行 python -I -B office.py doctor，确认这是一个新工作台，然后告诉我怎么交代第一件事。不要创建示例任务。

5. 说出你的第一项任务。具体操作见[初始化指南](docs/quickstart.md)和[日常对话手册](docs/daily-use.md)。

```text
你的某个父目录/
├─ office-workbench/     # 可公开的代码；日常材料不放这里
└─ MyOffice/             # 私人工作目录；在 Codex 打开这里
   ├─ AGENTS.md、LOCAL.md、office.py
   ├─ ACTIVE/、ARCHIVE/、SERIES/、KNOWLEDGE/
   ├─ INBOX/、INDEX/、DERIVED/、工作看板.md
   └─ .office-system/    # 已安装的独立运行时与手册
```

只需保留 MyOffice 全目录，日常运行不再依赖代码仓库原来的位置。初始化不会导入任何现有材料，不会覆盖现有目录、调整 Codex 权限、复制登录状态或设置全局配置。

## 阅读路线

| 我想知道 | 文档 |
|---|---|
| 初始化、选择目录、第一轮自检 | [快速开始](docs/quickstart.md) |
| 平时怎么对 Codex 说话 | [日常使用](docs/daily-use.md) |
| 状态、文件版本、手工修改、历史找回 | [任务与文件](docs/files-and-history.md) |
| 备份、迁移、升级、故障处理 | [维护手册](docs/maintenance.md) |
| 私隐、权限和网络边界 | [隐私说明](docs/privacy.md) |
| 邮件、钉钉、Office 等可选接入 | [接入边界](docs/integrations.md) |
| 查看参数、退出码和检索协议 | [命令参考](docs/commands.md) |
| 实现、验证范围和限制 | [架构](docs/architecture.md)、[支持范围](SUPPORT.md) |
| 从零体验完整虚构流程 | [文字演示](demo/README.md) |
| 授权和准备发布 | [第三方审查](THIRD_PARTY.md)、[发布说明](docs/publishing.md) |

私人数据保存在你的文件目录里，**这不等于 Codex 推理完全离线**。本地脚本不访问网络；Codex 和你配置的连接器遵循各自的数据与权限设置。开始放入材料前请阅读[隐私说明](docs/privacy.md)。

# 开始使用

在能读取项目文件、运行本地命令的 AI Agent 中打开本目录，并开启一个以本目录为当前工作目录的新会话。
如果 Agent 支持 `AGENTS.md`，可以直接对它说：

> 请读取本目录 AGENTS.md 和 LOCAL.md，运行 python -I -B office.py doctor，然后告诉我当前在办事项。如果目录为空，不要创建演示事项。

如果 Agent 不自动识别 `AGENTS.md`，请按该产品的项目规则机制引用这份文件，或在会话开始时明确要求读取。需要的 Skill / MCP 按对应 Agent 的方式安装和授权，本工作台不复制登录信息或全局配置。

终端自检：`python -I -B office.py doctor`。查看手册：`python -I -B office.py guide`。
本目录保存私人材料，禁止上传公开仓库。代码仓库可以删除或移动，本目录仍可独立运行。

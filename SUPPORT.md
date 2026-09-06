# 支持与验证范围

当前候选：0.1.0-rc1。

软件最低检查为 Python 3.12；本次实际执行环境为 Windows、Python 3.14.6、PowerShell、本地磁盘。其他 Python 版本、Windows 版本组合、Linux、macOS、网络盘和多机协作没有完成运行验证，不宣称支持。

提供公开测试代码，输入全部运行时虚构生成；测试结果、机器信息、日志和截图不打入发布包。安装者可自行运行：

```powershell
python -I -B tests/run.py
python -I -B tools/release.py check
```

本地隔离测试验证脚本，不等于全新电脑的 Codex 会话或登录已经验收。请完成快速开始的会话自检。GitHub Actions 未执行，不提供 CI 已通过徽章。

不支持自动生成 Office、附件全文搜索、邮件收发、钉钉联网、团队审批、计划任务、后台通知、自动恢复任意损坏、全局配置同步、自动 schema 迁移或恶意文件隔离。

反馈问题请提供虚构复现步骤、命令、版本和错误类型。不要在公共 Issue 上传真实 CASE、工作目录、日志、附件、截图或凭据。见 SECURITY.md。

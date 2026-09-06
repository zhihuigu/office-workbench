# 实现与范围

## 轻量形态

项目采用 Python 标准库、Markdown、少量 JSON。未引入 Web 服务、数据库、后台任务、插件商店、向量检索或自建模型 API 层。

`engine/caseboard.py` 负责 CASE 生命周期、视图和命令；`safety.py` 负责边界路径、单机锁、原子写和补偿恢复；`retrieval.py` 负责按用途搜索与只读上下文。这三个模块从文件工作台的通用实现整理而来，保留有用机制，去掉私人安装布局与特定 Agent 诊断。

## 私人安装

`workbench.py init` 从明确文件列表装入新目录。`.office-system/releases/<版本-内容摘要>/` 内放运行时、模板和该版手册，`.office-workbench.json` 保存格式、相对版本标记与各文件哈希。根 office.py 检查安装完整性，显式传入自身私人目录，拒绝用户传另一个 root。

所有运行时文件为独立副本，不链接到源码。root、父路径和控制文件链接有防误用检查；这不是抵御恶意本地竞态的操作系统沙箱。核心无网络或登录依赖。Codex 的规则入口是根 AGENTS.md，补充偏好在 LOCAL.md，无全局 Skill 或固定模型要求。

## 权威、事务、检索

唯一业务事实源是 CASE.md。看板、INDEX、上下文都是派生文件；安装标记只记录软件状态，事务日志只为恢复，均不是另一份业务任务库。

生命周期操作先做合法性和指纹检查，写时加锁并保存补偿记录。文件材料正文由外部工具处理，不受本工具锁约束。历史搜索先匹配任务，再按明确用途选版本；缺少目的版本不回退猜测。

上下文默认 stdout；显式保存放在私人目录 DERIVED，随完整备份迁移。源引文保持引用性质，不获得指令权限。

## 验证层次

源码提供在临时目录生成虚构内容的自动化测试，不保存真实样本、历史日志、截图或测试输出。测试入口为 `python -I -B tests/run.py`。

发布检查为 `python -I -B tools/release.py check`，使用 `PUBLIC_FILES.txt` 明确白名单。打包为 `python -I -B tools/release.py pack --output 外部新zip路径`。发布检查覆盖文件类别、链接和常见泄露模式，不代替人工审阅或授权确认。

支持范围见 SUPPORT.md。开发者测试与本地 clean venv 验证不代表已经测试远端 GitHub Actions、不同电脑的 Codex 登录或连接器；不提供这样的承诺。

# 使用 AI 辅助开发

MaaSVWB 将 MaaFramework Skill 和 MaaMCP 作为可选开发工具。它们不会进入桌面前端、
发布包或用户运行依赖。

## MaaFramework Skill

[maaframework-skills](https://github.com/Kutius/maaframework-skills) 将 MaaFramework v5
文档整理成适合 AI 按需读取的 Pipeline、识别算法、动作、Controller、Agent 和排错参考。
项目在 `tools/ai-tools.lock.json` 中固定其上游 commit，避免不同开发者获得不同内容。

在 PowerShell 中运行：

```powershell
powershell -ExecutionPolicy Bypass -File .\tools\setup_ai_dev.ps1
```

脚本会把 Skill 下载到 `.agents/skills/maaframework/`。该目录采用跨客户端的项目级
Agent Skills 约定；下载内容不提交到仓库，来源和版本锁定文件会提交。

需要切换到锁定文件中的新 commit 时，先修改 `tools/ai-tools.lock.json`，再运行：

```powershell
powershell -ExecutionPolicy Bypass -File .\tools\setup_ai_dev.ps1 -Force
```

更新后必须执行 `tools/test.ps1` 和 `npx @nekosu/maa-tools check`。Skill 是辅助资料，
项目当前使用的 MaaFramework schema 和实际检查结果优先级更高。

## MaaMCP 的作用

[MaaMCP](https://github.com/MAA-AI/MaaMCP) 把 MaaFramework 的设备发现、ADB 连接、
OCR、截图、点击、滑动以及 Pipeline 加载和运行能力暴露为 MCP 工具。它适合以下开发场景：

- 让 AI 直接观察模拟器并定位教程遮罩、按钮和列表条目；
- 重现滚动惯性、动画等待和分辨率映射问题；
- 用 OCR 或截图辅助确定识别区域和模板；
- 在写入正式 Pipeline 前探索交互流程，并运行 Pipeline 做现场验证。

它不替代 MaaSVWB 的语义解法引擎。探索时可以使用坐标点击，但正式解法仍应使用
`play_card`、`attack`、`select_target` 等序号化动作。MaaMCP 也不应参与 GUI 正常运行、
CI 或发布构建。

MaaMCP 会给 AI 实际控制设备或窗口的能力。只连接明确授权的模拟器，不要连接包含隐私
内容的桌面窗口；启用后台流水线后，任务结束必须停止。项目固定 MaaMCP 版本，但默认不安装。

需要它时运行：

```powershell
powershell -ExecutionPolicy Bypass -File .\tools\setup_ai_dev.ps1 -WithMaaMcp
```

MaaMCP 会安装到独立的 `.ai-tools/maa-mcp/` 虚拟环境，避免与 MaaSVWB 的 `.venv`
及 `maafw` 版本相互覆盖。MCP 客户端可以使用以下 stdio 配置；若客户端不以项目根目录
为工作目录，请把脚本路径改为绝对路径：

```json
{
    "mcpServers": {
        "MaaMCP": {
            "command": "powershell",
            "args": [
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                "tools/run_maa_mcp.ps1"
            ]
        }
    }
}
```

MaaMCP 的 `load_pipeline` 有路径沙箱，只允许读取它自己的用户数据目录下的
`pipelines/`。不能直接把 `assets/resource/pipeline/*.json` 的项目路径传给它。安装后先运行：

```powershell
powershell -ExecutionPolicy Bypass -File .\tools\sync_maa_mcp.ps1
```

脚本会输出同步后的绝对目录；将该目录内的 JSON 路径交给 `load_pipeline`。同步内容只是
开发副本，正式修改仍必须写回 `assets/resource/pipeline/` 并通过项目测试。

MaaMCP 使用 AGPL-3.0-or-later；本项目只把它作为隔离安装的外部开发工具，不复制其代码，
也不链接到 MaaSVWB 发布产物。

## AI 开发约定

项目级规则写在根目录 `AGENTS.md`，Claude Code 通过 `CLAUDE.md` 引用相同规则。
AI 修改 MaaFramework 资源时应读取已安装的 Skill；需要现场设备信息时才启用 MaaMCP。
无论使用何种 AI，提交前都要运行：

```powershell
.\tools\test.ps1
npx @nekosu/maa-tools check
```

# MaaSVWB

[![check](https://github.com/allenx555/MaaSVWB/actions/workflows/check.yml/badge.svg)](https://github.com/allenx555/MaaSVWB/actions/workflows/check.yml)
[![release](https://img.shields.io/github/v/release/allenx555/MaaSVWB?display_name=tag)](https://github.com/allenx555/MaaSVWB/releases)

《影之诗：超凡世界》安卓模拟器自动操作工具，基于
[MaaFramework](https://github.com/MaaXYZ/MaaFramework) 和 Avalonia 开发。

MaaSVWB 通过 OCR 定位游戏内的教程或盘面解密条目，再用人工录入的语义解法完成
出牌、指定目标、随从攻击、进化和护符启动等操作。解法使用“第几张手牌”“第几个
随从”等序号表达，避免把逐关坐标暴露给解法作者。

> [!IMPORTANT]
> 当前所有识别和操作均以横屏 `1280 × 720` 为基准。使用前必须把模拟器分辨率设置为
> `1280 × 720`；其他分辨率暂不支持。

## 当前状态

- 已完成安卓模拟器连接、列表 OCR 导航、教程遮罩跳过和语义动作框架；
- 已录入盘面解密与对战教程的完整目录，尚无脚本的条目会在 GUI 中显示为灰色；
- 当前提供 5 项可执行盘面解密：
    - 同时学习【守护】【突进】【疾驰】吧！；
    - 学习／熟练运用巴巴洛丝皇家护卫吧！；
    - 学习／熟练运用护符主教吧！；
- 语义执行器支持出牌与指定目标、随从攻击、模式选择、普通进化、超进化、护符启动、
  回合结束、能量点识别及额外能量点操作；
- 开局换牌目前支持直接确认，自动选择换牌策略尚未实现；
- “地域试炼”页签暂未开放。

## 用户使用

1. 从 [Releases](https://github.com/allenx555/MaaSVWB/releases) 下载与系统和架构匹配的 ZIP；
2. 完整解压，不要只复制 `MaaSVWB.exe`；
3. 启动安卓模拟器、开启 ADB，并将游戏切换到横屏 `1280 × 720`；
4. 运行 `MaaSVWB.exe`，在“设置”中刷新设备并测试连接；
5. 进入游戏的盘面解密或对战教程列表，再在对应页签选择任务并开始执行。

发布包已经包含 MaaFramework、Python Runner 和 .NET 运行时，普通用户不需要安装
Python、Node.js 或 .NET SDK。发布包内的 `README.md` 是独立维护的用户手册。

## 开发环境

Windows PowerShell 下执行：

```powershell
git clone git@github.com:allenx555/MaaSVWB.git
cd MaaSVWB
powershell -ExecutionPolicy Bypass -File .\tools\setup_dev.ps1
powershell -ExecutionPolicy Bypass -File .\tools\setup_gui.ps1
```

- Python 基准版本：3.12；
- MaaFramework 版本：见 `tools/project_versions.json`；
- .NET SDK：10.0，由 `setup_gui.ps1` 安装到项目内的 `.dotnet/`；
- Node.js：仅用于 Maa 配置检查，要求 20.19 或更高版本。

启动开发版 GUI：

```powershell
powershell -ExecutionPolicy Bypass -File .\tools\run_gui.ps1
```

只连接模拟器并截图，不执行点击：

```powershell
.\.venv\Scripts\python tools\run_android.py
```

在盘面解密列表中执行已录入解法：

```powershell
.\.venv\Scripts\python tools\run_android.py `
    --task puzzle `
    --solution puzzle_001 `
    --execute
```

如果自动发现设备失败，可增加 `--adb "模拟器 adb.exe 的完整路径"` 和 `--serial`。
连接与识别日志默认写入 `debug/`。

## 项目结构

```text
agent/                         Python Custom Action 与语义解法执行器
assets/
  catalog/                     GUI 展示的关卡目录、分组和前置关系
  resource/
    layouts/                   1280×720 统一语义布局
    pipeline/                  MaaFramework Pipeline 与 OCR 节点
    solutions/                 人工录入的关卡解法
  schemas/                     目录、布局和解法的项目内 Schema
gui/MaaSVWB.Desktop/           Avalonia 官方桌面前端
tests/                         解法模型、执行器和运行时测试
tools/                         环境、检查、调试和发布脚本
```

`assets/interface.base.json` 是通用 MaaFramework Project Interface 的基础配置；
`assets/interface.json` 由目录与已有解法自动生成。正式桌面前端以
`gui/MaaSVWB.Desktop` 为准，同时保留 Project Interface 供通用 Maa 客户端兼容使用。

## 添加解法

1. 参考 `docs/examples/puzzle_demo.json`，在 `assets/resource/solutions/` 新建同 ID 的 JSON；
2. 在对应的 `assets/catalog/*_catalog.json` 中加入目录项；
3. 优先使用 `play_card`、`attack`、`select_choice`、`evolve`、`activate_amulet` 和
   `end_turn` 等语义动作；
4. 运行 `python tools/generate_interface.py` 更新通用 Project Interface；
5. 执行 `tools/test.ps1`。

完整字段、导航配置和动作说明见[人工解法格式](./docs/zh_cn/solution-format.md)。

## 检查与发布

完整项目检查：

```powershell
.\tools\test.ps1
npm ci
npm run typecheck
npx @nekosu/maa-tools check
.\.dotnet\dotnet.exe build gui\MaaSVWB.Desktop\MaaSVWB.Desktop.csproj
```

生成与 GitHub Release 一致的 Windows x64 发布目录：

```powershell
.\tools\package.ps1 -Version v0.2.0 -Os win -RuntimeIdentifier win-x64
```

成品位于 `install/`。桌面前端以单文件 `MaaSVWB.exe` 发布，资源、目录和内置运行器
分别位于 `resource/`、`catalog/` 与 `runtime/`。推送 `v*` 标签后，GitHub Actions 会为
Windows、Linux 和 macOS 的 x64/ARM64 架构生成 ZIP。

贡献流程见[开发指南](./docs/zh_cn/develop/how_to_develop.md)和
[PR 规范](./docs/zh_cn/develop/pull_request_guidelines.md)。可选 AI 开发工具见
[AI 辅助开发说明](./docs/zh_cn/develop/ai-development.md)。

## 许可

MaaSVWB 使用 [MIT License](./LICENSE)。发布包中的 MaaFramework、MaaAgentBinary、
Avalonia 等第三方组件适用各自许可证，详见
[第三方许可声明](./docs/release/THIRD_PARTY_NOTICES.md)。

使用自动化工具前，请确认符合游戏服务条款并自行承担风险。

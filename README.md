<!-- markdownlint-disable -->

<div align="center">

<img alt="MaaSVWB Logo" src="./assets/icon.png" width="256" height="256" />

# MaaSVWB

<div>
  <img alt="Python" src="https://img.shields.io/badge/Python-3.12-3776AB?logo=python&amp;logoColor=white" />
  <img alt=".NET" src="https://img.shields.io/badge/.NET-10.0-512BD4?logo=dotnet&amp;logoColor=white" />
  <a href="https://github.com/allenx555/MaaSVWB/blob/main/LICENSE"><img alt="license" src="https://img.shields.io/github/license/allenx555/MaaSVWB" /></a>
</div>
<div>
  <a href="https://github.com/allenx555/MaaSVWB/releases"><img alt="release" src="https://img.shields.io/github/v/release/allenx555/MaaSVWB?display_name=tag" /></a>
  <img alt="platform" src="https://img.shields.io/badge/platform-Windows-blueviolet" />
</div>

</div>

<!-- markdownlint-restore -->

《影之诗：超凡世界》安卓模拟器自动操作工具，基于
[MaaFramework](https://github.com/MaaXYZ/MaaFramework) 和 Avalonia 开发。

MaaSVWB 通过 OCR 定位游戏内的教程、盘面解密条目和卡牌名称，再用人工录入的语义
解法或 Battle Profile 完成出牌、指定目标、随从攻击、进化和护符启动等操作。解法
使用“第几张手牌”“第几个随从”等序号表达，避免把逐关坐标暴露给解法作者。

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
- 基础战斗组件支持按 Battle Profile 交换起手；当前内置快梦策略在起手有任意 1 费牌时整手保留，否则交换全部已识别起手；
- “地城试炼”页签已经开放，首版自动对战支持：
  - 通过 OCR 卡名按 Battle Profile 的优先级使用手牌，直伤法术可指定敌方主战者；
  - 按场上随从序号攻击，识别敌方守护并优先处理，否则攻击敌方主战者；
  - 自动结束回合、处理“仍有可用卡牌”的确认弹窗，并通过能量上限增加和回满识别新回合；
- 已建立可校验的 Battle Profile 接口，支持配置卡牌使用优先级、目标、固定组合、换牌、进化和安全限制；当前内置策略针对无限制快攻梦魇牌组，暂不自动选择牌组。
  - 识别胜负结算、自动再战并按目标胜场循环；失败不计数，连续失败超过 2 次时停止；
- 记牌器支持牌组预览、地城自动战斗同步和独立只读监听。独立监听不需要 Battle Profile，可在其他对局的己方回合读取展开手牌；只有连续两次完整识别才更新，结果始终标为估计值。

## 用户使用

记牌器：在“记牌器”页粘贴完整的 40 张牌组码，点击“开始监听”，再从开局开始正常游戏。
独立模式不会点击或拖动；请在每次手牌变化后展开手牌，保持约 1–2 秒以便确认。
识别到换牌页或上一局结算后会开始新会话，换牌阶段不扣牌；识别失败会保留上次结果并提示原因。
若没有捕获到换牌或结算、切换牌组，需停止后重新开始监听。运行地城自动战斗时自动共享记牌逻辑，无需另开监听。

完整手牌与己方牌库数字连续两次一致后，会用游戏显示的总数校验记牌账本。洗回等效果造成的额外牌数会显示为“构成未知”，不会猜测具体卡名；无法解释的牌库减少也会降低单卡构成的确定性。未知条目与其余条目之和等于本次校验的牌库总数。
牌库数字识别失败时暂用手牌差分估计，完整手牌未识别时保留上次结果。截图差分不能证明卡牌来源：生成、回手、变身、同时抽牌和洗回、漏帧以及两次观察间同名牌的替换仍可能造成构成偏差，即使总数一致也不代表卡名准确。已提供确认洗回事件接口，但尚未自动识别具体卡牌效果及目标。
中途接入也不能恢复此前的抽牌历史。当前适配中文 1280×720 的手牌布局，其他玩法的结算画面仍需实机校准。
GUI 会显示“预览 / 估计剩余”、观察状态和最后更新时间；停止后保留最后结果。

开发环境也可运行 `tools/run_android.py --task tracker --execute --deck-code "牌组码"`，使用 `--adb` / `--serial` 指定设备，Ctrl+C 停止。

1. 从 [Releases](https://github.com/allenx555/MaaSVWB/releases) 下载与系统和架构匹配的 ZIP；
2. 完整解压，不要只复制 `MaaSVWB.exe`；
3. 启动安卓模拟器、开启 ADB，并将游戏切换到横屏 `1280 × 720`；
4. 运行 `MaaSVWB.exe`，在“设置”中刷新设备并测试连接；
5. 进入游戏的盘面解密、对战教程或地城试炼页面，再在对应页签选择任务并开始执行。

使用“地城试炼”前，请先在游戏中选好要使用的无限制牌组，并停在地城关卡列表。
程序不会校验牌组名称或自动切换牌组；“战斗次数”表示目标胜场，包含首次挑战，只有胜利才会计数。

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

从地城关卡列表或己方回合启动自动对战，目标完成 3 场胜利：

```powershell
.\.venv\Scripts\python tools\run_android.py `
    --task dungeon `
    --profile aggro_nightmare `
    --battle-count 3 `
    --execute
```

如果自动发现设备失败，可增加 `--adb "模拟器 adb.exe 的完整路径"` 和 `--serial`。
连接与识别日志默认写入 `debug/`。

## 项目结构

```text
agent/                         Python Custom Action 与语义解法执行器
assets/
  battle/                      卡牌注册表与内置对战策略
  catalog/                     GUI 展示的关卡目录、分组和前置关系
  resource/
    layouts/                   1280×720 统一语义布局
    pipeline/                  MaaFramework Pipeline 与 OCR 节点
    recordings/                MuMu 操作录制文件
    solutions/                 人工录入的关卡解法
  schemas/                     目录、布局和解法的项目内 Schema
gui/MaaSVWB.Desktop/           Avalonia 官方桌面前端
tests/                         解法模型、执行器和运行时测试
tools/                         环境、检查、调试和发布脚本
```

基础对战状态机位于 `agent/runtime/battle_runner.py`，负责换牌确认、能量与新回合判断、
出牌、攻击、结束回合和胜负识别。`agent/runtime/dungeon_runner.py` 只处理地城入口、
当前牌组确认和结算后的连战，并通过组合 `BattleRunner` 复用上述能力；地城连战计数与
连续失败保护单独位于 `agent/runtime/dungeon_session.py`。

`assets/interface.base.json` 是通用 MaaFramework Project Interface 的基础配置；
`assets/interface.json` 由目录与已有解法自动生成。正式桌面前端以
`gui/MaaSVWB.Desktop` 为准，同时保留 Project Interface 供通用 Maa 客户端兼容使用。

## 添加解法

盘面解密支持两种编写方式，可以按关卡任选其一：

- 语义动作：使用 `play_card`、`attack`、`select_choice`、`evolve`、
  `activate_amulet` 和 `end_turn` 等动作描述解法。它便于阅读和调整，也能在每步操作前
  重新识别实时手牌与随从位置。
- 录制回放：把 MuMu 录制的 `.mmor` 文件放入
  `assets/resource/recordings/`，建议文件名与解法 ID 一致，再通过
  `replay_mumu_script` 执行。运行时只读取每个手势的起点、终点和时序，并由
  MaaFramework 生成点击或直线拖动，不会原样重放录制中的抖动轨迹。

对战教程包含多回合等待和大量固定教学对话，推荐使用录制回放；可先用 `wait_for` 和
`wait_until_gone` 将回放起点同步到稳定提示消失后的画面。录制依赖固定分辨率和一致的
起始状态，当前项目以横屏 `1280 × 720` 为基准。

添加流程：

1. 参考 `docs/examples/puzzle_demo.json`，在 `assets/resource/solutions/` 新建与 ID 同名的 JSON；
2. 在对应的 `assets/catalog/*_catalog.json` 中加入目录项；
3. 选择语义动作，或添加 `.mmor` 录制并使用 `replay_mumu_script`；
4. 运行 `python tools/generate_interface.py` 更新通用 Project Interface；
5. 执行 `tools/test.ps1`。

完整字段、导航配置和动作说明见[人工解法格式](./docs/zh_cn/solution-format.md)。

地城试炼的卡牌优先级和决策偏好使用独立 Battle Profile，格式见
[用户对战策略 JSON](./docs/zh_cn/battle-profile.md)。该配置不接受坐标、Pipeline 节点或
任意可执行内容。运行时使用 OCR 读取展开手牌的名称，并将其映射到项目维护的卡牌
注册表；不需要为牌组中的每张卡牌制作图像模板。开发者还可以使用
`tools/import_battle_deck.py` 从外部 `SVWBData` 生成卡组限定注册表和策略草稿；完整
解包数据不会进入仓库或发布包。

## 检查与发布

完整项目检查：

```powershell
.\tools\test.ps1
npm ci
npm run typecheck
npx @nekosu/maa-tools check
.\.dotnet\dotnet.exe build gui\MaaSVWB.Desktop\MaaSVWB.Desktop.csproj
```

完整本地打包 Windows x64 版本（GUI、Agent、Runner 和资源）：

```powershell
$version = git describe --tags --always --dirty
.\tools\package.ps1 -Version $version -RuntimeIdentifier win-x64
```

成品位于 `install/`：桌面前端以单文件 `MaaSVWB.exe` 发布，
资源、目录和内置运行器分别位于 `resource/`、`catalog/`与 `runtime/`。
推送 `v*` 标签后，GitHub Actions 会为 Windows x64/ARM64 架构生成 ZIP。

贡献流程见[开发指南](./docs/zh_cn/develop/how_to_develop.md)和
[PR 规范](./docs/zh_cn/develop/pull_request_guidelines.md)。可选 AI 开发工具见
[AI 辅助开发说明](./docs/zh_cn/develop/ai-development.md)。

## 许可

MaaSVWB 使用 [MIT License](./LICENSE)。发布包中的 MaaFramework、MaaAgentBinary、
Avalonia 等第三方组件适用各自许可证，详见
[第三方许可声明](./docs/release/THIRD_PARTY_NOTICES.md)。

使用自动化工具前，请确认符合游戏服务条款并自行承担风险。

MaaSVWB 是非官方开源项目，与《影之诗：超凡世界》的开发商、发行商及运营方无关。
相关游戏名称、角色形象及美术素材的权利归原权利人所有；项目的 MIT License 不对这些
第三方内容作出授权。

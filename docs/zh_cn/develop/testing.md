# 跨模块验证

测试按实际调用链组织；策略、事件解析等单元测试继续保留。集成测试使用真实的配置加载、
策略和执行器，只替换设备、时间等外部边界。新增场景优先断言可观察的操作顺序、状态与
退出结果，避免把相邻模块的返回值全部 Mock 掉。

## 本地运行

```powershell
# 仓库必需检查：Python 测试、内容、类型、Schema，以及桌面进程集成测试
.\tools\test.ps1

# 仅检查 GUI 服务与 Python 子进程
.\tools\test_gui.ps1

# 只运行对应 Python 集成测试
.\.venv\Scripts\python -m unittest discover -s tests -p test_battle_integration.py -v
.\.venv\Scripts\python -m unittest discover -s tests -p test_stop_integration.py -v
```

`test_gui.ps1` 使用项目内 .NET；未安装时使用系统 `dotnet`。它运行无界面的控制台测试
程序，任何失败都返回非零退出码。测试子进程使用真实 `run_android.parse_args` 与
`runtime.events`，不连接设备，也不加载用户设置。

## 验证范围

| 链路                                                  | 验证内容                                                                                                              | 文件                                                          |
| ----------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------- |
| Profile → Policy → BattleRunner → 有状态设备替身      | 固定组合不被单卡插入、实时手牌序号、重复卡牌、目标覆盖、条件失效与安全限制                                            | `tests/test_battle_integration.py`                            |
| 停止文件 → Monitor → Tasker → MaaBackend → Controller | 提前停止不提交任务；运行中接受停止后不继续排入点击、拖动或按键                                                        | `tests/test_run_android.py`、`tests/test_stop_integration.py` |
| AutomationService → 真实 Python 子进程 → 事件解析     | 含空格及中文的参数、UTF-8 事件、末行输出、错误事件、非零退出、优雅停止、强制终止、取消、Dispose、并发运行、失败后重试 | `gui/MaaSVWB.Desktop.IntegrationTests/`                       |
| 最终 ZIP → 解压 → Runner/Agent                        | ZIP 内容和执行权限、独立工作目录启动、无开发环境变量、原生库与资源加载                                                | `tools/smoke_release.py`                                      |

桌面进程测试会启动受控子进程及其后代，检查停止后是否退出。Windows 虚拟环境有额外
Python 启动进程，因此需要覆盖至少两层后代。强制终止等待沿用产品的 8 秒宽限期。

## 发布包验证

```powershell
python tools/archive_release.py --source install --output build/release/local.zip --os win
python tools/smoke_release.py --archive build/release/local.zip --os win
```

`--os` 可选 `win`、`linux`、`macos`，必须在与包匹配的平台上运行冒烟测试。
发布流水线先复用完整检查工作流，通过后才构建。构建完成后先上传 ZIP，再下载同一
Artifact，解压到独立临时目录；只有冒烟通过后，构建
job 才成功，发布 job 才能继续。不会修改 GitHub 上已有的发布包。

两个程序均支持 `--self-check`，运行过程中不发现设备、不连接模拟器、不发出输入。
Runner 检查模型文件、布局、卡牌、策略、解法、目录及 Interface，并由真实 MaaFramework
加载资源、注册动作；Agent 检查相同静态资源，并加载自己的原生服务库。Agent 的检查
不启动 socket 服务，不代表客户端与 Agent 的通信已验证。

CI 的普通检查在 Windows、Linux、macOS 上运行桌面进程测试；发布流水线在每个构建
平台和架构上运行最终归档冒烟。Python 对原生 Unix 权限的测试在 Windows 上明确跳过。

## 授权实机验收

无设备测试不能证明 OCR、坐标、动画等待或游戏内结算正确。涉及这些变化时，在用户
指定并授权的设备上执行对应流程；不将未执行项标记为通过。

1. 记录 commit、包版本、设备、游戏语言和 1280×720 分辨率。
2. 从列表执行一项相关盘面解法或教程，确认定位、操作和返回列表。
3. 若改动涉及地城，使用确认的牌组，覆盖换牌、目标选择、攻击和至少一次结算。
4. 在连接中及运行中分别停止一次，确认日志、界面状态和设备均停止操作；关闭 GUI
   后确认没有该次运行的 Runner 残留。
5. 若改动涉及记牌，展开手牌并等待确认，核对估计值、状态，以及停止后保留的结果。
6. 保存相关日志和必要截图，记录每项的预期、实际结果及未覆盖边界。

每次只运行与改动相关的流程；发布前按发布范围补齐验收。构建成功、退出码 0 或
`--self-check` 成功都不替代这些实机结果。

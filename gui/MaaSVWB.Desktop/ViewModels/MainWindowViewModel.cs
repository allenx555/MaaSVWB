using System.Collections.ObjectModel;
using Avalonia.Threading;
using MaaSVWB.Desktop.Models;
using MaaSVWB.Desktop.Services;

namespace MaaSVWB.Desktop.ViewModels;

public sealed class MainWindowViewModel : ViewModelBase, IDisposable
{
    private readonly AutomationService _automation = new();
    private string _projectRoot;
    private string _pythonPath;
    private string _adbPath;
    private string _deviceSerial;
    private bool _saveDraw;
    private int _dungeonBattleCount;
    private string _logText = string.Empty;
    private string _statusText = "准备就绪";
    private bool _isBusy;

    public MainWindowViewModel()
    {
        var settings = SettingsStore.Load();
        _projectRoot = settings.ProjectRoot;
        _pythonPath = settings.PythonPath;
        _adbPath = settings.AdbPath;
        _deviceSerial = settings.DeviceSerial;
        _saveDraw = settings.SaveDraw;
        _dungeonBattleCount = Math.Clamp(settings.DungeonBattleCount, 1, 99);

        RefreshDevicesCommand = new AsyncCommand(RefreshDevicesAsync, () => !IsBusy);
        TestConnectionCommand = new AsyncCommand(TestConnectionAsync, () => !IsBusy);
        DungeonRunCommand = new AsyncCommand(RunDungeonAsync, () => !IsBusy);
        StopCommand = new RelayCommand(Stop, () => IsBusy);
        SaveSettingsCommand = new RelayCommand(SaveSettings);
        ClearLogCommand = new RelayCommand(() => LogText = string.Empty);

        Puzzle = new TaskTabViewModel(
            this,
            new TaskDefinition(
                "盘面解密",
                "从列表定位指定关卡，并按人工录入的固定解法自动操作。",
                "启动前请把模拟器设为 1280×720 横屏并停在盘面解密列表。程序会识别分类、关卡名称和决定按钮，然后进入盘面执行解法。",
                "puzzle",
                "选择类别",
                "选择具体解密",
                "解密",
                [
                    new TaskRunMode("all_incomplete", "自动完成所有未完成的解密"),
                    new TaskRunMode("specific", "选择盘面解密"),
                ]),
            SolutionCatalog.Load(ProjectRoot, "puzzle"));
        Tutorial = new TaskTabViewModel(
            this,
            new TaskDefinition(
                "对战教程",
                "识别教程对话、说明弹窗和可操作状态，自动完成已录入流程。",
                "启动前请把模拟器设为 1280×720 横屏并进入对应教程。程序会在内部跳过对话和说明弹窗，识别可操作状态后继续执行。",
                "tutorial",
                "选择系列 / 分类",
                "选择具体教程",
                "教程",
                [
                    new TaskRunMode("all_incomplete", "自动完成所有未完成的教程"),
                    new TaskRunMode("specific", "选择对战教程"),
                ]),
            SolutionCatalog.Load(ProjectRoot, "tutorial"));

        AppendLog($"MaaSVWB 前端已启动，项目目录：{ProjectRoot}");
        _ = RefreshDevicesAsync();
    }

    public TaskTabViewModel Puzzle { get; }

    public TaskTabViewModel Tutorial { get; }

    public ObservableCollection<string> Devices { get; } = [];

    public string ProjectRoot
    {
        get => _projectRoot;
        set => SetProperty(ref _projectRoot, value);
    }

    public string PythonPath
    {
        get => _pythonPath;
        set => SetProperty(ref _pythonPath, value);
    }

    public string AdbPath
    {
        get => _adbPath;
        set => SetProperty(ref _adbPath, value);
    }

    public string DeviceSerial
    {
        get => _deviceSerial;
        set => SetProperty(ref _deviceSerial, value ?? string.Empty);
    }

    public bool SaveDraw
    {
        get => _saveDraw;
        set => SetProperty(ref _saveDraw, value);
    }

    public int DungeonBattleCount
    {
        get => _dungeonBattleCount;
        set
        {
            var normalized = Math.Clamp(value, 1, 99);
            if (SetProperty(ref _dungeonBattleCount, normalized))
            {
                OnPropertyChanged(nameof(DungeonBattleCountText));
            }
        }
    }

    public string DungeonBattleCountText =>
        $"目标完成 {DungeonBattleCount} 场胜利；失败不会计入战斗次数";

    public string LogText
    {
        get => _logText;
        private set => SetProperty(ref _logText, value);
    }

    public string StatusText
    {
        get => _statusText;
        private set => SetProperty(ref _statusText, value);
    }

    public bool IsBusy
    {
        get => _isBusy;
        private set
        {
            if (SetProperty(ref _isBusy, value))
            {
                RefreshDevicesCommand.RaiseCanExecuteChanged();
                TestConnectionCommand.RaiseCanExecuteChanged();
                DungeonRunCommand.RaiseCanExecuteChanged();
                StopCommand.RaiseCanExecuteChanged();
            }
        }
    }

    public AsyncCommand RefreshDevicesCommand { get; }

    public AsyncCommand TestConnectionCommand { get; }

    public AsyncCommand DungeonRunCommand { get; }

    public RelayCommand StopCommand { get; }

    public RelayCommand SaveSettingsCommand { get; }

    public RelayCommand ClearLogCommand { get; }

    public async Task<bool> RunTaskAsync(
        string category,
        string solutionId,
        string displayName,
        bool skipCompleted = false)
    {
        SaveSettings();
        return await RunAutomationAsync(
            category,
            solutionId,
            displayName,
            execute: true,
            skipCompleted);
    }

    public async Task RunBatchAsync(
        IEnumerable<SolutionItem> solutions,
        string batchNoun)
    {
        var configured = solutions.Where(solution => solution.HasScript).ToArray();
        if (configured.Length == 0)
        {
            StatusText = $"没有已配置的{batchNoun}";
            AppendLog($"当前没有可检查的{batchNoun}配置。");
            return;
        }

        AppendLog($"准备依次检查 {configured.Length} 个{batchNoun}；游戏内已完成的项目会自动跳过。");
        for (var index = 0; index < configured.Length; index++)
        {
            var solution = configured[index];
            AppendLog($"[批量 {index + 1}/{configured.Length}] {solution.Name}");
            if (!await RunTaskAsync(
                    solution.Category,
                    solution.Id,
                    solution.Name,
                    skipCompleted: true))
            {
                AppendLog($"批量任务已因当前{batchNoun}失败或被停止而结束。");
                return;
            }
        }
        StatusText = $"所有未完成{batchNoun}均已执行";
        AppendLog("批量任务执行完成。");
    }

    private async Task RefreshDevicesAsync()
    {
        try
        {
            StatusText = "正在查找模拟器…";
            var devices = await AdbService.FindDevicesAsync(AdbPath);
            Devices.Clear();
            foreach (var device in devices)
            {
                Devices.Add(device);
            }
            if (devices.Count > 0)
            {
                var selectedDevice = devices.FirstOrDefault(device =>
                    string.Equals(device, DeviceSerial, StringComparison.OrdinalIgnoreCase))
                    ?? devices[0];
                // ComboBox 的 SelectedItem 需要集合内的字符串实例；即使内容相同也要通知绑定刷新。
                _deviceSerial = selectedDevice;
                OnPropertyChanged(nameof(DeviceSerial));
            }
            StatusText = devices.Count == 0 ? "未发现设备" : $"已发现 {devices.Count} 台设备";
            AppendLog(devices.Count == 0
                ? "未发现处于 device 状态的 ADB 设备。"
                : $"发现设备：{string.Join(", ", devices)}");
        }
        catch (Exception exception)
        {
            StatusText = "设备发现失败";
            AppendLog($"[错误] {exception.Message}");
        }
    }

    private async Task TestConnectionAsync()
    {
        SaveSettings();
        var solution = Puzzle.SelectedSolution ?? Tutorial.SelectedSolution;
        if (solution is null)
        {
            AppendLog("[错误] 没有可用于连接测试的解法配置。");
            return;
        }
        await RunAutomationAsync(
            solution.Category,
            solution.Id,
            "连接与截图测试",
            execute: false,
            skipCompleted: false);
    }

    private async Task<bool> RunAutomationAsync(
        string category,
        string solutionId,
        string displayName,
        bool execute,
        bool skipCompleted,
        int battleCount = 1)
    {
        if (IsBusy)
        {
            return false;
        }

        IsBusy = true;
        StatusText = execute ? $"正在执行：{displayName}" : "正在测试连接";
        AppendLog(string.Empty);
        AppendLog($"[{DateTime.Now:HH:mm:ss}] {(execute ? "开始任务" : "连接测试")}：{displayName}");
        try
        {
            var exitCode = await _automation.RunAsync(
                ProjectRoot,
                PythonPath,
                AdbPath,
                DeviceSerial,
                category,
                solutionId,
                execute,
                skipCompleted,
                SaveDraw,
                AppendLog,
                battleCount);
            if (_automation.WasStopped || exitCode == 130)
            {
                StatusText = "任务已停止";
                AppendLog("任务已停止。");
                return false;
            }
            StatusText = exitCode == 0 ? "执行完成" : $"执行失败（退出码 {exitCode}）";
            AppendLog(exitCode == 0 ? "任务正常结束。" : $"[错误] 进程退出码：{exitCode}");
            return exitCode == 0;
        }
        catch (Exception exception)
        {
            StatusText = "执行失败";
            AppendLog($"[错误] {exception.Message}");
            return false;
        }
        finally
        {
            IsBusy = false;
        }
    }

    private async Task RunDungeonAsync()
    {
        SaveSettings();
        await RunAutomationAsync(
            "dungeon",
            "aggro_nightmare",
            $"地城试炼（目标 {DungeonBattleCount} 场胜利）",
            execute: true,
            skipCompleted: false,
            battleCount: DungeonBattleCount);
    }

    private void Stop()
    {
        _automation.Stop();
        StatusText = "正在停止…";
        AppendLog("已请求停止当前任务。");
    }

    private void SaveSettings()
    {
        SettingsStore.Save(new FrontendSettings
        {
            ProjectRoot = ProjectRoot,
            PythonPath = PythonPath,
            AdbPath = AdbPath,
            DeviceSerial = DeviceSerial,
            SaveDraw = SaveDraw,
            DungeonBattleCount = DungeonBattleCount,
        });
        StatusText = "设置已保存";
    }

    private void AppendLog(string line)
    {
        Dispatcher.UIThread.Post(() =>
        {
            LogText += string.IsNullOrEmpty(line) ? Environment.NewLine : line + Environment.NewLine;
        });
    }

    public void Dispose() => _automation.Dispose();
}

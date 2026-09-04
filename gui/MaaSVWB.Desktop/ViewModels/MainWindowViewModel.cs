using System.Collections.ObjectModel;
using System.IO;
using System.Linq;
using System.Text.Json;
using System.Text.RegularExpressions;
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
    private int _ownDeckTotal;
    private string _trackerDeckCode;
    private string _trackerParseStatus = string.Empty;

    public MainWindowViewModel()
    {
        var settings = SettingsStore.Load();
        _projectRoot = settings.ProjectRoot;
        _pythonPath = settings.PythonPath;
        _adbPath = settings.AdbPath;
        _deviceSerial = settings.DeviceSerial;
        _saveDraw = settings.SaveDraw;
        _dungeonBattleCount = Math.Clamp(settings.DungeonBattleCount, 1, 99);
        _trackerDeckCode = settings.TrackerDeckCode;

        RefreshDevicesCommand = new AsyncCommand(RefreshDevicesAsync, () => !IsBusy);
        TestConnectionCommand = new AsyncCommand(TestConnectionAsync, () => !IsBusy);
        DungeonRunCommand = new AsyncCommand(RunDungeonAsync, () => !IsBusy);
        StopCommand = new RelayCommand(Stop, () => IsBusy);
        SaveSettingsCommand = new RelayCommand(SaveSettings);
        ClearLogCommand = new RelayCommand(() => LogText = string.Empty);
        ParseDeckCodeCommand = new RelayCommand(RebuildInitialTracker);

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
        _automation.TrackerUpdated += OnTrackerUpdated;
        RebuildInitialTracker();
        _ = RefreshDevicesAsync();
    }

    public TaskTabViewModel Puzzle { get; }

    public TaskTabViewModel Tutorial { get; }

    public ObservableCollection<string> Devices { get; } = [];

    public ObservableCollection<TrackerEntry> OwnDeckEntries { get; } = [];

    public int OwnDeckTotal
    {
        get => _ownDeckTotal;
        private set => SetProperty(ref _ownDeckTotal, value);
    }

    public string TrackerParseStatus
    {
        get => _trackerParseStatus;
        private set => SetProperty(ref _trackerParseStatus, value);
    }

    public string TrackerDeckCode
    {
        get => _trackerDeckCode;
        set
        {
            if (SetProperty(ref _trackerDeckCode, value ?? string.Empty))
                RebuildInitialTracker();
        }
    }

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

    public string DungeonRecommendedDeckCode =>
        "2.5.e3ls.e3ls.e3ls.d6jm.d6jm.d6jm.fPCm.fPCm.fPCm.eSAM.eSAM.eSAM." +
        "cLuw.cLuw.eeNc.eeNc.eeNc.f0oG.f0oG.f0oG.fPCw.fPCw.fPCw.fnd6.fnd6." +
        "fnd6.fndG.fndG.fndG.ckrU.ckrU.ckrU.eGFs.eGFs.eGFs.ckJ6.ckJ6.ckoq." +
        "d7D0.d7D0";

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

    public RelayCommand ParseDeckCodeCommand { get; }

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

        OwnDeckEntries.Clear();
        OwnDeckTotal = 0;
        RebuildInitialTracker();
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
                battleCount,
                deckCode: string.IsNullOrWhiteSpace(TrackerDeckCode) ? null : TrackerDeckCode);
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
            TrackerDeckCode = TrackerDeckCode,
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

    private static readonly Regex DeckCodePattern =
        new(@"\d+\.\d+(?:\.[A-Za-z0-9-]+)+", RegexOptions.Compiled);

    private static string? ExtractDeckCode(string raw)
    {
        var m = DeckCodePattern.Match(raw);
        return m.Success ? m.Value : null;
    }

    // The card catalog ships in two layouts: the dev tree keeps it under
    // assets/battle/, while the packaged install/ places it directly under
    // battle/ (see tools/install.py). Also fall back to the app directory so
    // the tracker works even if ProjectRoot is unset or points elsewhere.
    private string? ResolveCatalogPath(string? root)
    {
        var roots = new[] { root, AppContext.BaseDirectory };
        foreach (var baseDir in roots)
        {
            if (string.IsNullOrWhiteSpace(baseDir))
                continue;
            var packaged = Path.Combine(baseDir, "battle", "card_catalog.json");
            if (File.Exists(packaged))
                return packaged;
            var dev = Path.Combine(baseDir, "assets", "battle", "card_catalog.json");
            if (File.Exists(dev))
                return dev;
        }
        return null;
    }

    private void RebuildInitialTracker()
    {
        var code = _trackerDeckCode;
        var root = _projectRoot;
        if (string.IsNullOrWhiteSpace(code))
        {
            Dispatcher.UIThread.Post(() => { OwnDeckEntries.Clear(); OwnDeckTotal = 0; TrackerParseStatus = string.Empty; });
            return;
        }
        var canonical = ExtractDeckCode(code);
        if (canonical is null)
        {
            Dispatcher.UIThread.Post(() => { OwnDeckEntries.Clear(); OwnDeckTotal = 0; TrackerParseStatus = "未检测到有效牌组码"; });
            return;
        }
        try
        {
            // The catalog only maps short IDs to display names; parsing works without
            // it (falling back to the raw short ID), so a missing file is non-fatal.
            var codeToName = new Dictionary<string, string>();
            var catalogPath = ResolveCatalogPath(root);
            var catalogFound = catalogPath is not null;
            if (catalogFound)
            {
                using var stream = File.OpenRead(catalogPath!);
                using var doc = JsonDocument.Parse(stream);
                if (doc.RootElement.TryGetProperty("cards", out var cardsEl))
                {
                    foreach (var card in cardsEl.EnumerateArray())
                    {
                        if (card.TryGetProperty("deck_code_id", out var cid) &&
                            card.TryGetProperty("name", out var nm))
                        {
                            var shortId = cid.GetString();
                            var name = nm.GetString();
                            if (shortId != null && name != null)
                                codeToName[shortId] = name;
                        }
                    }
                }
            }
            var parts = canonical.Split('.');
            var start = parts.Length >= 2
                && int.TryParse(parts[0], out _)
                && int.TryParse(parts[1], out _) ? 2 : 0;
            var counts = new Dictionary<string, int>();
            for (var i = start; i < parts.Length; i++)
            {
                var shortId = parts[i];
                if (string.IsNullOrEmpty(shortId)) continue;
                var display = codeToName.TryGetValue(shortId, out var n) ? n : shortId;
                counts[display] = counts.TryGetValue(display, out var c) ? c + 1 : 1;
            }
            var entries = counts
                .OrderBy(kv => kv.Key)
                .Select(kv => new TrackerEntry(kv.Key, kv.Value))
                .ToList();
            var total = entries.Sum(e => e.Count);
            var kinds = entries.Count;
            var status = catalogFound
                ? $"已解析 {total} 张牌 / {kinds} 种"
                : $"已解析 {total} 张牌 / {kinds} 种（未找到卡牌数据，仅显示牌组码）";
            Dispatcher.UIThread.Post(() =>
            {
                OwnDeckEntries.Clear();
                foreach (var entry in entries)
                    OwnDeckEntries.Add(entry);
                OwnDeckTotal = total;
                TrackerParseStatus = status;
            });
        }
        catch
        {
            Dispatcher.UIThread.Post(() => TrackerParseStatus = "解析出错，请检查牌组码格式");
        }
    }

    private void OnTrackerUpdated(object? sender, TrackerSnapshot snapshot)
    {
        Dispatcher.UIThread.Post(() =>
        {
            OwnDeckEntries.Clear();
            foreach (var entry in snapshot.Entries)
            {
                OwnDeckEntries.Add(entry);
            }
            OwnDeckTotal = snapshot.Total;
        });
    }

    public void Dispose()
    {
        _automation.TrackerUpdated -= OnTrackerUpdated;
        _automation.Dispose();
    }
}

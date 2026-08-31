using System.Diagnostics;
using System.Text;
using System.Text.Json;

namespace MaaSVWB.Desktop.Services;

public sealed class AutomationService : IDisposable
{
    private readonly object _gate = new();
    private Process? _process;
    private string? _stopFile;
    private bool _stopRequested;

    public bool WasStopped
    {
        get
        {
            lock (_gate)
            {
                return _stopRequested;
            }
        }
    }

    public bool IsRunning
    {
        get
        {
            lock (_gate)
            {
                return _process is { HasExited: false };
            }
        }
    }

    public async Task<int> RunAsync(
        string projectRoot,
        string pythonPath,
        string adbPath,
        string deviceSerial,
        string category,
        string solutionId,
        bool execute,
        bool skipCompleted,
        bool saveDraw,
        Action<string> onOutput,
        int battleCount = 1,
        CancellationToken cancellationToken = default)
    {
        lock (_gate)
        {
            if (_process is { HasExited: false })
            {
                throw new InvalidOperationException("已有任务正在运行。");
            }
        }

        var bundledRunner = string.Equals(
            Path.GetFileNameWithoutExtension(pythonPath),
            "MaaSVWB.Runner",
            StringComparison.OrdinalIgnoreCase);
        var scriptPath = Path.Combine(projectRoot, "tools", "run_android.py");
        if (!bundledRunner && !File.Exists(scriptPath))
        {
            throw new FileNotFoundException("找不到 tools/run_android.py。", scriptPath);
        }
        var stopFile = Path.Combine(Path.GetTempPath(), $"maasvwb-{Guid.NewGuid():N}.stop");

        var startInfo = new ProcessStartInfo
        {
            FileName = pythonPath,
            WorkingDirectory = projectRoot,
            UseShellExecute = false,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            StandardOutputEncoding = Encoding.UTF8,
            StandardErrorEncoding = Encoding.UTF8,
            CreateNoWindow = true,
        };
        startInfo.Environment["PYTHONUTF8"] = "1";
        startInfo.Environment["PYTHONIOENCODING"] = "utf-8";
        startInfo.Environment["MAASVWB_ROOT"] = Path.GetFullPath(projectRoot);
        if (!bundledRunner)
        {
            startInfo.ArgumentList.Add(scriptPath);
        }
        if (!string.IsNullOrWhiteSpace(adbPath))
        {
            startInfo.ArgumentList.Add("--adb");
            startInfo.ArgumentList.Add(adbPath);
        }
        if (!string.IsNullOrWhiteSpace(deviceSerial))
        {
            startInfo.ArgumentList.Add("--serial");
            startInfo.ArgumentList.Add(deviceSerial);
        }
        startInfo.ArgumentList.Add("--task");
        startInfo.ArgumentList.Add(category);
        if (string.Equals(category, "dungeon", StringComparison.OrdinalIgnoreCase))
        {
            startInfo.ArgumentList.Add("--profile");
            startInfo.ArgumentList.Add(solutionId);
            startInfo.ArgumentList.Add("--battle-count");
            startInfo.ArgumentList.Add(battleCount.ToString(System.Globalization.CultureInfo.InvariantCulture));
        }
        else
        {
            startInfo.ArgumentList.Add("--solution");
            startInfo.ArgumentList.Add(solutionId);
        }
        if (execute)
        {
            startInfo.ArgumentList.Add("--execute");
        }
        if (skipCompleted)
        {
            startInfo.ArgumentList.Add("--skip-completed");
        }
        if (saveDraw)
        {
            startInfo.ArgumentList.Add("--save-draw");
        }
        if (execute)
        {
            startInfo.ArgumentList.Add("--stop-file");
            startInfo.ArgumentList.Add(stopFile);
        }

        var process = new Process { StartInfo = startInfo, EnableRaisingEvents = true };
        process.OutputDataReceived += (_, args) =>
        {
            if (args.Data is not null)
            {
                onOutput(FormatOutputLine(args.Data));
            }
        };
        process.ErrorDataReceived += (_, args) =>
        {
            if (args.Data is not null)
            {
                onOutput($"[错误] {args.Data}");
            }
        };

        lock (_gate)
        {
            _process = process;
            _stopFile = execute ? stopFile : null;
            _stopRequested = false;
        }

        try
        {
            if (!process.Start())
            {
                throw new InvalidOperationException("无法启动自动化进程。");
            }
            process.BeginOutputReadLine();
            process.BeginErrorReadLine();
            await process.WaitForExitAsync(cancellationToken);
            await Task.WhenAll(process.WaitForExitAsync(), Task.Delay(80, CancellationToken.None));
            return process.ExitCode;
        }
        finally
        {
            lock (_gate)
            {
                if (ReferenceEquals(_process, process))
                {
                    _process = null;
                    _stopFile = null;
                }
            }
            process.Dispose();
            try
            {
                if (File.Exists(stopFile))
                {
                    File.Delete(stopFile);
                }
            }
            catch (IOException)
            {
                // A stale stop marker is harmless and uses a unique temporary name.
            }
            catch (UnauthorizedAccessException)
            {
                // Do not replace the automation result with a cleanup failure.
            }
        }
    }

    public void Stop()
    {
        Process? process;
        string? stopFile;
        lock (_gate)
        {
            if (_process is not { HasExited: false } running)
            {
                return;
            }
            process = running;
            stopFile = _stopFile;
            _stopRequested = true;
        }

        var stopSignalWritten = false;
        if (!string.IsNullOrWhiteSpace(stopFile))
        {
            try
            {
                File.WriteAllText(stopFile, "stop", Encoding.UTF8);
                stopSignalWritten = true;
            }
            catch (IOException)
            {
                // The fallback below terminates the process immediately.
            }
            catch (UnauthorizedAccessException)
            {
                // The fallback below terminates the process immediately.
            }
        }

        _ = Task.Run(async () =>
        {
            if (stopSignalWritten)
            {
                await Task.Delay(TimeSpan.FromSeconds(8));
            }
            lock (_gate)
            {
                if (ReferenceEquals(_process, process) && !process.HasExited)
                {
                    process.Kill(entireProcessTree: true);
                }
            }
        });
    }

    private static string FormatOutputLine(string line)
    {
        const string prefix = "@maasvwb-event ";
        if (!line.StartsWith(prefix, StringComparison.Ordinal))
        {
            return line;
        }
        try
        {
            using var document = JsonDocument.Parse(line[prefix.Length..]);
            if (document.RootElement.TryGetProperty("message", out var message))
            {
                return $"[状态] {message.GetString()}";
            }
        }
        catch (JsonException)
        {
            return $"[事件格式错误] {line}";
        }
        return line;
    }

    public void Dispose() => Stop();
}

using System.Collections.Concurrent;
using System.Diagnostics;
using System.Text.Json;
using MaaSVWB.Desktop.Models;
using MaaSVWB.Desktop.Services;

// No UI or additional test packages: run the production service against a real
// Python child, using its real CLI parser and event emitter.
internal static class Program
{
    private static string _source = "";
    private static string _python = "";
    private static readonly ConcurrentDictionary<string, Fixture> Fixtures = new();

    public static async Task<int> Main(string[] args)
    {
        if (args.Length != 2) throw new ArgumentException("Expected source root and Python executable");
        _source = Path.GetFullPath(args[0]);
        _python = Path.GetFullPath(args[1]);
        var tests = new (string Name, Func<Task> Run)[]
        {
            ("arguments and Python events", ArgumentsAndEvents),
            ("puzzle and tracker CLI routing", CategoryRouting),
            ("stderr and nonzero exit", ErrorExit),
            ("malformed events do not break the output reader", MalformedEvents),
            ("graceful stop and marker cleanup", GracefulStop),
            ("unresponsive child and descendants are killed", ForcedStop),
            ("cancellation waits for child cleanup", Cancellation),
            ("desktop disposal kills child and descendants", Disposal),
            ("concurrent run is rejected", ConcurrentRun),
            ("failed start permits a later run", FailedStart),
        };
        var failures = 0;
        foreach (var test in tests)
        {
            try
            {
                await test.Run().WaitAsync(TimeSpan.FromSeconds(30));
                Console.WriteLine($"PASS {test.Name}");
            }
            catch (Exception error)
            {
                failures++;
                Console.Error.WriteLine($"FAIL {test.Name}: {error}");
            }
            finally
            {
                // A timed-out async test still owns its child. End it before
                // continuing, even if its own using/finally has not resumed.
                foreach (var fixture in Fixtures.Values) fixture.Dispose();
            }
        }
        Console.WriteLine($"Desktop integration: {tests.Length - failures}/{tests.Length} passed");
        return failures == 0 ? 0 : 1;
    }

    private static void Check(bool condition, string message)
    {
        if (!condition) throw new InvalidOperationException(message);
    }

    private static async Task ArgumentsAndEvents()
    {
        using var fixture = new Fixture("normal");
        Check(await fixture.Start() == 0, "Successful child failed");
        using var args = fixture.Arguments();
        var root = args.RootElement;
        Check(root.GetProperty("task").GetString() == "dungeon", "Wrong task argument");
        Check(root.GetProperty("profile").GetString() == "profile-with-spaces 测试", "Profile argument was split");
        Check(root.GetProperty("battle_count").GetInt32() == 3, "Wrong battle count");
        Check(root.GetProperty("serial").GetString() == "serial with spaces", "Serial argument was split");
        Check(root.GetProperty("adb").GetString() == Path.Combine(fixture.Root, "模拟器 adb.exe"), "ADB path was split");
        Check(root.GetProperty("deck_code").GetString() == "牌组分享 2.5.test.test", "Deck code was split");
        foreach (var flag in new[] { "execute", "skip_completed", "save_draw" })
            Check(root.GetProperty(flag).GetBoolean(), $"Missing {flag}");
        Check(root.GetProperty("cwd_matches_project_root").GetBoolean(),
            $"Wrong working directory: actual={root.GetProperty("cwd").GetString()}, expected={fixture.Root}");
        Check(root.GetProperty("project_root").GetString() == fixture.Root, "Wrong MAASVWB_ROOT");
        var snapshot = fixture.Snapshots.Single();
        Check(snapshot.Total == 3 && snapshot.Entries.Single() == new TrackerEntry("测试卡牌", 3), "Deck event mismatch");
        Check(snapshot.SessionId == "integration-session" && snapshot.Sequence == 1 && snapshot.State == "tracking", "Event metadata mismatch");
        Check(fixture.Output.Contains("最后一行输出"), "Last output line was lost");
        await fixture.AssertStopped();
    }

    private static async Task ErrorExit()
    {
        using var fixture = new Fixture("crash");
        Check(await fixture.Start() == 7, "Lost nonzero exit code");
        Check(fixture.Output.Contains("[错误] 预期的测试错误"), "stderr was lost");
        await fixture.AssertStopped();
    }

    private static async Task CategoryRouting()
    {
        foreach (var category in new[] { "puzzle", "tracker" })
        {
            using var fixture = new Fixture("normal");
            Check(await fixture.Start(category: category, execute: false) == 0, "Category route failed");
            using var args = fixture.Arguments();
            var root = args.RootElement;
            Check(root.GetProperty("task").GetString() == category, "Wrong category");
            Check(!root.GetProperty("execute").GetBoolean(), "Read-only run became executable");
            Check(root.GetProperty("stop_file").ValueKind == JsonValueKind.Null, "Read-only run has stop marker");
            var solution = root.GetProperty("solution").GetString();
            Check(category == "puzzle" ? solution == "profile-with-spaces 测试" : solution is null, "Wrong solution routing");
            await fixture.AssertStopped();
        }
    }

    private static async Task MalformedEvents()
    {
        using var fixture = new Fixture("malformed");
        Check(await fixture.Start() == 0, "Malformed event killed the output reader");
        Check(fixture.Output.Any(line => line.StartsWith("[事件格式错误]")), "Missing JSON diagnostic");
        Check(fixture.Output.Any(line => line.StartsWith("[事件字段错误]")), "Missing field diagnostic");
        Check(fixture.Snapshots.Count == 1 && fixture.Output.Contains("最后一行输出"), "Subsequent valid output lost");
    }

    private static async Task GracefulStop()
    {
        using var fixture = new Fixture("graceful");
        var run = fixture.Start();
        await fixture.Ready.Task.WaitAsync(TimeSpan.FromSeconds(10));
        await fixture.Service.StopAsync();
        Check(await run == 130 && fixture.Service.WasStopped, "Graceful stop was not reported");
        await fixture.AssertStopped();
    }

    private static async Task ForcedStop()
    {
        using var fixture = new Fixture("ignore-stop");
        var run = fixture.Start();
        await fixture.Ready.Task.WaitAsync(TimeSpan.FromSeconds(10));
        await fixture.Service.StopAsync();
        Check(await run != 0 && fixture.Service.WasStopped, "Forced stop was not reported");
        await fixture.AssertStopped();
    }

    private static async Task Cancellation()
    {
        using var fixture = new Fixture("cancel");
        using var cancellation = new CancellationTokenSource();
        var run = fixture.Start(cancellation.Token);
        await fixture.Ready.Task.WaitAsync(TimeSpan.FromSeconds(10));
        cancellation.Cancel();
        try
        {
            await run;
            throw new InvalidOperationException("Cancellation did not propagate");
        }
        catch (OperationCanceledException) { }
        await fixture.AssertStopped();
    }

    private static async Task Disposal()
    {
        using var fixture = new Fixture("dispose");
        var run = fixture.Start();
        await fixture.Ready.Task.WaitAsync(TimeSpan.FromSeconds(10));
        fixture.Service.Dispose();
        Check(await run != 0, "Disposed child exited successfully");
        await fixture.AssertStopped();
    }

    private static async Task ConcurrentRun()
    {
        using var fixture = new Fixture("graceful");
        var first = fixture.Start();
        await fixture.Ready.Task.WaitAsync(TimeSpan.FromSeconds(10));
        try
        {
            await fixture.Start();
            throw new InvalidOperationException("Concurrent run was accepted");
        }
        catch (InvalidOperationException error) when (error.Message == "已有任务正在运行。") { }
        await fixture.Service.StopAsync();
        Check(await first == 130, "Second run disturbed the first process");
        await fixture.AssertStopped();
    }

    private static async Task FailedStart()
    {
        using var fixture = new Fixture("normal");
        try
        {
            await fixture.Start(python: Path.Combine(fixture.Root, "missing-python"));
            throw new InvalidOperationException("Missing executable was accepted");
        }
        catch (System.ComponentModel.Win32Exception) { }
        Check(!fixture.Service.IsRunning, "Failed start left the service busy");
        Check(await fixture.Start() == 0, "Service could not recover after a failed start");
        await fixture.AssertStopped();
    }

    private sealed class Fixture : IDisposable
    {
        private int _disposed;
        public string Root { get; } = Path.GetFullPath(Path.Combine(Path.GetTempPath(), $"maasvwb-integration-{Guid.NewGuid():N} 子进程"));
        public AutomationService Service { get; } = new();
        public ConcurrentQueue<string> Output { get; } = new();
        public ConcurrentQueue<TrackerSnapshot> Snapshots { get; } = new();
        public TaskCompletionSource Ready { get; } = new(TaskCreationOptions.RunContinuationsAsynchronously);

        public Fixture(string mode)
        {
            Directory.CreateDirectory(Path.Combine(Root, "tools"));
            File.Copy(Path.Combine(_source, "tests", "fixtures", "automation_child.py"), Path.Combine(Root, "tools", "run_android.py"));
            File.WriteAllText(Path.Combine(Root, "source-root.txt"), _source);
            File.WriteAllText(Path.Combine(Root, "mode.txt"), mode);
            Service.TrackerUpdated += (_, snapshot) => Snapshots.Enqueue(snapshot);
            Fixtures.TryAdd(Root, this);
        }

        public Task<int> Start(CancellationToken cancellation = default, string? python = null,
            string category = "dungeon", bool execute = true) => Service.RunAsync(
            Root, python ?? _python, Path.Combine(Root, "模拟器 adb.exe"), "serial with spaces",
            category, "profile-with-spaces 测试", execute, true, true,
            line => { Output.Enqueue(line); if (line.Contains("子进程就绪")) Ready.TrySetResult(); },
            battleCount: 3, deckCode: "牌组分享 2.5.test.test", cancellationToken: cancellation);

        public JsonDocument Arguments() => JsonDocument.Parse(File.ReadAllText(Path.Combine(Root, "arguments.json")));

        public async Task AssertStopped()
        {
            Check(!Service.IsRunning, "Service is still running");
            using var args = Arguments();
            Check(!File.Exists(args.RootElement.GetProperty("stop_file").GetString()), "Stop marker was not cleaned up");
            await AssertExited(args.RootElement.GetProperty("pid").GetInt32());
            var descendant = Path.Combine(Root, "descendant.pid");
            if (File.Exists(descendant)) await AssertExited(int.Parse(File.ReadAllText(descendant)));
        }

        private static async Task AssertExited(int pid)
        {
            // Kill(entireProcessTree) is asynchronous for descendants.
            var deadline = Stopwatch.StartNew();
            while (Alive(pid) && deadline.Elapsed < TimeSpan.FromSeconds(3))
                await Task.Delay(20);
            Check(!Alive(pid), $"Process {pid} leaked after termination");
        }

        private static bool Alive(int pid)
        {
            try { using var process = Process.GetProcessById(pid); return !process.HasExited; }
            catch (ArgumentException) { return false; }
        }

        public void Dispose()
        {
            if (Interlocked.Exchange(ref _disposed, 1) != 0) return;
            Fixtures.TryRemove(Root, out _);
            Service.Dispose();
            var descendant = Path.Combine(Root, "descendant.pid");
            if (File.Exists(descendant))
            {
                try { using var process = Process.GetProcessById(int.Parse(File.ReadAllText(descendant))); if (!process.HasExited) process.Kill(true); }
                catch (ArgumentException) { }
            }
            var temporary = Path.TrimEndingDirectorySeparator(Path.GetFullPath(Path.GetTempPath()));
            var comparison = OperatingSystem.IsWindows() ? StringComparison.OrdinalIgnoreCase : StringComparison.Ordinal;
            if (!string.Equals(Path.GetDirectoryName(Root), temporary, comparison)
                || !Path.GetFileName(Root).StartsWith("maasvwb-integration-", StringComparison.Ordinal))
                throw new InvalidOperationException($"Refusing to delete unexpected test path: {Root}");
            Directory.Delete(Root, recursive: true);
        }
    }
}

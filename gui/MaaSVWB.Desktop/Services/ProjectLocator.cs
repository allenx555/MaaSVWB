namespace MaaSVWB.Desktop.Services;

public static class ProjectLocator
{
    public static string FindProjectRoot()
    {
        var configured = Environment.GetEnvironmentVariable("MAASVWB_ROOT");
        if (IsProjectRoot(configured))
        {
            return Path.GetFullPath(configured!);
        }

        var current = new DirectoryInfo(AppContext.BaseDirectory);
        for (var depth = 0; current is not null && depth < 10; depth++, current = current.Parent)
        {
            if (IsProjectRoot(current.FullName))
            {
                return current.FullName;
            }
        }

        return AppContext.BaseDirectory;
    }

    public static string FindPython(string projectRoot)
    {
        var candidates = new[]
        {
            Path.Combine(projectRoot, "runtime", "MaaSVWB.Runner.exe"),
            Path.Combine(projectRoot, "runtime", "MaaSVWB.Runner"),
            Path.Combine(projectRoot, ".venv", "Scripts", "python.exe"),
            Path.Combine(projectRoot, ".venv", "bin", "python"),
        };
        return candidates.FirstOrDefault(File.Exists) ?? "python";
    }

    public static string FindAdb()
    {
        var candidates = new[]
        {
            @"C:\Program Files\Netease\MuMuPlayer-12.0\nx_device\12.0\shell\adb.exe",
            @"C:\Program Files\Netease\MuMuPlayer-12.0\nx_main\adb.exe",
        };
        return candidates.FirstOrDefault(File.Exists) ?? "adb";
    }

    private static bool IsProjectRoot(string? path)
    {
        if (string.IsNullOrWhiteSpace(path))
        {
            return false;
        }
        var hasRuntime = File.Exists(Path.Combine(path, "runtime", "MaaSVWB.Runner.exe"))
            || File.Exists(Path.Combine(path, "runtime", "MaaSVWB.Runner"));
        var hasDevelopmentScript = File.Exists(Path.Combine(path, "tools", "run_android.py"));
        if (!hasRuntime && !hasDevelopmentScript)
        {
            return false;
        }
        return File.Exists(Path.Combine(path, "assets", "catalog", "puzzle_catalog.json"))
            || File.Exists(Path.Combine(path, "catalog", "puzzle_catalog.json"));
    }
}

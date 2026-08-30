using System.Text.Json;
using MaaSVWB.Desktop.Models;

namespace MaaSVWB.Desktop.Services;

public static class SettingsStore
{
    private static readonly JsonSerializerOptions JsonOptions = new()
    {
        WriteIndented = true,
    };

    public static string SettingsPath => Path.Combine(
        Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData),
        "MaaSVWB",
        "settings.json");

    public static FrontendSettings Load()
    {
        FrontendSettings settings;
        try
        {
            settings = File.Exists(SettingsPath)
                ? JsonSerializer.Deserialize<FrontendSettings>(File.ReadAllText(SettingsPath), JsonOptions)
                    ?? new FrontendSettings()
                : new FrontendSettings();
        }
        catch
        {
            settings = new FrontendSettings();
        }

        if (string.IsNullOrWhiteSpace(settings.ProjectRoot))
        {
            settings.ProjectRoot = ProjectLocator.FindProjectRoot();
        }
        if (string.IsNullOrWhiteSpace(settings.PythonPath)
            || (!string.Equals(settings.PythonPath, "python", StringComparison.OrdinalIgnoreCase)
                && !File.Exists(settings.PythonPath)))
        {
            settings.PythonPath = ProjectLocator.FindPython(settings.ProjectRoot);
        }
        if (string.IsNullOrWhiteSpace(settings.AdbPath))
        {
            settings.AdbPath = ProjectLocator.FindAdb();
        }
        return settings;
    }

    public static void Save(FrontendSettings settings)
    {
        var directory = Path.GetDirectoryName(SettingsPath)!;
        Directory.CreateDirectory(directory);
        File.WriteAllText(SettingsPath, JsonSerializer.Serialize(settings, JsonOptions));
    }
}

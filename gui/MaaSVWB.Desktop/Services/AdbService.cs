using System.Diagnostics;

namespace MaaSVWB.Desktop.Services;

public static class AdbService
{
    public static async Task<IReadOnlyList<string>> FindDevicesAsync(
        string adbPath,
        CancellationToken cancellationToken = default)
    {
        if (string.IsNullOrWhiteSpace(adbPath))
        {
            throw new InvalidOperationException("请先填写 adb.exe 路径。");
        }

        var startInfo = new ProcessStartInfo
        {
            FileName = adbPath,
            UseShellExecute = false,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            CreateNoWindow = true,
        };
        startInfo.ArgumentList.Add("devices");
        startInfo.ArgumentList.Add("-l");

        using var process = Process.Start(startInfo)
            ?? throw new InvalidOperationException("无法启动 ADB。");
        var outputTask = process.StandardOutput.ReadToEndAsync(cancellationToken);
        var errorTask = process.StandardError.ReadToEndAsync(cancellationToken);
        await process.WaitForExitAsync(cancellationToken);
        var output = await outputTask;
        var error = await errorTask;

        if (process.ExitCode != 0)
        {
            throw new InvalidOperationException(
                string.IsNullOrWhiteSpace(error) ? "ADB 设备发现失败。" : error.Trim());
        }

        return output
            .Split(['\r', '\n'], StringSplitOptions.RemoveEmptyEntries)
            .Select(line => line.Trim())
            .Where(line => !line.StartsWith("List of devices", StringComparison.OrdinalIgnoreCase))
            .Select(line => line.Split((char[]?)null, StringSplitOptions.RemoveEmptyEntries))
            .Where(parts => parts.Length >= 2 && parts[1] == "device")
            .Select(parts => parts[0])
            .Distinct(StringComparer.OrdinalIgnoreCase)
            .ToArray();
    }
}

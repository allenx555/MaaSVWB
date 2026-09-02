namespace MaaSVWB.Desktop.Models;

public sealed class FrontendSettings
{
    public string ProjectRoot { get; set; } = string.Empty;

    public string PythonPath { get; set; } = string.Empty;

    public string AdbPath { get; set; } = string.Empty;

    public string DeviceSerial { get; set; } = string.Empty;

    public bool SaveDraw { get; set; }

    public int DungeonBattleCount { get; set; } = 1;

    public string TrackerDeckCode { get; set; } = string.Empty;
}

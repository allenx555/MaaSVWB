namespace MaaSVWB.Desktop.Models;

public record TrackerEntry(string Name, int Count);

public record TrackerSnapshot(IReadOnlyList<TrackerEntry> Entries, int Total);

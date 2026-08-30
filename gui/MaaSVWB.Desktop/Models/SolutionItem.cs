namespace MaaSVWB.Desktop.Models;

public sealed record SolutionItem(
    string Id,
    string Name,
    string Category,
    string GroupName,
    string SeriesName,
    bool HasScript,
    int Sequence = 0,
    string? RequiresId = null)
{
    public override string ToString() => Name;
}

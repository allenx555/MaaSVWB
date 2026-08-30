namespace MaaSVWB.Desktop.Models;

public sealed record TaskRunMode(string Id, string Name)
{
    public override string ToString() => Name;
}

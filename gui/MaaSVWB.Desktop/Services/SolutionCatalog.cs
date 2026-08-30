using System.Text.Json;
using MaaSVWB.Desktop.Models;

namespace MaaSVWB.Desktop.Services;

public static class SolutionCatalog
{
    public static IReadOnlyList<SolutionItem> Load(string projectRoot, string category)
    {
        var catalogPath = FindExistingFile(
            Path.Combine(projectRoot, "assets", "catalog", $"{category}_catalog.json"),
            Path.Combine(projectRoot, "catalog", $"{category}_catalog.json"));
        if (!File.Exists(catalogPath))
        {
            return [];
        }

        var solutionDirectory = FindExistingDirectory(
            Path.Combine(projectRoot, "assets", "resource", "solutions"),
            Path.Combine(projectRoot, "resource", "solutions"));
        var configuredIds = Directory.Exists(solutionDirectory)
            ? Directory.EnumerateFiles(solutionDirectory, "*.json")
                .Select(Path.GetFileNameWithoutExtension)
                .OfType<string>()
                .Where(id => !string.IsNullOrWhiteSpace(id))
                .ToHashSet(StringComparer.OrdinalIgnoreCase)
            : new HashSet<string>(StringComparer.OrdinalIgnoreCase);

        try
        {
            using var document = JsonDocument.Parse(File.ReadAllText(catalogPath));
            return document.RootElement
                .GetProperty("items")
                .EnumerateArray()
                .Select(item => ParseItem(item, category, configuredIds))
                .ToArray();
        }
        catch (Exception exception) when (
            exception is IOException
                or UnauthorizedAccessException
                or JsonException
                or InvalidOperationException)
        {
            return [];
        }
    }

    private static SolutionItem ParseItem(
        JsonElement item,
        string category,
        IReadOnlySet<string> configuredIds)
    {
        var id = item.GetProperty("id").GetString() ?? string.Empty;
        var name = item.GetProperty("name").GetString() ?? id;
        var series = OptionalString(item, "series");
        var explicitGroup = OptionalString(item, "group");
        var group = NormalizeGroupName(
            string.IsNullOrWhiteSpace(explicitGroup) ? series : explicitGroup);
        var sequence = item.TryGetProperty("sequence", out var sequenceProperty)
            ? sequenceProperty.GetInt32()
            : 0;
        var requiresId = item.TryGetProperty("requires", out var requiresProperty)
            ? requiresProperty.GetString()
            : null;
        return new SolutionItem(
            id,
            name,
            category,
            group,
            series,
            configuredIds.Contains(id),
            sequence,
            requiresId);
    }

    private static string OptionalString(JsonElement item, string name) =>
        item.TryGetProperty(name, out var property)
            ? property.GetString() ?? string.Empty
            : string.Empty;

    private static string FindExistingFile(params string[] candidates) =>
        candidates.FirstOrDefault(File.Exists) ?? candidates[0];

    private static string FindExistingDirectory(params string[] candidates) =>
        candidates.FirstOrDefault(Directory.Exists) ?? candidates[0];

    private static string NormalizeGroupName(string name) => name
        .Replace("①", "1", StringComparison.Ordinal)
        .Replace("②", "2", StringComparison.Ordinal)
        .Replace("③", "3", StringComparison.Ordinal)
        .Replace("④", "4", StringComparison.Ordinal)
        .Replace("⑤", "5", StringComparison.Ordinal);
}

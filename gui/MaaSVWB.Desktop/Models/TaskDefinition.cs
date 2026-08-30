namespace MaaSVWB.Desktop.Models;

public sealed record TaskDefinition(
    string Title,
    string Description,
    string ExecutionHint,
    string Category,
    string GroupSelectorLabel,
    string ItemSelectorLabel,
    string BatchNoun,
    IReadOnlyList<TaskRunMode> RunModes);

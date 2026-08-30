using System.Collections.ObjectModel;
using System.ComponentModel;
using System.Windows.Input;
using MaaSVWB.Desktop.Models;

namespace MaaSVWB.Desktop.ViewModels;

public sealed class TaskTabViewModel : ViewModelBase
{
    private readonly MainWindowViewModel _owner;
    private SolutionItem? _selectedSolution;
    private TaskRunMode? _selectedRunMode;
    private string? _selectedSolutionGroup;

    public TaskTabViewModel(
        MainWindowViewModel owner,
        TaskDefinition definition,
        IEnumerable<SolutionItem> solutions)
    {
        _owner = owner;
        Definition = definition;
        Solutions = new ObservableCollection<SolutionItem>(solutions);
        ShowRunModeSelector = definition.RunModes.Count > 0;
        SolutionGroups = new ObservableCollection<string>(Solutions
            .Where(solution => !string.IsNullOrWhiteSpace(solution.GroupName))
            .Select(solution => solution.GroupName)
            .Distinct(StringComparer.OrdinalIgnoreCase));
        _selectedSolutionGroup = SolutionGroups.FirstOrDefault();
        VisibleSolutions = new ObservableCollection<SolutionItem>(
            SolutionsForGroup(_selectedSolutionGroup));
        _selectedSolution = VisibleSolutions.FirstOrDefault(solution => solution.HasScript);
        RunModes = new ObservableCollection<TaskRunMode>(definition.RunModes);
        _selectedRunMode = RunModes.LastOrDefault();
        RunCommand = new AsyncCommand(RunAsync, CanRun);
        _owner.PropertyChanged += OwnerOnPropertyChanged;
    }

    public TaskDefinition Definition { get; }

    public string Title => Definition.Title;

    public string Description => Definition.Description;

    public string ExecutionHint => Definition.ExecutionHint;

    public string Category => Definition.Category;

    public string GroupSelectorLabel => Definition.GroupSelectorLabel;

    public string SpecificSelectorLabel => Definition.ItemSelectorLabel;

    public ObservableCollection<SolutionItem> Solutions { get; }

    public ObservableCollection<SolutionItem> VisibleSolutions { get; }

    public ObservableCollection<string> SolutionGroups { get; }

    public ObservableCollection<TaskRunMode> RunModes { get; }

    public bool ShowRunModeSelector { get; }

    public string? SelectedSolutionGroup
    {
        get => _selectedSolutionGroup;
        set
        {
            if (SetProperty(ref _selectedSolutionGroup, value))
            {
                RefreshVisibleSolutions();
            }
        }
    }

    public TaskRunMode? SelectedRunMode
    {
        get => _selectedRunMode;
        set
        {
            if (SetProperty(ref _selectedRunMode, value))
            {
                OnPropertyChanged(nameof(IsCatalogSolutionSelectorVisible));
                RunCommand.RaiseCanExecuteChanged();
            }
        }
    }

    public bool IsCatalogSolutionSelectorVisible =>
        ShowRunModeSelector && SelectedRunMode?.Id == "specific";

    public SolutionItem? SelectedSolution
    {
        get => _selectedSolution;
        set
        {
            if (SetProperty(ref _selectedSolution, value))
            {
                RunCommand.RaiseCanExecuteChanged();
            }
        }
    }

    public string LogText => _owner.LogText;

    public bool IsBusy => _owner.IsBusy;

    public string StatusText => _owner.StatusText;

    public AsyncCommand RunCommand { get; }

    public ICommand StopCommand => _owner.StopCommand;

    public ICommand ClearLogCommand => _owner.ClearLogCommand;

    private bool CanRun() => !IsBusy
        && (SelectedRunMode?.Id == "all_incomplete"
            ? BatchSolutions().Any()
            : SelectedSolution?.HasScript == true);

    private async Task RunAsync()
    {
        if (SelectedRunMode?.Id == "all_incomplete")
        {
            await _owner.RunBatchAsync(BatchSolutions(), Definition.BatchNoun);
            return;
        }
        if (SelectedSolution is not null)
        {
            await _owner.RunTaskAsync(Category, SelectedSolution.Id, SelectedSolution.Name);
        }
    }

    private void RefreshVisibleSolutions()
    {
        VisibleSolutions.Clear();
        foreach (var solution in SolutionsForGroup(SelectedSolutionGroup))
        {
            VisibleSolutions.Add(solution);
        }
        SelectedSolution = VisibleSolutions.FirstOrDefault(solution => solution.HasScript);
    }

    private IEnumerable<SolutionItem> BatchSolutions() =>
        Solutions.Where(solution => solution.HasScript);

    private IEnumerable<SolutionItem> SolutionsForGroup(string? groupName) =>
        Solutions
            .Where(solution => string.Equals(
                solution.GroupName,
                groupName,
                StringComparison.OrdinalIgnoreCase))
            .OrderBy(solution => solution.Sequence == 0 ? int.MaxValue : solution.Sequence);

    private void OwnerOnPropertyChanged(object? sender, PropertyChangedEventArgs args)
    {
        if (args.PropertyName is nameof(MainWindowViewModel.LogText)
            or nameof(MainWindowViewModel.IsBusy)
            or nameof(MainWindowViewModel.StatusText))
        {
            OnPropertyChanged(args.PropertyName);
        }
        if (args.PropertyName == nameof(MainWindowViewModel.IsBusy))
        {
            RunCommand.RaiseCanExecuteChanged();
        }
    }
}

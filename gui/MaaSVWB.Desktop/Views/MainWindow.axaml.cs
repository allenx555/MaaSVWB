using Avalonia.Controls;
using MaaSVWB.Desktop.ViewModels;

namespace MaaSVWB.Desktop.Views;

public partial class MainWindow : Window
{
    public MainWindow() => InitializeComponent();

    private async void OnCopyDeckCode(object? sender, Avalonia.Interactivity.RoutedEventArgs e)
    {
        var vm = DataContext as MainWindowViewModel;
        if (vm is not null)
            await (GetTopLevel(this)?.Clipboard?.SetTextAsync(vm.DungeonRecommendedDeckCode)
                   ?? System.Threading.Tasks.Task.CompletedTask);
    }
}

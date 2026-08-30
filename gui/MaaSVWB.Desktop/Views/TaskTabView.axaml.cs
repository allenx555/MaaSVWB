using Avalonia.Controls;
using Avalonia.Interactivity;

namespace MaaSVWB.Desktop.Views;

public partial class TaskTabView : UserControl
{
    public TaskTabView() => InitializeComponent();

    private void LogBox_OnTextChanged(object? sender, TextChangedEventArgs args)
    {
        if (sender is TextBox textBox)
        {
            textBox.CaretIndex = textBox.Text?.Length ?? 0;
        }
    }
}

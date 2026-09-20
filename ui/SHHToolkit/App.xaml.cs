using System.Windows;

namespace SHHToolkit;

public partial class App : Application
{
    protected override void OnStartup(StartupEventArgs e)
    {
        base.OnStartup(e);
        DispatcherUnhandledException += (_, args) =>
        {
            MessageBox.Show(args.Exception.Message, "Silent Hill: Homecoming Toolkit",
                MessageBoxButton.OK, MessageBoxImage.Warning);
            args.Handled = true;
        };
    }
}

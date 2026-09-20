using System.ComponentModel;
using System.Runtime.CompilerServices;
using SHHToolkit.Services;

namespace SHHToolkit;

/// <summary>
/// One row: a short label, a one-line summary, and a toggle. The long explanation lives
/// in the tooltip, not on screen.
/// </summary>
public sealed class FeatureRow : INotifyPropertyChanged
{
    public required string Name { get; init; }
    public required string Summary { get; init; }
    public required string Tooltip { get; init; }

    public required Func<PatchState> GetState { get; init; }
    public required Action<bool> Set { get; init; }

    /// <summary>File patches need the game closed; the practice hook needs it running.</summary>
    public bool RequiresGameRunning { get; init; }

    /// <summary>Live text for this row specifically, refreshed on a timer. Optional.</summary>
    public Func<string?>? GetDetail { get; init; }

    private PatchState _state = PatchState.Unknown;
    public PatchState State
    {
        get => _state;
        private set
        {
            _state = value;
            Raise(nameof(State));
            Raise(nameof(IsOn));
            Raise(nameof(CanToggle));
        }
    }

    private string? _detail;
    /// <summary>Live text under the summary: the hook's counters, for example.</summary>
    public string? Detail
    {
        get => _detail;
        set { _detail = value; Raise(nameof(Detail)); Raise(nameof(HasDetail)); }
    }

    public bool HasDetail => !string.IsNullOrWhiteSpace(Detail);
    public bool IsOn => State == PatchState.Patched;
    public bool CanToggle => State != PatchState.Unknown;

    public void Refresh() => State = GetState();

    public event PropertyChangedEventHandler? PropertyChanged;
    private void Raise([CallerMemberName] string? n = null) =>
        PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(n));
}

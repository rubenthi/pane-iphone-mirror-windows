using System.Text.Json;
using Windows.Devices.Enumeration;
using Windows.Media.Audio;

internal sealed class Receiver : IDisposable
{
    private AudioPlaybackConnection? connection;
    private string? device;
    private HashSet<string> known = new();
    public object Status() => new { available = true, state = connection?.State.ToString() ?? "Disconnected", device };
    public void Dispose() { connection?.Dispose(); connection = null; device = null; }
    public async Task<object> Command(JsonElement input)
    {
        switch (input.GetProperty("action").GetString()) {
            case "notification.probe":
                var selected = input.GetProperty("device").GetString();
                if (!(await Ancs.Devices()).Any(d => d.Id == selected)) throw new ArgumentException("Select a paired LE device.");
                using (var probe = new CancellationTokenSource(TimeSpan.FromSeconds(18))) {
                    bool subscribed = false;
                    try {
                        await Ancs.Listen(selected!, _ => { subscribed = true; probe.Cancel(); }, (_, _, _) => {}, probe.Token);
                    } catch (OperationCanceledException) when (subscribed) {}
                    if (!subscribed) throw new InvalidOperationException("No ANCS subscription established.");
                    return new { subscribed };
                }
            case "notification.devices":
                var ble = await Ancs.Devices();
                return new { devices = ble.Select(d => new { id=d.Id, name=d.Name }).ToArray() };
            case "status": return Status();
            case "devices":
                var devices = await Pairing.AudioDevices();
                known = devices.Select(d => d.id).ToHashSet();
                return new { devices };
            case "audio.pair":
                return Pairing.PairPhone(input.GetProperty("address").GetString() ?? "");
            case "audio.disconnect": Dispose(); return Status();
            case "audio.connect":
                var id = input.GetProperty("device").GetString() ?? "";
                if (!known.Contains(id)) throw new ArgumentException("Refresh and select a paired Bluetooth audio device.");
                if (device == id && connection?.State == AudioPlaybackConnectionState.Opened) return Status();
                using (var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(25))) {
                    if (device != id || connection == null) {
                        Dispose();
                        connection = AudioPlaybackConnection.TryCreateFromId(id) ?? throw new InvalidOperationException("Windows cannot receive media from this device.");
                        try { await connection.StartAsync().AsTask(timeout.Token); device = id; }
                        catch { Dispose(); throw; }
                    }
                    AudioPlaybackConnectionOpenResult result;
                    try { result = await connection.OpenAsync().AsTask(timeout.Token); }
                    catch { Dispose(); throw; }
                    if (result.Status != AudioPlaybackConnectionOpenResultStatus.Success)
                        return new { state = connection.State.ToString(), listening = true,
                            note = $"Paired. Receiver enabled. Windows: {result.Status} (0x{result.ExtendedError?.HResult:X8}). Choose this PC in the iPhone media output picker." };
                }
                return Status();
            default: throw new ArgumentException("Unknown audio action.");
        }
    }
}
internal static class Program
{
    [MTAThread]
    private static async Task Main()
    {
        using var receiver = new Receiver();
        while (await Console.In.ReadLineAsync() is { } line) {
            object reply;
            try {
                if (line.Length > 16384) throw new ArgumentException("Request too large.");
                using var input = JsonDocument.Parse(line);
                reply = new { ok = true, result = await receiver.Command(input.RootElement) };
            } catch (Exception error) { reply = new { ok = false, error = $"{error.Message} (0x{error.HResult:X8})" }; }
            Console.WriteLine(JsonSerializer.Serialize(reply));
        }
    }
}

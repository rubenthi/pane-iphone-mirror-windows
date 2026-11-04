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
            case "status": return Status();
            case "devices":
                var devices = await DeviceInformation.FindAllAsync(AudioPlaybackConnection.GetDeviceSelector(),
                    new[] { "System.Devices.Aep.DeviceAddress" }).AsTask().WaitAsync(TimeSpan.FromSeconds(12));
                known = devices.Select(d => d.Id).ToHashSet();
                return new { devices = devices.Select(d => new { id = d.Id, name = d.Name,
                    address = d.Properties.TryGetValue("System.Devices.Aep.DeviceAddress", out var a) ? a?.ToString() : null }).ToArray() };
            case "audio.disconnect": Dispose(); return Status();
            case "audio.connect":
                var id = input.GetProperty("device").GetString() ?? "";
                if (!known.Contains(id)) throw new ArgumentException("Refresh and select a paired Bluetooth audio device.");
                if (device == id && connection?.State == AudioPlaybackConnectionState.Opened) return Status();
                Dispose();
                var next = AudioPlaybackConnection.TryCreateFromId(id) ?? throw new InvalidOperationException("The Windows Bluetooth adapter cannot receive audio from this device.");
                try {
                    using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(25));
                    await next.StartAsync().AsTask(timeout.Token);
                    var result = await next.OpenAsync().AsTask(timeout.Token);
                    if (result.Status != AudioPlaybackConnectionOpenResultStatus.Success)
                        throw new InvalidOperationException($"Audio connection: {result.Status}. Unlock the paired iPhone and retry.");
                    connection = next; device = id;
                } catch { next.Dispose(); throw; }
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

using System.Text.Json;
using Windows.Devices.Bluetooth;
using Windows.Devices.Enumeration;
using Windows.Media.Audio;
using Windows.Storage.Streams;

namespace Pane.Bluetooth;

internal static class Buffers
{
    public static IBuffer From(byte[] bytes)
    {
        using var writer = new DataWriter();
        writer.WriteBytes(bytes);
        return writer.DetachBuffer();
    }
    public static byte[] Read(IBuffer buffer)
    {
        using var reader = DataReader.FromBuffer(buffer);
        var bytes = new byte[buffer.Length];
        reader.ReadBytes(bytes);
        return bytes;
    }
}

internal sealed class Bridge : IDisposable
{
    private AudioPlaybackConnection? audio;
    private string? audioId;
    private readonly MousePeripheral mouse = new();
    private readonly Notifications notifications = new();
    private HashSet<string> audioDevices = new();
    private HashSet<string> notificationDevices = new();

    public object Status() => new {
        available = true,
        audio = new { state = audio?.State.ToString() ?? "Disconnected", device = audioId },
        cursor = mouse.Status(), notifications = notifications.Status(),
        microphone = new { state = "external", note = "Use Phone Link Calls for the laptop microphone. A2DP is playback only; arbitrary iPhone app microphone routing is unavailable." }
    };

    public async Task<object> Command(JsonElement command)
    {
        string action = command.GetProperty("action").GetString() ?? "";
        switch (action)
        {
            case "status": return Status();
            case "devices":
                var sound = await DeviceInformation.FindAllAsync(AudioPlaybackConnection.GetDeviceSelector());
                var ble = await DeviceInformation.FindAllAsync(BluetoothLEDevice.GetDeviceSelectorFromPairingState(true));
                audioDevices = sound.Select(d => d.Id).ToHashSet();
                notificationDevices = ble.Select(d => d.Id).ToHashSet();
                return new {
                    audio = sound.Select(d => new { id = d.Id, name = d.Name }).ToArray(),
                    notifications = ble.Select(d => new { id = d.Id, name = d.Name }).ToArray()
                };
            case "audio.connect":
                string id = command.GetProperty("device").GetString() ?? "";
                if (!audioDevices.Contains(id)) throw new ArgumentException("Refresh and select an audio device first.");
                audio?.Dispose(); audio = null; audioId = null;
                var connection = AudioPlaybackConnection.TryCreateFromId(id)
                    ?? throw new InvalidOperationException("Windows cannot receive audio from this device.");
                try
                {
                    await connection.StartAsync();
                    var result = await connection.OpenAsync();
                    if (result.Status != AudioPlaybackConnectionOpenResultStatus.Success)
                        throw new InvalidOperationException($"Bluetooth audio: {result.Status}. Select this PC as the iPhone's audio output and retry.");
                    audio = connection; audioId = id;
                }
                catch { connection.Dispose(); throw; }
                return Status();
            case "audio.disconnect":
                audio?.Dispose(); audio = null; audioId = null; return Status();
            case "cursor.start": await mouse.Start(); return Status();
            case "cursor.stop": await mouse.Stop(); return Status();
            case "cursor.select": mouse.Select(command.GetProperty("device").GetString() ?? ""); return Status();
            case "cursor.move":
                await mouse.Send(Protocol.Mouse(command.GetProperty("buttons").GetInt32(),
                    command.GetProperty("dx").GetInt32(), command.GetProperty("dy").GetInt32(),
                    command.GetProperty("wheel").GetInt32()));
                return new { ok = true };
            case "notifications.connect":
                string device = command.GetProperty("device").GetString() ?? "";
                if (!notificationDevices.Contains(device)) throw new ArgumentException("Refresh and select a paired Bluetooth LE device first.");
                await notifications.Connect(device); return Status();
            case "notifications.disconnect": await notifications.Disconnect(); return Status();
            case "stop": Dispose(); return new { ok = true };
            default: throw new ArgumentException("Unknown Bluetooth action.");
        }
    }

    public void Dispose()
    {
        audio?.Dispose(); audio = null; audioId = null;
        mouse.Stop().GetAwaiter().GetResult();
        notifications.Disconnect().GetAwaiter().GetResult();
    }
}

internal static class Program
{
    // No TCP listener. Only the owning Pane process can access these pipes.
    [MTAThread]
    private static async Task Main()
    {
        using var bridge = new Bridge();
        while (await Console.In.ReadLineAsync() is { } line)
        {
            object response;
            try
            {
                if (line.Length > 16384) throw new ArgumentException("Request too large.");
                using var request = JsonDocument.Parse(line);
                response = new { ok = true, result = await bridge.Command(request.RootElement) };
            }
            catch (Exception error)
            {
                response = new { ok = false, error = $"{error.Message} (0x{error.HResult:X8})" };
            }
            Console.WriteLine(JsonSerializer.Serialize(response));
        }
    }
}

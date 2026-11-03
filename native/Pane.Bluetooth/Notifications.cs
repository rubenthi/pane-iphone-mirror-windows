using System.Buffers.Binary;
using System.Threading.Channels;
using Windows.Devices.Bluetooth;
using Windows.Devices.Bluetooth.GenericAttributeProfile;

namespace Pane.Bluetooth;

internal sealed record PhoneNotification(uint uid, long revision, byte flags, byte category,
    string app = "", string title = "iPhone notification", string message = "");

internal sealed class Notifications
{
    private static readonly Guid ServiceId = Guid.Parse("7905f431-b5ce-4e99-a40f-4b1e122d00d0");
    private static readonly Guid SourceId = Guid.Parse("9fbf120d-6301-42d9-8c58-25e699a21dbd");
    private static readonly Guid DataId = Guid.Parse("22eac6e9-24d6-4bb5-be44-b36ace7c7bfb");
    private static readonly Guid ControlId = Guid.Parse("69d1d8f3-45e1-49a8-9821-9bbdfdaad9d9");
    private readonly object gate = new();
    private readonly Dictionary<uint, PhoneNotification> items = new();
    private BluetoothLEDevice? device;
    private GattDeviceService? service;
    private GattCharacteristic? source, data, control;
    private CancellationTokenSource? cancellation;
    private Task? worker;
    private Channel<PhoneNotification>? queue;
    private AttributeResponse? parser;
    private TaskCompletionSource<Dictionary<byte, string>>? pending;
    private string state = "Disconnected", error = "";
    private long revision;

    public object Status() { lock (gate) return new { state, error, device = device?.Name,
        items = items.Values.OrderByDescending(n => n.revision).ToArray() }; }

    public async Task Connect(string id)
    {
        await Disconnect();
        try
        {
            device = await BluetoothLEDevice.FromIdAsync(id) ?? throw new IOException("Bluetooth LE device unavailable.");
            device.ConnectionStatusChanged += ConnectionChanged;
            device.GattServicesChanged += ServicesChanged;
            var services = await device.GetGattServicesForUuidAsync(ServiceId, BluetoothCacheMode.Uncached);
            if (services.Status != GattCommunicationStatus.Success || services.Services.Count == 0)
                throw new IOException("The iPhone did not expose ANCS. Pair with Windows, unlock it and allow Share System Notifications in its Bluetooth settings, then reconnect.");
            service = services.Services[0];
            foreach (var extra in services.Services.Skip(1)) extra.Dispose();
            var characteristics = await service.GetCharacteristicsAsync(BluetoothCacheMode.Uncached);
            if (characteristics.Status != GattCommunicationStatus.Success) throw new IOException("ANCS characteristics unavailable.");
            source = characteristics.Characteristics.FirstOrDefault(c => c.Uuid == SourceId)
                ?? throw new IOException("ANCS notification source unavailable.");
            data = characteristics.Characteristics.FirstOrDefault(c => c.Uuid == DataId);
            control = characteristics.Characteristics.FirstOrDefault(c => c.Uuid == ControlId);
            cancellation = new CancellationTokenSource();
            queue = Channel.CreateBounded<PhoneNotification>(new BoundedChannelOptions(128) {
                SingleReader = true, FullMode = BoundedChannelFullMode.DropOldest
            });
            if (data != null && control != null) {
                data.ValueChanged += DataChanged;
                await Subscribe(data);
                worker = Process(queue.Reader, cancellation.Token);
            }
            source.ValueChanged += SourceChanged;
            await Subscribe(source);
            cancellation.Token.ThrowIfCancellationRequested();
            lock (gate) { state = "Connected"; error = ""; }
        }
        catch { await Disconnect(); throw; }
    }

    private static async Task Subscribe(GattCharacteristic characteristic)
    {
        var result = await characteristic.WriteClientCharacteristicConfigurationDescriptorAsync(GattClientCharacteristicConfigurationDescriptorValue.Notify);
        if (result != GattCommunicationStatus.Success) throw new IOException($"iPhone notification permission/connection failed: {result}.");
    }

    private void ConnectionChanged(BluetoothLEDevice sender, object args)
    {
        if (sender.ConnectionStatus == BluetoothConnectionStatus.Disconnected) Fault("Bluetooth disconnected. Reconnect notifications.");
    }
    private void ServicesChanged(BluetoothLEDevice sender, object args) => Fault("The iPhone changed its Bluetooth services. Reconnect notifications.");
    private void Fault(string reason)
    {
        lock (gate) { state = "Disconnected"; error = reason; items.Clear(); pending?.TrySetException(new IOException(reason)); }
        cancellation?.Cancel();
    }

    private void SourceChanged(GattCharacteristic sender, GattValueChangedEventArgs args)
    {
        try {
            var bytes = Buffers.Read(args.CharacteristicValue);
            if (bytes.Length != 8 || bytes[0] > 2) return;
            uint uid = BinaryPrimitives.ReadUInt32LittleEndian(bytes.AsSpan(4));
            lock (gate) {
                if (cancellation?.IsCancellationRequested != false) return;
                if (bytes[0] == 2) { items.Remove(uid); return; }
                var item = new PhoneNotification(uid, ++revision, bytes[1], bytes[2]);
                if (items.Count >= 100 && !items.ContainsKey(uid)) items.Remove(items.Values.MinBy(n => n.revision)!.uid);
                items[uid] = item;
                queue?.Writer.TryWrite(item);
            }
        } catch { Fault("Invalid notification event. Reconnect notifications."); }
    }

    private void DataChanged(GattCharacteristic sender, GattValueChangedEventArgs args)
    {
        lock (gate) {
            try {
                if (parser?.Feed(Buffers.Read(args.CharacteristicValue)) is { } attributes) pending?.TrySetResult(attributes);
            } catch (Exception e) { pending?.TrySetException(e); }
        }
    }

    private async Task Process(ChannelReader<PhoneNotification> reader, CancellationToken token)
    {
        try {
            await foreach (var item in reader.ReadAllAsync(token)) {
                Task<Dictionary<byte, string>> response;
                lock (gate) {
                    if (!items.TryGetValue(item.uid, out var current) || current.revision != item.revision) continue;
                    parser = new AttributeResponse(item.uid);
                    pending = new(TaskCreationOptions.RunContinuationsAsynchronously);
                    response = pending.Task;
                }
                try {
                    var status = await control!.WriteValueAsync(Buffers.From(Protocol.Attributes(item.uid)), GattWriteOption.WriteWithResponse).AsTask(token);
                    if (status != GattCommunicationStatus.Success) throw new IOException($"ANCS request failed: {status}.");
                    var attributes = await response.WaitAsync(TimeSpan.FromSeconds(10), token);
                    lock (gate) {
                        if (items.TryGetValue(item.uid, out var current) && current.revision == item.revision)
                            items[item.uid] = item with { app = attributes[0], title = attributes[1], message = attributes[3] };
                    }
                } finally { lock (gate) { parser = null; pending = null; } }
            }
        } catch (OperationCanceledException) { }
        catch { Fault("Notification details stopped. Reconnect notifications to resynchronize."); }
    }

    public async Task Disconnect()
    {
        cancellation?.Cancel();
        if (source != null) source.ValueChanged -= SourceChanged;
        if (data != null) data.ValueChanged -= DataChanged;
        if (device != null) { device.ConnectionStatusChanged -= ConnectionChanged; device.GattServicesChanged -= ServicesChanged; }
        if (worker != null) { try { await worker; } catch { } }
        // Closing the owned GATT session drops subscriptions. Do not unpair the phone.
        service?.Dispose(); device?.Dispose();
        service = null; device = null; source = null; data = null; control = null;
        worker = null; queue = null; cancellation?.Dispose(); cancellation = null;
        lock (gate) { items.Clear(); parser = null; pending = null; state = "Disconnected"; error = ""; }
    }
}

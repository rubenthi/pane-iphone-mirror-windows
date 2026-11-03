using Windows.Devices.Bluetooth;
using Windows.Devices.Bluetooth.GenericAttributeProfile;

namespace Pane.Bluetooth;

internal sealed class MousePeripheral
{
    private GattServiceProvider? provider;
    private GattLocalCharacteristic? report;
    private string? selected;
    private bool suspended;
    private readonly SemaphoreSlim sending = new(1);
    private long lastInput;
    private int buttons;
    private Timer? releaseTimer;
    private static Guid Uuid(string shortId) => Guid.Parse($"0000{shortId}-0000-1000-8000-00805f9b34fb");

    public object Status() => new {
        state = provider?.AdvertisementStatus.ToString() ?? "Stopped",
        selected,
        clients = report?.SubscribedClients.Select(c => new { id = c.Session.DeviceId.Id, name = c.Session.DeviceId.Id }).ToArray(),
        suspended
    };

    public void Select(string device)
    {
        if (report == null || !report.SubscribedClients.Any(c => c.Session.DeviceId.Id == device))
            throw new ArgumentException("Select a connected iPhone cursor client.");
        if (buttons != 0) throw new InvalidOperationException("Release the mouse before changing phones.");
        selected = device;
    }

    public async Task Start()
    {
        if (provider != null) return;
        var adapter = await BluetoothAdapter.GetDefaultAsync();
        if (adapter == null || !adapter.IsPeripheralRoleSupported)
            throw new InvalidOperationException("This Bluetooth adapter/driver does not support BLE peripheral mode.");
        var result = await GattServiceProvider.CreateAsync(Uuid("1812"));
        if (result.Error != BluetoothError.Success)
            throw new InvalidOperationException($"Windows refused the Bluetooth HID service: {result.Error}.");
        provider = result.ServiceProvider;
        try
        {
            await Create("2a4a", GattCharacteristicProperties.Read, new byte[] { 0x11, 0x01, 0, 2 });
            await Create("2a4b", GattCharacteristicProperties.Read, Protocol.MouseMap);
            report = await Create("2a4d", GattCharacteristicProperties.Read | GattCharacteristicProperties.Notify, new byte[4]);
            var descriptor = await report.CreateDescriptorAsync(Uuid("2908"), new GattLocalDescriptorParameters {
                StaticValue = Buffers.From(new byte[] { 1, 1 }), ReadProtectionLevel = GattProtectionLevel.EncryptionRequired
            });
            if (descriptor.Error != BluetoothError.Success) throw new InvalidOperationException("Cannot create mouse report reference.");
            var control = await Create("2a4c", GattCharacteristicProperties.WriteWithoutResponse, null);
            control.WriteRequested += async (sender, args) => {
                var deferral = args.GetDeferral();
                try {
                    var request = await args.GetRequestAsync();
                    if (request != null) {
                        var value = Buffers.Read(request.Value);
                        if (value.Length == 1 && value[0] <= 1) suspended = value[0] == 0;
                        if (request.Option == GattWriteOption.WriteWithResponse) request.Respond();
                    }
                } catch { /* A disconnected peer may cancel its write. */ }
                finally { deferral.Complete(); }
            };
            provider.StartAdvertising(new GattServiceProviderAdvertisingParameters { IsConnectable = true, IsDiscoverable = true });
            releaseTimer = new Timer(async _ => {
                try {
                    if (Volatile.Read(ref buttons) != 0 && Environment.TickCount64 - Interlocked.Read(ref lastInput) > 1500)
                        await Send(new byte[4], staleOnly: true);
                } catch { /* Disconnected clients cannot receive a release. */ }
            }, null, 500, 500);
        }
        catch { await Stop(); throw; }
    }

    private async Task<GattLocalCharacteristic> Create(string id, GattCharacteristicProperties properties, byte[]? data)
    {
        var parameters = new GattLocalCharacteristicParameters {
            CharacteristicProperties = properties,
            ReadProtectionLevel = GattProtectionLevel.EncryptionRequired,
            WriteProtectionLevel = GattProtectionLevel.EncryptionRequired
        };
        if (data != null) parameters.StaticValue = Buffers.From(data);
        var result = await provider!.Service.CreateCharacteristicAsync(Uuid(id), parameters);
        if (result.Error != BluetoothError.Success) throw new InvalidOperationException($"Cannot create HID {id}: {result.Error}.");
        return result.Characteristic;
    }

    public async Task Send(byte[] data, bool staleOnly = false)
    {
        await sending.WaitAsync();
        try {
            if (staleOnly && (buttons == 0 || Environment.TickCount64 - Interlocked.Read(ref lastInput) <= 1500)) return;
            if (report == null || selected == null) throw new InvalidOperationException("Pair the iPhone, enable AssistiveTouch, then select its cursor client.");
            var client = report.SubscribedClients.FirstOrDefault(c => c.Session.DeviceId.Id == selected)
                ?? throw new InvalidOperationException("The selected iPhone cursor disconnected.");
            if (suspended && data.Any(b => b != 0)) throw new InvalidOperationException("The iPhone suspended Bluetooth cursor input.");
            var result = await report.NotifyValueAsync(Buffers.From(data), client);
            if (result.Status != GattCommunicationStatus.Success) throw new IOException($"Cursor delivery failed: {result.Status}.");
            Volatile.Write(ref buttons, data[0]);
            Interlocked.Exchange(ref lastInput, Environment.TickCount64);
        } finally { sending.Release(); }
    }

    public async Task Stop()
    {
        releaseTimer?.Dispose(); releaseTimer = null;
        try { if (buttons != 0) await Send(new byte[4]); } catch { }
        await sending.WaitAsync();
        try {
            provider?.StopAdvertising(); provider = null; report = null; selected = null;
            buttons = 0; suspended = false;
        } finally { sending.Release(); }
    }
}

using Windows.Devices.Bluetooth;
using Windows.Devices.Bluetooth.GenericAttributeProfile;
using Windows.Devices.Enumeration;
using Windows.Storage.Streams;

internal static class Ancs
{
    private static readonly Guid ServiceId = new("7905f431-b5ce-4e99-a40f-4b1e122d00d0");
    private static readonly Guid SourceId = new("9fbf120d-6301-42d9-8c58-25e699a21dbd");

    public static async Task<DeviceInformationCollection> Devices() =>
        await DeviceInformation.FindAllAsync(BluetoothLEDevice.GetDeviceSelectorFromPairingState(true));

    // Returns when the phone disconnects or changes services. iOS notification
    // identifiers are session-scoped. No message bodies or titles are requested.
    public static async Task Listen(string id, Action<string> status,
        Action<byte, byte, uint> changed, CancellationToken token)
    {
        using var phone = await BluetoothLEDevice.FromIdAsync(id).AsTask(token)
            ?? throw new InvalidOperationException("Bluetooth iPhone unavailable. Check Bluetooth and pairing.");
        var ended = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        phone.ConnectionStatusChanged += (device, _) => {
            if (device.ConnectionStatus == BluetoothConnectionStatus.Disconnected) ended.TrySetResult();
        };
        phone.GattServicesChanged += (_, _) => ended.TrySetResult();
        var services = await phone.GetGattServicesForUuidAsync(ServiceId, BluetoothCacheMode.Uncached).AsTask(token);
        if (services.Status != GattCommunicationStatus.Success || services.Services.Count == 0)
            throw new InvalidOperationException($"ANCS unavailable ({services.Status}). Unlock iPhone and enable Share System Notifications for this PC.");
        using var service = services.Services[0];
        var chars = await service.GetCharacteristicsForUuidAsync(SourceId).AsTask(token);
        if (chars.Status != GattCommunicationStatus.Success || chars.Characteristics.Count == 0)
            throw new InvalidOperationException($"Notification source unavailable ({chars.Status}). Check iPhone permissions.");
        var source = chars.Characteristics[0];
        void Receive(GattCharacteristic sender, GattValueChangedEventArgs args)
        {
            using var reader = DataReader.FromBuffer(args.CharacteristicValue);
            if (reader.UnconsumedBufferLength != 8) return;
            reader.ByteOrder = ByteOrder.LittleEndian;
            var kind = reader.ReadByte();
            var flags = reader.ReadByte();
            reader.ReadByte(); reader.ReadByte();
            changed(kind, flags, reader.ReadUInt32());
        }
        source.ValueChanged += Receive;
        try {
            var result = await source.WriteClientCharacteristicConfigurationDescriptorAsync(
                GattClientCharacteristicConfigurationDescriptorValue.Notify).AsTask(token);
            if (result != GattCommunicationStatus.Success)
                throw new InvalidOperationException($"Notification permission: {result}. Approve sharing on iPhone.");
            status("Subscribed to iPhone notifications.");
            await ended.Task.WaitAsync(token);
        } finally {
            source.ValueChanged -= Receive;
        }
    }
}

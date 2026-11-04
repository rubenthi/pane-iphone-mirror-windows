using System.ComponentModel;
using System.Runtime.InteropServices;
using Windows.Devices.Bluetooth;
using Windows.Devices.Enumeration;

internal static class Pairing
{
    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
    private struct DeviceInfo
    {
        public uint size;
        public ulong address;
        public uint deviceClass;
        public int connected, remembered, authenticated;
        // Two SYSTEMTIME structures, each containing eight 16-bit fields.
        [MarshalAs(UnmanagedType.ByValArray, SizeConst = 16)] public ushort[] times;
        [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 248)] public string name;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct Search
    {
        public uint size;
        public int authenticated, remembered, unknown, connected, inquiry;
        public byte timeoutMultiplier;
        public IntPtr radio;
    }

    [DllImport("bthprops.cpl", SetLastError = true)]
    private static extern IntPtr BluetoothFindFirstDevice(ref Search search, ref DeviceInfo info);
    [DllImport("bthprops.cpl", SetLastError = true)]
    private static extern bool BluetoothFindNextDevice(IntPtr search, ref DeviceInfo info);
    [DllImport("bthprops.cpl")]
    private static extern bool BluetoothFindDeviceClose(IntPtr search);
    [DllImport("bthprops.cpl")]
    private static extern int BluetoothAuthenticateDeviceEx(IntPtr parent, IntPtr radio, ref DeviceInfo info, IntPtr oob, int protection);

    public static object PairPhone(string raw)
    {
        var hex = raw.Replace(":", "").Replace("-", "");
        if (hex.Length != 12 || !ulong.TryParse(hex, System.Globalization.NumberStyles.HexNumber, null, out var address))
            throw new ArgumentException("The phone did not report a valid Bluetooth address.");
        var search = new Search { size = (uint)Marshal.SizeOf<Search>(), authenticated = 1,
            remembered = 1, unknown = 1, connected = 1, inquiry = 1, timeoutMultiplier = 6 };
        var info = new DeviceInfo { size = (uint)Marshal.SizeOf<DeviceInfo>(), times = new ushort[16], name = "" };
        var handle = BluetoothFindFirstDevice(ref search, ref info);
        if (handle != IntPtr.Zero) {
            try {
                do {
                    if (info.address != address) continue;
                    if (info.authenticated != 0)
                        return new { paired = true, note = "Paired. Waiting for the Windows media endpoint." };
                    // Null out-of-band data delegates numeric comparison to the OS wizard.
                    var error = BluetoothAuthenticateDeviceEx(IntPtr.Zero, IntPtr.Zero, ref info, IntPtr.Zero, 3);
                    if (error == 0 || error == 259)
                        return new { paired = true, note = "Paired. Waiting for Windows to install the media endpoint." };
                    return new { paired = false, note = $"Windows pairing: {new Win32Exception(error).Message} ({error}). Open Bluetooth settings and retry." };
                } while (BluetoothFindNextDevice(handle, ref info));
            } finally { BluetoothFindDeviceClose(handle); }
        }
        return new { paired = false, note = "Windows could not discover this iPhone. Keep Settings > Bluetooth open on it, then retry audio." };
    }

    public static async Task<Endpoint[]> AudioDevices()
    {
        const string container = "System.Devices.ContainerId";
        var properties = new[] { container, "System.Devices.Aep.DeviceAddress" };
        var paired = await DeviceInformation.FindAllAsync(BluetoothDevice.GetDeviceSelectorFromPairingState(true), properties, DeviceInformationKind.AssociationEndpoint);
        var endpoints = await DeviceInformation.FindAllAsync(Windows.Media.Audio.AudioPlaybackConnection.GetDeviceSelector(), properties);
        var rows = endpoints.Select(d => {
            var address = d.Properties.GetValueOrDefault("System.Devices.Aep.DeviceAddress")?.ToString();
            if (address == null && d.Properties.GetValueOrDefault(container) is Guid id && id != Guid.Empty) {
                var peer = paired.FirstOrDefault(p => Equals(p.Properties.GetValueOrDefault(container), id));
                address = peer?.Properties.GetValueOrDefault("System.Devices.Aep.DeviceAddress")?.ToString();
            }
            // Windows' BTHENUM A2DP interface includes the classic device address.
            var match = System.Text.RegularExpressions.Regex.Match(d.Id, @"&0&([\dA-F]{12})_", System.Text.RegularExpressions.RegexOptions.IgnoreCase);
            return new Endpoint(d.Id, d.Name, address ?? (match.Success ? match.Groups[1].Value : null));
        }).ToArray();
        return rows;
    }
    public record Endpoint(string id, string name, string? address);
}

using System.Buffers.Binary;
using System.Text;

namespace Pane.Bluetooth;

public static class Protocol
{
    // Report ID 1: three buttons, relative X/Y, vertical wheel.
    public static readonly byte[] MouseMap = Convert.FromHexString(
        "05010902A10185010901A10005091901290315002501950375018102" +
        "95017505810305010930093109381581257F750895038106C0C0");

    public static byte[] Mouse(int buttons, int dx, int dy, int wheel)
    {
        if (buttons < 0 || buttons > 7 || new[] { dx, dy, wheel }.Any(n => n < -127 || n > 127))
            throw new ArgumentException("Invalid mouse report.");
        return new[] { (byte)buttons, unchecked((byte)(sbyte)dx), unchecked((byte)(sbyte)dy), unchecked((byte)(sbyte)wheel) };
    }

    public static byte[] Attributes(uint uid)
    {
        byte[] data = { 0, 0, 0, 0, 0, 0, 1, 128, 0, 3, 0, 4 };
        BinaryPrimitives.WriteUInt32LittleEndian(data.AsSpan(1), uid);
        return data; // app id, title (128 bytes), message (1024 bytes)
    }
}

// ANCS Data Source is a fragmented stream, not one response per BLE packet.
public sealed class AttributeResponse(uint uid)
{
    private readonly List<byte> bytes = new();
    private static readonly byte[] Order = { 0, 1, 3 };

    public Dictionary<byte, string>? Feed(byte[] fragment)
    {
        if (bytes.Count + fragment.Length > 8192) throw new InvalidDataException("ANCS response too large.");
        bytes.AddRange(fragment);
        if (bytes.Count < 5) return null;
        var data = bytes.ToArray();
        if (data[0] != 0 || BinaryPrimitives.ReadUInt32LittleEndian(data.AsSpan(1)) != uid)
            throw new InvalidDataException("Unexpected ANCS response.");
        int pos = 5;
        var result = new Dictionary<byte, string>();
        foreach (byte attribute in Order)
        {
            if (pos + 3 > data.Length) return null;
            if (data[pos] != attribute) throw new InvalidDataException("Unexpected ANCS attribute.");
            int length = BinaryPrimitives.ReadUInt16LittleEndian(data.AsSpan(pos + 1));
            if (length > (attribute == 1 ? 128 : attribute == 3 ? 1024 : 4096))
                throw new InvalidDataException("ANCS attribute too large.");
            pos += 3;
            if (pos + length > data.Length) return null;
            result[attribute] = Encoding.UTF8.GetString(data, pos, length);
            pos += length;
        }
        if (pos != data.Length) throw new InvalidDataException("Unexpected trailing ANCS data.");
        return result;
    }
}

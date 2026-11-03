using Pane.Bluetooth;
using System.Text;

static void Check(bool condition, string message) { if (!condition) throw new Exception(message); }
static void Reject(Action action) {
    try { action(); } catch (ArgumentException) { return; } catch (InvalidDataException) { return; }
    throw new Exception("Invalid input accepted");
}

Check(Protocol.Mouse(1, -127, 127, -1).SequenceEqual(new byte[] { 1, 129, 127, 255 }), "Signed mouse encoding");
Reject(() => Protocol.Mouse(8, 0, 0, 0));
Reject(() => Protocol.Mouse(0, 128, 0, 0));
Check(Protocol.Attributes(0x12345678).SequenceEqual(Convert.FromHexString("007856341200018000030004")), "ANCS request framing");

var bytes = new List<byte> { 0, 0x78, 0x56, 0x34, 0x12 };
foreach (var (id, value) in new[] { (0, "com.apple.MobileSMS"), (1, "Hello 👋"), (3, "<script>untrusted text</script>") }) {
    var data = Encoding.UTF8.GetBytes(value);
    bytes.Add((byte)id); bytes.Add((byte)data.Length); bytes.Add((byte)(data.Length >> 8)); bytes.AddRange(data);
}
for (int split = 0; split < bytes.Count; split++) {
    var parser = new AttributeResponse(0x12345678);
    Check(parser.Feed(bytes.Take(split).ToArray()) == null, "Incomplete response accepted");
    var result = parser.Feed(bytes.Skip(split).ToArray());
    Check(result != null && result[1] == "Hello 👋" && result[3].StartsWith("<script>"), "Fragmented response lost data");
}
var single = new AttributeResponse(0x12345678);
Dictionary<byte, string>? last = null;
foreach (var b in bytes) last = single.Feed(new[] { b });
Check(last?.Count == 3, "Bytewise fragments");
Reject(() => new AttributeResponse(1).Feed(bytes.ToArray()));
Reject(() => new AttributeResponse(0x12345678).Feed(bytes.Concat(new byte[] { 0 }).ToArray()));
Reject(() => new AttributeResponse(0x12345678).Feed(new byte[8193]));
Reject(() => new AttributeResponse(0x12345678).Feed(Convert.FromHexString("0078563412000110")));
Console.WriteLine("Protocol tests passed: mouse limits, ANCS commands, all split points, UTF-8, malformed/oversized responses.");

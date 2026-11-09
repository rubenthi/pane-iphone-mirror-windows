# Performance evidence and budgets

## Existing application baseline

On 2026-11-08, the installed Pane (Development) 2.5.6 process family was sampled for 5.05 seconds while its screen state was `idle`:

| Metric | Observed |
| --- | ---: |
| Processes | 2 Pane + 6 WebView2 |
| Summed private committed memory | 455.3 MiB |
| Summed working set | 728.5 MiB |
| CPU | 3.4% of one logical CPU |
| Logical processors on laptop | 24 |
| Packaged executable | 82,939,647 bytes |

This is a short local sample, not a controlled benchmark. Summing working sets can count shared pages more than once; private committed memory is a different metric from resident private working set. It includes the identified process descendants, not unrelated Apple/system services. No phone state or settings were changed for measurement.

## Native shell measurement method

The native candidate is measured as a visible window after its one-shot
discovery completes, without a phone session, video decoding or file transfer.
Process CPU is the change in `TotalProcessorTime` divided by wall time,
expressed as a percentage of one logical CPU. Private committed memory and
working set are reported separately; Apple/system services are outside scope.

Initial 60-second samples showed 8.1–9.4% of one core while the computer-control
inspection runtime remained active. Temporary numeric counters then recorded
one scan, one main-window paint and 15,860 `WM_GETOBJECT` accessibility queries
in 34 seconds. After resetting the inspection runtime, a fresh visible process
measured zero CPU time at the counter's resolution over 20 seconds. This is an
observer effect, not evidence supporting removal of accessibility. Native
control semantics were preserved and the temporary counters removed. Final
measurements must be taken after that runtime reset, with no UI inspection
during the sample.

Final local sample on 2026-11-08, with temporary counters removed:

| Native shell metric | Observed |
| --- | ---: |
| Sample duration | 60.228 seconds |
| Application processes | 1 |
| CPU | 0.078% of one logical CPU |
| Private committed memory at end | 2.141 MiB |
| Peak sampled private committed memory | 2.238 MiB |
| Working set at end | 14.523 MiB |
| Executable | 269,824 bytes |

Executable SHA-256:
`3234032D6C1E2255AFFC466287138041A286A9F17666025AD1AAA9CFB1B926CE`.
The sampled shell meets the proposed idle CPU/private-memory budgets on this
laptop. These results exclude unfinished mirroring, decode, transfers, audio
and notification features and do not establish full-product savings.

## Proposed targets — not measured results

- Disconnected idle: one application process, under 50 MiB private committed memory, under 0.5% of one logical CPU averaged over 60 seconds, with no continuous UI/network polling.
- Rendering: use the display's native density and Windows hardware video decoding/composition. Do not increase network video dimensions solely to match display DPI.
- Frames: at most one pending frame and one being processed, with explicit byte limits. Replace obsolete pending frames instead of building latency and memory in an unbounded queue.
- Transfers: bounded streaming buffers, bounded in-flight data, no whole-file memory copies; measure upload throughput separately from video FPS.
- Lifecycle: stop decode, capture, scans, timers and transfers that are not required by an enabled feature. Background notifications must not keep the full desktop UI running.

Use Rust for the native host and Swift for Apple-platform work where appropriate. Measure allocator usage, process memory, CPU, GPU, startup, frame latency and transfer throughput before claiming an improvement. Native language choices alone do not establish faster or lighter behavior.

A disconnected shell prototype must not be compared with the full mirroring product as if it demonstrated equivalent performance. Repeat the same idle and connected workloads on the final candidate before release.

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

## Proposed targets — not measured results

- Disconnected idle: one application process, under 50 MiB private committed memory, under 0.5% of one logical CPU averaged over 60 seconds, with no continuous UI/network polling.
- Rendering: use the display's native density and Windows hardware video decoding/composition. Do not increase network video dimensions solely to match display DPI.
- Frames: at most one pending frame and one being processed, with explicit byte limits. Replace obsolete pending frames instead of building latency and memory in an unbounded queue.
- Transfers: bounded streaming buffers, bounded in-flight data, no whole-file memory copies; measure upload throughput separately from video FPS.
- Lifecycle: stop decode, capture, scans, timers and transfers that are not required by an enabled feature. Background notifications must not keep the full desktop UI running.

Use Rust for the native host and Swift for Apple-platform work where appropriate. Measure allocator usage, process memory, CPU, GPU, startup, frame latency and transfer throughput before claiming an improvement. Native language choices alone do not establish faster or lighter behavior.

A disconnected shell prototype must not be compared with the full mirroring product as if it demonstrated equivalent performance. Repeat the same idle and connected workloads on the final candidate before release.

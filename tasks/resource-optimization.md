# Resource optimization, preserving rendering

Keep every Gaussian, exact floating-point depth ordering, SH lighting, full textures, export resolution and video encoding quality. Optimize only repeated work and allocation; never substitute sampling or lower quality.

1. Measure the full 13,026,917-Gaussian bridge with the existing 1.10.1 binaries. Save reference pixels, process memory, CPU and elapsed time.
2. Stop redundant stationary viewer draws while continuing event polling, keyboard navigation, paging, dynamic scene updates, overlays, resize and snapshot requests. Hidden/minimized views resume correctly.
3. Reduce bounded cache-read overhead and unnecessary sorting/SH updates. Validate unchanged pixels and rejected malformed data.
4. Run regression and actual full-scene comparisons, moving video and viewer interaction/paging checks. Report measured resource changes without extrapolating to other hardware.
5. Package 1.10.2, inspect it and publish the tested portable build.

Acceptance: stationary render count settles; camera/clip/snapshot/page arrivals wake the viewer; saved frames match the reference; full point count and original crop/export properties remain intact. No increased active render time or peak memory in the controlled bridge check.

# 1.10.2 resource-efficiency verification

Date: 2026-11-16. Windows x64, RTX 4080 SUPER / 16 GB, 64 GB system RAM. Compare against the released 1.10.1 native executables. Controlled native workloads used the same CPU affinity in both versions; this is a test setting, not an application restriction.

## Preserved rendering

All 13,026,917 Gaussians in the actual bridge remain loaded. No point sampling, opacity/size multiplier, depth quantization, texture resizing, framebuffer reduction or encoding-quality change is introduced. Original sources and exports are not rewritten by this optimization.

The 13-frame bridge reference sequence combines 12 translated views with a final turn at 1280x720. All 35,942,400 output color-channel bytes are identical between releases. Both stationary viewer screenshots also match exactly. SH0, SH1, SH2 and SH3 were independently compared against 1.10.1 over 10 perspective/orthographic translated, turned and rolled views per degree, with random nonzero coefficients: zero differing channels in every comparison.

## Measured bridge workload

| Measurement | 1.10.1 | 1.10.2 |
|---|---:|---:|
| 13-frame native render wall time, including load | 7.595 s | 4.030 s |
| Native process CPU time for that sequence | 6.891 s | 3.578 s |
| Peak process commit for that sequence | 2,558,599,168 B | 2,560,389,120 B |
| Viewer loading to ready | 3.437 s | 2.391 s |
| Viewer CPU time during 6 seconds stationary | 0.641 s | 0.344 s |

The improved viewer's render counter remained at 2 throughout the stationary interval: no repeated full-scene drawing. GPU memory still holds the complete scene for immediate interaction. Bridge peak commit is effectively unchanged; no RAM reduction is claimed for this SH0 scene. Times vary with hardware, camera path, driver and background work. Translating a fixed viewing axis benefits more than turning it continuously.

## Changes and checks

- On-demand viewer drawing continues event polling, camera movement, dynamic scene updates, paging and GL compilation. Camera/clip changes, measurement/polygon overlays, snapshots, resize and restored windows trigger rendering. Hidden/minimized viewports suspend drawing. New paged geometry receives its original display materials after update traversal.
- Native cache reads use bounded blocks of 65,536 records instead of an individual stream read per point; every field remains validated, including the last record of a second block.
- Gaussian depth order is reused only when the viewing axis is exactly equal. Turning still executes the unchanged stable full-float sorting algorithm. Perspective SH is updated as the camera moves; parallel orthographic SH can reuse colors with unchanged direction. No angular tolerance or stale approximation is used.
- SH runtime arrays store the active degree's coefficients: 12 floats per SH1 Gaussian, 27 for SH2 and 48 for SH3, instead of always reserving 48. SH1 coefficient storage falls 75%; SH2 falls 43.75%. An unused 16-byte-per-Gaussian color copy is also removed for higher SH degrees. These percentages concern coefficient arrays, not total process memory. Cache/source formats and their full property records stay compatible.
- 208 regressions passed in 73.391 seconds. An additional final 22-check viewer/navigation run passed after refining mouse-down invalidation. Native protocol tests cover stationary sleep, paged mesh loading/materials, camera/clip changes, real snapshots, window resize and hide/restore. Exact depth ordering, point records, texture fidelity, clipping, inspection and video regressions also pass.
- The actual full bridge exported a 3840x2160 / 60 fps, 60-frame MP4. Frame count, dimensions, duration and complete decoding passed. It contains all 13,026,917 Gaussians; peak native process commit was 2,727,419,904 bytes. The complete export, including original-source preparation and verification, took 77.36 seconds. This validates 4K60 output and does not claim realtime rendering.
- Native Release and portable PyInstaller builds completed successfully.
- The final portable application opened the original bridge, loaded and played a saved camera path, and responded to a real mouse orbit. Its cache retained all 13,026,917 source Gaussians with `sampled=false`; after playback stopped, its actual viewer counter remained at 25 across the checked idle interval.

Evidence: local `validation/resource1102`, including reference executables, raw pixels, metrics, SH comparisons, tests and verified video metadata. Model data and test media are excluded from the public software distribution.

The demand loop was checked against the [OpenSceneGraph 3.6.5 viewer implementation](https://github.com/openscenegraph/OpenSceneGraph/blob/OpenSceneGraph-3.6.5/src/osgViewer/Viewer.cpp), including scene-update, redraw and event checks. No new runtime dependency was added.

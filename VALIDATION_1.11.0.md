# 1.11.0 large-scene and video recovery verification

2026-11-16, Windows 11, RTX 4080 SUPER / 16 GB, i9-14900KF, 64 GB RAM.

## Actual reported failure

The blade-factory source contains 21,579,838 SH0 Gaussians. Its failed task requested 30 seconds at 3840x2160 / 60 fps, 1,800 camera frames. Persistent progress stopped around frame 71 with an empty encoder error. Windows Application Error 1000 identifies ffmpeg.exe access violation `0xC0000005`; the evidence does not establish an out-of-memory failure or the underlying library/instruction responsible for the access violation.

The complete original diagnostic job and camera frames were preserved locally. The original source and user files were not overwritten.

## Complete sorting and rendering

The new optional GPU path computes every original float32 depth key, performs eight stable radix passes, and draws with GPU-resident indices. It preserves all Gaussians and original-record ties. CPU multicore sorting remains available for unsupported hardware, allocation limits and incompatible numeric ranges. The first GPU operation checks driver arithmetic; subgroup mapping is checked before its result is accepted. Normal/subnormal range safeguards retain the CPU reference where GPU flush-to-zero behavior could change the result.

The original OSG float dot product converts its RHS to Vec3f. GPU operations explicitly match this conversion and left-associated float operations; they are not contracted into different arithmetic. The splat compositor, covariance, clipping, opacity, color activation, framebuffer and source/export data remain unchanged.

Independent full-array comparison against the original CPU comparator passed on all 21,579,838 source indices at the original first, middle and last camera views. A separate 24-view changing-axis sequence matches all 16,588,800 color-channel bytes against 1.10.2. GPU unit tests also cover ties, signed zero, mixed-axis views, prefix hierarchy, non-multiple workgroup counts, SH0–SH3, and exact CPU fallback for subnormal coordinates.

Controlled native 640x360, 24-view source workload, including loading:

| Path | Seconds |
|---|---:|
| Released 1.10.2 CPU path | 14.516 |
| Four-worker CPU prototype | 11.672 |
| Eight-worker CPU prototype | 9.641 |
| Final complete GPU path | 5.563 |

The final run spent 0.591 seconds in sorting/initialization and 1.055 seconds in frame draw/readback calls. These are workload timings, not universal interaction or 4K realtime frame-rate claims. GPU scratch for this source is 701,387,160 bytes (about 669 MiB). Scratch shifts work to available VRAM; it does not make complete scene storage free. Allocation/compatibility failures preserve complete CPU rendering instead of reducing scene detail.

## Video recovery and complete task checks

Hardware encoding is probed with a supported 256x256 frame and a bounded timeout. The initial 128x128 probe was rejected by this driver's minimum frame dimensions and was corrected before release. Successful hardware detection selects H.264 NVENC HQ / QP 16; otherwise the existing H.264 CRF 18 software path remains. An encoder crash or hardware encoder failure has one compatible software retry with the original render request. Memory failures and cancellation retain their distinct handling.

Encoder commands, return codes and process metadata now persist with failure diagnostics, including an empty-stderr `0xC0000005` crash. Compatibility flags disable fragile optimized code paths without changing frame dimensions, camera frames or scene data. Final videos are published only after complete frame-count, duration, dimensions, codec and full decoding checks.

The actual original 1,800-frame job passed twice:

| Encoder | Resolution / rate | Frames / duration | Complete export and verification |
|---|---|---|---:|
| Software H.264 CRF 18 | 3840x2160 / 60 fps | 1,800 / 30.000 s | 481.50 s |
| Hardware H.264 NVENC HQ, QP 16 | 3840x2160 / 60 fps | 1,800 / 30.000 s | 378.34 s |

Both retained all 21,579,838 Gaussians and passed full decoding. The hardware export used one successful attempt. The compatible software command was also checked on actual rendered frames; crash/retry bounds, preserved inputs, cancellation and hardware probe timeout are covered by subprocess tests. H.264 output remains compressed video; rendered-frame equality refers to pre-encoding pixels.

## Regression and distribution

218 regressions passed in 78.068 seconds. A final three-test real viewer run passed after exposing internal resource diagnostics, covering CPU/GPU clipping, snapshots, resize, hidden-window restore, stationary redraw and paged material loading. Native Release and portable builds include the existing runtime libraries; no CUDA/PyTorch package or extra SDK installation is required for the optional GPU path.

The packaged application loaded the original blade source and played the recovered viewing segment. A real mouse orbit was exercised. Its live state confirms GPU sorting, all 21,579,838 Gaussians and no sampling; the render counter stayed at 38 during the idle check. The freshly prepared 1.11.0 display cache matches the original task's full cache byte-for-byte. Earlier application windows and their unsaved work were preserved.

Local evidence is under `validation/large113`, with completed test videos in the workspace output directory. Models, raw frames, recovered camera diagnostics and test videos are excluded from the public software package.

Design references: [Khronos subgroup specification](https://registry.khronos.org/OpenGL/extensions/NV/NV_shader_thread_group.txt), [NVIDIA FFmpeg guide](https://docs.nvidia.com/video-technologies/video-codec-sdk/13.0/ffmpeg-with-nvidia-gpu/index.html), and the bundled OpenSceneGraph 3.6.5 headers. See `docs/decisions/0001-complete-gpu-gaussian-order.md` for boundaries and fallback behavior.

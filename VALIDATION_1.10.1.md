# 1.10.1 Gaussian display verification

Date: 2026-11-16. Windows x64, NVIDIA RTX 4080 SUPER / 16 GB, 64 GB system RAM.

## Reproduction and cause

The actual 深职院天桥_epoch_50.ply contains 13,026,917 SH0 Gaussians in 885,831,275 bytes, with 17 scalar properties. The old preview reused the ordinary point-cloud 300,000-point cap: stride 44 retained only 296,067 Gaussians (2.27%). Removing the other Gaussian contributions changed both coverage and accumulated opacity, producing the reported dark, sparse, transparent appearance.

The old behavior was reproduced from the original file and saved before implementation. Full and sampled renders use the same camera, opacity, activated scales, normalized quaternions, RGB, and renderer. The full scene produces continuous bridge surfaces, roads, foliage and buildings; no brightness or opacity multiplier was added. Original reconstruction artifacts remain visible at some viewpoints.

## Fix

- Gaussian preview and full rendering both retain all original Gaussians. Ordinary point previews retain their existing sampling policy.
- SH0 cache records use 14 floats instead of reserving 62. This scene's complete cache is 729,507,352 bytes instead of 3,230,675,416 bytes for a 62-float full cache. This changes display cache storage only; source PLY and crop output retain every property. Legacy 62-float Gaussian caches remain readable, and SH1–SH3 keep their existing layout.
- Stable full-precision radix depth sorting preserves the previous comparator's far-to-near ordering and original-record tie order, including negative depths and signed zero. On all 13,026,917 source positions, its output exactly matched the comparison sort. Measured sorting time was 0.151 seconds versus 1.268 seconds on this machine; this is a sorting measurement, not a whole-application frame-rate claim.
- Viewport rejection checks the complete projected Gaussian footprint. Centers outside the viewport may still contribute visible tails. The actual scene comparison before/after this rejection differed by at most one 8-bit display level; no coverage loss was observed.
- Orthographic projection uses a depth-independent Gaussian Jacobian and parallel viewing directions for SH evaluation, preventing splats from shrinking with camera distance in polygon-drawing top views.

## Checks

- 201 regression tests passed in 78.299 seconds. New checks reproduce the preview-cap failure, ensure all opacity contributions remain, verify compact/legacy pixel equality, compare native depth ordering against an independent comparator, and verify orthographic footprint invariance with camera depth. Existing clipping, splat tails, SH, HDR, point records, texture, wall inspection and video checks pass.
- Real full-scene cache: count and source_count both equal 13,026,917; sample_stride is 1 and sampled is false. Preparing it took 18.69 seconds in the development check.
- Six actual full-scene camera angles were inspected, and a same-camera sampled/full comparison was saved. No source-data cleanup or ellipsoid changes were applied.
- A full-detail 1920×1080 / 30 fps camera video rendered all 30 frames and passed duration, frame-count and complete decoding checks. Total export time was 50.78 seconds including preparation and verification. Native process peak commit was 2,536,849,408 bytes in that run.
- A rotated concave polygon exported 825,855 original Gaussians. An independent winding-angle selection yielded the same count and byte-identical records, including all 17 fields. Reopened preview retained all 825,855 Gaussians. Source SHA-256 before/after cropping remained `84e6a192f9e6140c6551b0060285beec9ed380853aa05cd626a65171c7621af1`.
- Native and portable PyInstaller builds completed successfully. Runtime still requires OpenGL 3.2 / GLSL 1.50. Full display uses more resources than the old sampled preview, and interaction speed depends on GPU, source size and projection footprint.

Development evidence is under `validation/bridge1101`; local comparison images, video and cropped PLY are under `output/高斯显示修复验证_1.10.1`. Source models are not bundled in the software distribution.

## Reference check

Existing SH activation, quaternion/covariance, low-pass filtering and alpha-compositing conventions were checked against the [original rasterizer's mathematical implementation](https://github.com/graphdeco-inria/diff-gaussian-rasterization/blob/main/cuda_rasterizer/forward.cu). No source from that repository or new dependency was bundled for this fix.

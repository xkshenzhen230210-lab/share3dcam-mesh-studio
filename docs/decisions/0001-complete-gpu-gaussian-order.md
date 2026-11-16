# Complete GPU Gaussian ordering with CPU fallback

Accepted, 2026-11-16.

The 21.6-million-Gaussian case remained slow during changing-axis camera motion after idle redraw and fixed-axis reuse were optimized. Geometry/texture quality, every Gaussian and stable floating-point depth order must be retained.

Use an optional OpenGL 4.3/NVIDIA subgroup radix sorter. Eight four-bit passes retain all 32 float depth bits. Hierarchical global prefix sums and subgroup ranks preserve original-record ties across workgroups. The generated element indices remain on the GPU and feed the existing splat compositor, avoiding per-camera CPU sorting and index uploads. Keep the original compositor, projection, activation and clipping behavior.

GPU arithmetic matches `osg::Vec3f::operator*`, including float conversion of its RHS, left-associated float operations and signed-zero canonicalization. Startup checks driver arithmetic; subgroup mapping is checked before its result can be drawn. A conservative range guard delegates subnormal/underflow-sensitive inputs to CPU. Complete independent CPU-reference verification is available for tests.

Unsupported hardware, shader/buffer limits and failed compatibility checks retain complete CPU rendering. The CPU fallback partitions stable radix sorting across at most eight available processors; small workloads remain serial. No process-wide single-core pin is imposed by the viewer.

GPU scratch adds roughly 32 bytes per Gaussian, plus prefix buffers, while eliminating CPU sort buffers on the fast path. The blade case uses about 669 MiB of GPU scratch. Allocation is checked and partial buffers are released before CPU fallback. A point scene owns one immutable cache in one native viewer/render context; context teardown reclaims GL objects when they cannot be explicitly released in their owning context.

Rejected: preview thinning or coarse depth bins change opacity and ordering; asynchronous stale camera ordering can display incorrect blends. CPU multicore sorting helps unsupported GPUs but retains memory-transfer costs. A CUDA/PyTorch runtime would add substantial deployment requirements; this implementation adds no runtime package dependency.

Separately, an ffmpeg `0xC0000005` crash requires exit diagnostics and bounded encoder recovery. Probe NVENC with a driver-supported 256x256 frame, select high-quality H.264 encoding, and retry a failed encoder once with compatible software settings while preserving render inputs. The selected encoder and actual quality mode are reported. H.264 remains a compressed video deliverable; rendered-frame equality is verified before encoding.

References: [Khronos NV shader thread groups](https://registry.khronos.org/OpenGL/extensions/NV/NV_shader_thread_group.txt), [NVIDIA FFmpeg encoding guide](https://docs.nvidia.com/video-technologies/video-codec-sdk/13.0/ffmpeg-with-nvidia-gpu/index.html), and the bundled OSG 3.6.5 Vec3f/State/GLExtensions headers.

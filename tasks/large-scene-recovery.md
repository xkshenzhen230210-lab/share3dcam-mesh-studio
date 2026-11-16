# Large scene interaction and encoder crash recovery

Reproduce the original 30-second 3840x2160/60 fps blade-factory job and preserve its diagnostics. Windows reports ffmpeg access violation 0xc0000005 after roughly 71 frames; do not label this as an out-of-memory error.

1. Diagnose encoder subprocesses with exit codes and durable command/log metadata; support bounded compatible encoding recovery without changing camera frames, resolution or scene detail.
2. Profile actual blade data during changing-axis camera motion. Parallelize exact stable full-float Gaussian sorting if measured faster; keep serial compatibility and independent order/pixel equivalence checks. Avoid sampling or deferred incorrect camera ordering.
3. Verify the complete original 1800-frame video, frame count, duration and full decode. Check actual viewer input latency and rotating scenes, then run regressions and package the tested release.

Do not overwrite sources, user camera plans or existing output videos. Test media and source data stay local.

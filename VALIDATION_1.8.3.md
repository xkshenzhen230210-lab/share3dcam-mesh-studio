# 1.8.3 continuous camera motion

Date: 2026-11-06.

## Reproduction and change

The supplied video is an 8.93-second, 1280 x 720, 30 fps orbit around a scanned statue. Its original keyframe JSON was not saved; the user authorized testing with the currently open model, Xiruiyuan Building 6 LAS.

The old camera evaluator applied smoothstep separately to every adjacent key pair. Thus translation, orientation and zoom reached zero velocity at every intermediate key; angular and positional acceleration also changed abruptly. Three new regression checks failed before the fix: continuous through-key velocity, acceleration continuity and gentle endpoint acceleration.

The replacement uses time-aware shared tangents and quintic Bezier curves. Quaternion control pairs and spherical de Casteljau preserve continuous angular velocity and acceleration. Position, log camera distance and field of view use matching quintic curves. Beginning and end velocities and accelerations are zero; intermediate keys are passed continuously unless the recorded motion is a hold or reversal. Scalar control points preserve the recorded interval bounds, and vector handles are limited by neighbouring speed and distance. Original key poses and timestamps are returned exactly.

Repeated poses remain stationary, including orientation; there is no global spline drift during a hold. A bounded cache uses immutable key values, so editing a key cannot reuse an obsolete path. Preview and export use the same compiled evaluator. Version 1 and 2 animation JSON files continue to load and receive the improved interpolation.

## Verification

- All 179 automated tests passed in 61.859 seconds. Eight new motion tests cover nonzero middle-key translation and turning, continuous acceleration, combined roll/pitch/yaw, exact key poses, holds, large world coordinates, nonuniform intervals, bounded zoom and field of view, and retiming/cache invalidation. Existing preview/export timing, 3600-frame minute, cancellation and output-protection tests remain passing.
- An initially coarse one-sided acceleration estimate at a join differed by 0.0996 at a 1 ms step. Refining the step to 0.1 ms and 0.01 ms reduced the difference to 0.00999 and 0.00102, confirming convergence rather than an acceleration discontinuity. The regression uses the finer step with the original error bounds.
- On the actual five-key, 12-second orbit, a symmetric one-frame measurement around 3, 6 and 9 seconds gives 0.332 degrees/second for the old evaluator and 20.001 / 20.000 / 20.001 degrees/second for the new evaluator. Preparing all 720 camera frames took 0.71 seconds in this measurement.
- The portable 1.8.3 build completed successfully. No new production dependency was added.
- The current Xiruiyuan Building 6 LAS (13,102,445 source points) was rendered with five keys at 0, 3, 6, 9 and 12 seconds. The roof was clipped for an interior view. The full-resolution render produced a 12-second, 3840 x 2160, 60 fps MP4 with exactly 720 decoded frames; error-strict full decoding passed. Twelve sampled views were inspected for framing and orientation. Frame differences remained nonzero through all three intermediate joins, with no frozen frames in the middle of the movie. The source SHA-256 remained unchanged: `1dbc52936ab4e921d7985ed76f7c1f696863a09d034ac3a2938b1ed7e7de1215`.
- The packaged 1.8.3 GUI opened the same LAS and loaded the saved five-key plan. Playback reached 12.00 seconds, and dragging the timeline to 6.05 seconds changed the native view correctly. A second export was initiated through the packaged GUI at 1920 x 1080 / 60 fps. It completed successfully with exactly 720 decoded frames and a 12-second duration; error-strict full decoding also passed. The GUI was left open with the model and keyframes loaded, at 4K / 60 fps / 1x settings.

Actual render artifacts are in `../output/连续运镜验证_1.8.3/`, including the 4K video, lightweight preview, saved camera plan and packaged-GUI export. Detailed local checks are in `validation/video183/` (test log, camera speed comparison, frame-difference check and render metadata).

Review covered quaternion sign continuity, shortest adjacent key arcs, valid orthonormal camera bases, positive camera distance, field-of-view bounds, immutable caching, retiming invariance and unchanged native rendering. The test suite uses SciPy's Rotation as an independent rotation representation; production interpolation uses NumPy.

Curved interpolation intentionally changes the route between exact key poses. Very sharp reversals must slow down, and a path in a confined space should be previewed with additional keys where necessary. This is camera interpolation, not obstacle avoidance or reconstruction of the unsaved source video's original camera path.

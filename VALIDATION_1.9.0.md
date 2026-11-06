# 1.9.0 automatic horizontal alignment

Verified on 2026-11-06 with Windows x64 and NVIDIA RTX 4080 SUPER.

## Behavior

New model and point-cloud imports default to a horizontal working direction inferred from the minimum-area footprint rectangle. The long side follows the clipping box X axis. Top/front/right views, box focus, picking, mesh planes and point shaders use the same frame. Auto align can be disabled to restore the original axes; switching resets the selection. Source geometry is not rotated or rewritten. Exports retain source coordinates, and camera keyframes retain their existing world-coordinate convention.

## Verification

- 187 automated tests passed in 60.544 seconds after the final native build. Coverage includes rotated triangles and UV interpolation, unchanged interior vertices, large coordinates, old box compatibility, native alignment at five rotations, native point pixels, LAS record bytes, selected-wall analysis, and the existing conversion/video/wall suites.
- The actual 13,102,445-point 溪瑞苑6栋 LAS opened with a -39.54861065 degree working direction. Its building edges and orange box aligned in top view. Disabling and re-enabling Auto align restored the original direction and the detected direction respectively, with the selection reset.
- A half-width selection was exported through the GUI: 6,691,516 original points. An independent source-coordinate selection calculation and SHA-256 comparison confirmed identical complete point records, including all extra fields. The original LAS SHA-256 remained `1dbc52936ab4e921d7985ed76f7c1f696863a09d034ac3a2938b1ed7e7de1215`.
- A 2-second 1920×1080 / 30 fps video of that oriented LAS selection rendered all 60 frames, passed frame-count/duration and full decoding checks, and showed the same straight crop boundary as the viewer.
- 藏经阁 OSGB geometry detected a 5.436002 degree direction. A 4×4 working-coordinate selection was exported from its original complete subtree to OBJ and OSGB: 2,530 triangles, 7,590 vertices and 3 materials. All exported vertices remained within the oriented selection in original coordinates. Background verification passed geometry, UVs, indices, groups and all 3 texture byte streams without repairs. The OBJ was reopened successfully with textures and its detected direction remained consistent.
- A 1-second 1920×1080 / 30 fps video of the cropped mesh passed all 30 frames and full decoding checks.
- The portable PyInstaller build succeeded. The native viewer/render binaries in the package match the final tested runtime binaries.

Validation artifacts and sample exports are saved under `output/自动摆正验证_1.9.0` and `validation/alignment190` in the development workspace.

## Review and limits

The shared ClipBox descriptor validates finite bounds/origin/yaw and retains six-number legacy boxes. Native mesh extraction uses a conservative world-axis broad phase followed by exact oriented triangle clipping. Point clipping preserves selected records; no coordinate baking, scaling, sampling or new production dependency was added. GPU clipping rebases around the point-cache origin before float conversion. Old sampled caches infer orientation before adding conservative source extents, so bounding corners cannot force a zero angle.

This estimates horizontal geometric direction, not semantic walls or gravity. Source Z should already be upright. Point footprints include all source points; mesh footprints use loaded coarse preview geometry. Irregular shapes and distant outliers can affect the inferred direction. Users can return to original axes. The unit and interpretation of wall reports are unchanged.

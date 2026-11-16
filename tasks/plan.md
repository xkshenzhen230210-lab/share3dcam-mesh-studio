# Full Gaussian preview repair

Reproduce the reported sparse bridge rendering from its original 13,026,917-Gaussian PLY. Preserve the sampled output as evidence, then remove Gaussian thinning while keeping ordinary point sampling. Compact SH0 display cache records without changing source/export records. Preserve exact depth sorting while replacing its scaling cost, retain visible offscreen tails, and correct orthographic splat projection.

Check exact native depth-order equivalence, opacity contributors, compact/legacy pixels and orthographic size. Compare the same original scene and camera before/after, export and decode a complete video, verify original crop record bytes, run regression tests, package and inspect the fixed application.

## Previous polygon selection follow-up

Add an optional simple XY polygon to the existing oriented clipping descriptor. Use inclusive center filtering for original point records; triangulate concave outlines and clip mesh faces with source-space attribute interpolation. Keep old boxes compatible.

Provide native top-view click drawing with draft/committed separation, undo, cancel and closure validation. The GUI exposes Draw/Finish/Undo/Cancel/Clear, polls native revisions, disables conflicting navigation and exports while drawing, and applies polygon bounds to existing export, selected-wall and video paths. Use a single fragment-discard pass for native meshes and center filtering for points, preserving textures and original coordinates.

Verify concavity, invalid inputs, internal diagonal face ownership, point bytes, Gaussian properties, native pixels, actual LAS and OSGB exports/videos, packaged UI and archive integrity.

## Previous automatic horizontal alignment

Default to a horizontal working frame whose X axis follows the long side of the footprint's minimum-area rectangle. Preserve source coordinates and records. Align the clipping volume and standard views to this frame, so the scene appears straight without rewriting geometry. An Auto align checkbox restores original axes by reopening the prepared preview; it resets the clipping selection but keeps world-coordinate camera keys compatible.

1. Add a backwards-compatible oriented clipping descriptor: bounds in a horizontal frame, double-precision origin and yaw in degrees. Keep existing six-number boxes valid. Verify triangle clipping, point-record preservation and conservative native extraction bounds.
2. Obtain footprint hulls while preparing point caches and while visiting coarse mesh geometry. Native viewer uses the resulting frame for bounds, box planes, picking, standard cameras and box focus. Native video uses the identical clipping frame. Check synthetic rotations and native rendering.
3. Connect default automatic alignment and a restore toggle in the clipping panel. Propagate the descriptor to mesh/point export, video and selected-wall analysis. Full automatic wall analysis remains in original source coordinates.
4. Run regression tests and actual LAS/mesh preview, crop and video checks; package and open the new release.

Accuracy: horizontal rotation only; no scale, resampling, tilted floor or source overwrite. Full point-record filtering and triangle UV interpolation operate in the oriented selection but outputs stay in original coordinates. Degenerate footprints fall back safely. Detection reflects the footprint and is not semantic wall recognition.

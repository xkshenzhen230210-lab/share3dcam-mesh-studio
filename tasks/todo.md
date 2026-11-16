# Gaussian display repair acceptance

- [x] Reproduce the original bridge file and identify the stride-44 Gaussian preview loss.
- [x] Keep every Gaussian without opacity/size compensation; ordinary point sampling unchanged.
- [x] Verify compact-cache pixels, exact stable depth order, offscreen tails and orthographic splat size.
- [x] Inspect actual same-view renders; decode full-scene video; preserve all 17 source crop fields.
- [x] Run 201 regressions and build native/portable components.
- [x] Inspect the packaged application and verify its distribution archive.

## Previous polygon selection acceptance

- [x] Preserve legacy boxes and original coordinates; validate and triangulate concave simple polygons.
- [x] Verify LAS and Gaussian PLY record preservation, UV interpolation and no duplicate diagonal faces.
- [x] Native point and textured mesh pixels match the selected polygon.
- [x] Draw/finish/right-click undo/Escape cancellation work on the actual LAS.
- [x] Actual LAS and OSGB exports and videos pass independent checks.
- [x] Package and verify the new portable application and archive.

## Previous automatic alignment acceptance

- [x] Oriented clipping accepts old and new boxes, preserves world geometry and point records; targeted tests pass.
- [x] Viewer frame handles mesh, LAS, PLY, picking and standard views; renderer uses matching planes.
- [x] Auto align defaults on; switching to original axes resets the selection clearly; wall and export paths receive the same selection.
- [x] Full tests and native build pass; actual data aligns and selected output matches preview.
- [x] Document, package, verify archive, and leave the new version open.

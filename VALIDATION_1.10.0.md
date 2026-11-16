# 1.10.0 polygon crop verification

Date: 2026-11-16. Windows x64, NVIDIA RTX 4080 SUPER.

## Behavior and compatibility

Draw starts an orthographic horizontal top-view outline, avoiding height-dependent perspective shifts; the wheel adjusts its scale. Left clicks append vertices; Enter, the Finish button, or clicking the first vertex closes it. Right click / Backspace removes the last vertex. Escape / Cancel abandons the draft and preserves the committed outline. Clear restores the box. Camera rotation and crop export are disabled during drawing. New drawings preserve the previous committed outline until completion; opening a model or changing the horizontal frame resets it. Z min/max controls the height; XY controls are disabled while a polygon determines the boundary.

Concave simple polygons with 3–128 vertices are supported. Self intersections, repeated vertices and zero-area outlines are rejected. This is a vertical polygon prism, without holes or arbitrary tilt. Mesh cut surfaces remain open. Point/Gaussian selection uses original centers; retained Gaussian tails may cross the boundary.

The existing ClipBox descriptor now optionally includes `polygon`, with XY vertices in the same horizontal working frame as `bounds`. Legacy lists and oriented boxes remain compatible. Mesh export, native mesh/point preview, video, and selected-wall analysis use the descriptor. Source coordinates, original point records and original texture bytes are preserved. Automatic whole-source wall inspection retains its original scope.

## Verification

- Full regression suite: 196 tests passed. Added coverage verifies concave boundary inclusion, clockwise/collinear normalization, invalid outlines, retained triangle area and UV interpolation at large coordinates, unique ownership of vertical faces on internal triangulation edges, native triangulation, actual native mesh texture pixels, Gaussian polygon pixels, LAS bytes and Gaussian PLY parameters/custom fields. A final 12-test targeted run passed after adding ear-plane broad-phase rejection for mesh performance.
- Actual 溪瑞苑6栋 LAS: 13,102,445 source points. Six vertices were clicked in the native GUI to form a concave L-shaped outline; its notch was removed in preview. Enter closed the outline. The GUI exported 6,216,388 points in 10.2 seconds. An independent winding-angle algorithm selected the same records from the source; the entire selected-record SHA-256 matched the exported LAS. All original fields were retained.
- The GUI was then used to start another outline, add one point, undo it with right click, and cancel with Escape. The original six-point committed outline and clipped preview returned.
- Actual 藏经阁 OSGB subtree: a concave six-point selection exported OBJ and OSGB containing 2,505 triangles and 3 materials. All positions were inside the prism; background checks passed geometry, UVs, normals, indices, groups, texture bytes and texture decoding with zero repairs.
- Both actual selections rendered 1-second 1920×1080 / 30 fps MP4s. Frame count, duration and complete decoding passed. Synthetic native mesh pixels independently verify the removed notch and retained textured arms.
- PyInstaller portable build and native C++ build completed. The portable folder contains both GUI and CLI entry points, runtime libraries, README and licenses.

Actual local artifacts: `output/手绘裁剪验证_1.10.0`. Development evidence: `validation/polygon110`.

## Review

Mesh export triangulates only the selection polygon, clips source triangles against each convex prism, preserves source-space attributes and interpolates boundary UVs/normals. Coplanar faces on internal selection diagonals have one owner. Ear-plane broad-phase rejection prevents unrelated faces from entering Python clipping loops. Native mesh preview uses a single polygon-discard pass with existing material textures, texture matrices and box planes; it does not duplicate the model per polygon ear. Points use GPU center-in-polygon clipping rebased around the cache origin. Input limits bound validation and shader loops. The original files are read only, and existing background export verification remains enabled.

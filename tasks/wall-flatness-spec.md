# LAS viewing and wall plane deviation — 1.7.0

## Objective and assumptions
Add a prominent LAS import action, adjustable point size, and a bilingual wall analysis tab to the existing Tk/OSG desktop. Select one wall with the existing clipping box, explicitly choose coordinate units (m, cm, mm), then calculate signed perpendicular distances to the least-squares best-fit plane. Default tolerance is 5 mm, user editable; this is a user threshold, not a construction acceptance standard. Do not present this as a 2 m straightedge test. User explicitly confirmed “先做平面偏差分析” during implementation. All selected source points participate, no automatic outlier removal. Source files are read-only.

## Architecture and boundaries
`wall_flatness.py`: two streaming passes over LAS, centered double-precision covariance and eigensolve, then all-point deviation statistics and a bounded color preview. Reject too few points, line-like/volumetric selections, invalid units or tolerance. Emit JSON, UTF-8 CSV and a readable HTML report only on complete success. Keep source fingerprint and selection/units/method in reports. Cancellation and source modification must not publish a successful result.

`flatness_panel.py` and `studio.py`: import LAS, choose wall area, set units/tolerance, analyze asynchronously using existing task/cancel controls, show signed color legend, full-point statistics, original/color toggle, face-on view and open report. Changing selection/settings invalidates the current overlay and labels the result stale. Do not silently reuse a previous model's result. Native `viewer.cpp` swaps an additional bounded point scene while preserving source coordinates and navigation. Existing mesh, video and cropping behavior remains.

## Commands and conventions
Python 3 / Tk / numpy / laspy, C++17 / OpenSceneGraph. Use small modules with explicit value validation, existing Control cancellation and atomic JSON writes. Example: `analyze_wall(source, output, box, unit='m', tolerance_mm=5, control=control)` returns a plain report dictionary.

- Test: `.venv-studio/Scripts/python.exe -m unittest discover -s tests`
- Native build: `cmake --build build/native --config Release --target mesh_viewer`
- Package: `.venv-studio/Scripts/python.exe -m PyInstaller --noconfirm --distpath build/package-v170 --workpath build/pyinstaller-v170 package.spec`
- Run: `.venv-studio/Scripts/python.exe app.py`

## Acceptance / verification
1. Known flat, offset, tilted, dented LAS fixtures give expected millimeter distances, all selected records counted, unit conversion correct, large world offsets stable. Reject degenerate selections, cancel cleanly, no source writes. Preview sampling never alters statistics.
2. Real desktop LAS import, clipping, point size, analysis, face-on view, color/original toggle, PNG and report open work. Input edits invalidate stale results. Non-LAS models have an explanatory disabled analysis action.
3. Real local LAS reads and bounded-memory analysis, repeat viewer actions, full regression suite, native build, packaged smoke run and verified ZIP. Synthetic data is clearly marked in demonstrations; no fabricated real-wall accuracy claim.

Sources: https://cloudcompare.org/doc/wiki/index.php/Fit_Plane ; https://cloudcompare.org/doc/wiki/index.php/Cloud-to-Primitive_Distance ; https://laspy.readthedocs.io/en/latest/api/laspy.lasreader.html

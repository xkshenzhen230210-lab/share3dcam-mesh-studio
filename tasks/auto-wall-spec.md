# Automatic wall inspection — 1.8.0

## Objective
User supplies an indoor LAS; software automatically identifies connected wall-like surfaces, divides them into numbered zones, analyses every assigned original point, and creates a report usable for contractor/supervisor communication. Improve convenience over the separate segmentation/inspection/export steps referenced in Trimble RealWorks. Retain existing manual plane analysis.

## Contract
- Default entire LAS, Z is vertical, user-selectable m/cm/mm; default ±5 mm tolerance and 2 m zone size. Project/site/operator metadata are optional and visibly left unspecified when absent.
- Detect near-vertical planar surfaces from a bounded sample. Separate disconnected coplanar surfaces and distinct parallel wall faces. Do not claim semantic room or structural wall recognition from geometry alone.
- Fit one least-squares reference plane per detected wall using all its assigned source points. All zones on that wall share this plane so subdivision cannot hide broad bowing. Every zone records its full-resolution count, bounds, min/max signed deviation, maximum absolute deviation, RMS, peak-to-valley and outside-tolerance count/ratio.
- Assignment membership uses a declared geometric band independent of tolerance, nearest compatible surface and connected footprint. No point belongs to two walls. Equidistant ambiguous points, unassigned points and their sample views remain explicitly reported; the assigned/source ratio is a point share, never a claim of complete wall coverage. No outlier removal after assignment.
- Sample neighbourhood PCA and a compatible-neighbour connectivity graph prevent nearby floor/corner/parallel fixture contamination. Full-point assignment uses valid source normals when present, otherwise estimated neighbourhood normals, plus local supported-surface continuity. A 25 mm local depth allowance plus tangential-spacing allowance is independent of tolerance. Unsampled isolated protrusions may remain unassigned and this limitation must be reported.
- Detection is an estimate. Sparse zones, insufficient occupied coverage, large thickness, quantization larger than tolerance, or deviations approaching the membership band are marked for review. Other points and missing surfaces must not be labelled passing. Reaching a detection cap is reported.
- Result wording: within/exceeding configured tolerance or review required; never unconditional construction acceptance, 2 m straightedge equivalence or scanner accuracy claims. Existing user choice is best-fit plane deviation; an optional standards question must not block independent implementation.
- Source read-only. Bounded sampling/chunking, deterministic IDs/order, explicit units, stable centered arithmetic for large coordinates, progress/cancel and atomic publication. No successful report after cancellation or source modification.

## Delivery
PDF cover and scope, summary and issue priority, XY location overview with wall IDs, per-wall elevation maps with zone boundaries, readable numeric zone tables, worst-point coordinates, assumptions/coverage and signature blanks. Offline HTML shares the results and links to assets; UTF-8 BOM CSV and machine-readable JSON preserve values. Report maps have metric axes, signed millimetre legend, blank/no-data distinction and a common configured color range. No invented customer, survey time, acceptance standard or signature.

## Implementation
Python 3.12, NumPy/laspy/Pillow; dedicated `wall_segmentation.py`, `auto_wall.py`, `wall_report.py`, `auto_wall_panel.py`. Integrate with existing studio worker/control and native analysis overlay. PDF renderer uses ReportLab with a redistributable embedded Chinese font, packaged alongside current branding. Tests use unittest and temporary synthetic LAS files.

`inspection_job.py` runs the analysis/report in a separate process with one allowed logical CPU and single numeric thread pools. Parent owns a temporary sibling directory, forwards progress, terminates on cancellation and rechecks source size/mtime before atomic publication. This confines the numerical/report workload and avoids reproducible host numeric faults observed with unrestricted affinity. No system settings change.

Commands: `.venv-studio/Scripts/python.exe -m unittest discover -s tests -v`; `.venv-studio/Scripts/python.exe -m PyInstaller --noconfirm --workpath build/studio-v180 --distpath build/package-v180 package.spec`.

## Checks
Analytical plane/defect statistics, geometry disconnection/corners/opposite faces, full-point count reconciliation, units/translation invariance, sparse/no-wall handling, source modification, cancellation and output preservation. Real-file test must independently recompute selected wall/zone statistics and inspect all report pages. Portable GUI must complete analysis and navigate results; package must include PDF dependencies/font.

## Reference
Trimble official RealWorks 2024.00 notes document Magic Wand segmentation and inspection-map CSV export: https://help.fieldsystems.trimble.com/realworks/2024.00.htm . Product overview documents construction deviation reports: https://www.trimble.com/en/products/building-construction-field-systems/trimble-realworks . These inform workflow design, not an assertion of feature parity or benchmark superiority.
## 1.8.1 near-wall surface correction

- Isolate the selected wall in both deviation and original color views; surrounding surfaces must not occlude it.
- Prevent sparse parallel faces bridging the sampled wall graph through tilted neighbourhood normals. Limit the candidate-plane depth step to 35 mm and full-source local support depth to 25 mm independently of along-surface spacing and report tolerance.
- Preserve connected 30 mm defects and continuous 50 mm bowing in regression tests. Do not remove assigned outliers to improve statistics.
- Automatically flag overlapping depth layers in a 120 mm projected cell (at least three sampled points per side, gap > 35 mm), mark intersecting zones unresolved/review, and retain candidate statistics with explicit interpretation limits.
- Include isolated RGB, context depth section and orange overlap locations in PDF/HTML. Missing wall points remain blank and unjudged.
- Re-run the actual Xiruiyuan LAS; previous 1.8.0 wall membership was contaminated in W003/W024 and is superseded for interpretation.

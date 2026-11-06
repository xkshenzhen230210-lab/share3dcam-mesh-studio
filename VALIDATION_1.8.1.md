# 1.8.1 wall isolation and near-wall surface validation

Date: 2026-11-06. Read-only source: Xiruiyuan Building 5 LAS, 10,956,838 points. The 1.8.0 membership in this sample is superseded: viewing extracted RGB walls and horizontal/vertical sections exposed nearby layers previously joined to W003/W024.

## Changes and regression evidence

- A stable candidate-plane depth-step guard prevents tilted neighbourhood PCA normals from bridging parallel faces. Full-source local support no longer grows with tangential spacing. Both checks remain independent of report tolerance.
- Sparse 60 mm wall sampling with a parallel object 40 mm away reproduced 36.83% object leakage before the fix. The regression now allows at most 1% leakage and checks retained wall coverage. Dense and unsampled fixtures, translated source coordinates and supplied normals are also covered.
- Connected 20 mm broad/narrow bumps, the existing 30 mm step defect, and continuous 50 mm wall bowing remain represented. No outlier pruning occurs after assignment.
- A projected-cell depth-layer guard marks unresolved overlap locations and affected zones for review without silently erasing possible defects. A separate test distinguishes two coherent layers from a continuous bow and a single extreme point.
- All 164 automated tests passed in 46.861 seconds, including full-source statistics, unchanged input, report outputs, cancellation and isolated-worker behavior.

## Actual extracted-wall inspection

All 40 candidate walls were examined as isolated RGB elevations and horizontal/vertical depth sections, using original source context for comparison. W024's separated layer around 100–130 mm and W003's larger bottom intrusion were removed from their populations. This is not a claim that every remaining point has a certified semantic wall label.

40 candidates / 94 zones remain. Assigned points changed from 5,211,575 to 5,112,560. 5,844,278 original points remain unassigned and unjudged. Statistics use full original assigned points; extraction views use a bounded sample. Context points are never included merely because they appear gray in a section.

Independent direct SVD on reconstructed full point sets verifies the revised fit/statistics, including all 14 zones for these three walls and raster totals/extremes:

| Wall | Assigned points | RMS mm | Maximum absolute mm |
|---|---:|---:|---:|
| W003 | 845,111 | 4.719971 | 65.207387 |
| W024 | 216,509 | 9.004054 | 44.826657 |
| W035 | 130,815 | 2.607619 | 50.008200 |

The overlap guard identifies sampled depth layers in W005, W009, W011, W012, W013, W014, W015, W019, W023, W028, W029, W034 and W037. Their marked zones cannot be interpreted directly as wall defects. Inclined, touching, thin, sparsely sampled or obscured objects may still be missed; the method is geometric, not semantic furniture recognition. Empty/occluded wall regions are not filled or passed. Candidate statistics in uncertain regions are retained transparently.

Source SHA-256 remains `bf491c6c730190291d497300705e1e10e51e0a949bb5c035023f08e6f9fb22c0`. The automatic method uses adjustable plane-deviation tolerance, not a 2 m straightedge or construction-acceptance result.

## Review

Reviewed membership, local-coordinate units, zone overlap intersections, bounded sample cost, source protection, HTML/PDF text escaping and atomic publication. Regression tests and actual sections support the improvements above. Old reports remain available for traceability and must not be used as the revised wall analysis.

## Portable application and final report

The packaged 1.8.1 GUI opened the full UNC LAS and generated the complete report. Its revised numerical results match the development run. W003 and W024 were selected in the native viewer and switched to their isolated original-color caches, confirming that surrounding model surfaces did not reappear. The automatic overlap guard marks 13 zones across 13 candidates; 74 zones have outside-tolerance values and 20 have quality-review status in total (including overlap).

The final report has 51 pages. Every page was rendered and inspected in contact sheets, with W024, W034 overlap locations and methods reviewed at full size. W003's longer zone table has a dedicated labeled continuation page; the final pagination was regenerated from the GUI report's unchanged result data and the same report code included in the final portable build. Both report regression tests passed again after this pagination adjustment. Source hash was checked again and remains unchanged.

Final report: `output/溪瑞苑5栋_墙面隔离巡检_1.8.1_20261106/wall_inspection`. It includes PDF, offline HTML, 81 figure images, full-count grid data, CSV, structured parameters and isolated wall preview caches.

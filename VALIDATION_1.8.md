# 1.8.0 automatic wall inspection validation

**Superseded for wall-membership interpretation by 1.8.1.** Isolated RGB and side-section inspection later exposed nearby-layer contamination in this real sample, especially W003 and W024. The numerical SVD agreement below validates arithmetic for the old assigned set, not that every assigned point is a wall. Use a newly generated 1.8.1 report and `VALIDATION_1.8.1.md`.

Date: 2026-11-06 (Asia/Shanghai). Method: all assigned original points relative to each wall's least-squares plane; shared reference for its metric zones. Tolerance is configurable and independent of membership.

## Algorithm and delivery checks

- Final complete existing and new regression suite: all 161 tests passed (47.224 seconds). Includes tolerance-invariance, original-color/cache geometry equality, and all 4 isolated-worker/camera tests.
- Synthetic cases cover separated coplanar walls, close parallel surfaces, adjacent floors/corners, detached fixtures, connected 20 mm broad and narrow defects, supplied normals, coordinate translation, metres/millimetres, no-wall data, full-point statistics, incomplete coverage, cancellation, changed source and existing output preservation.
- Changing tolerance from 1 to 5 mm changes outside counts without changing point membership, reference plane or actual deviations.
- The worker handles Unicode paths, confines numerical/report work to one allowed CPU, and leaves no completed output on cancellation or source modification. PDF font and numeric/report dependencies are bundled.
- PDF/HTML/CSV/cache tests reconcile output counts and source hashes, escape report text and preserve existing destinations. The source-size/mtime check runs again in the parent immediately before publication.

## Real input and independent calculation

Actual source: `V:\给泽强\C10\成果数据\室内建筑\溪瑞苑5栋_colorized_segmented.las` (accessed using its UNC equivalent).

- LAS 1.4 format 7, 10,956,838 points, 657,411,439 bytes, RGB and NormalX/Y/Z attributes, metre units and 0.1 mm coordinate increments.
- Whole-file SHA-256: `bf491c6c730190291d497300705e1e10e51e0a949bb5c035023f08e6f9fb22c0`.
- At ±5 mm and 2 m zones: 40 geometric wall candidates, 94 zones, 5,211,575 assigned points. The 5,745,263 unassigned points include other surfaces and unresolved/missed walls and receive no tolerance judgement.
- 74 zones contain outside-tolerance points; 20 require quality review (and may also contain outside points). These counts are not construction acceptance results.
- Initial isolated complete run: 77.039 seconds. PDF has 50 pages. All 50 pages rendered and visually inspected in contact sheets; representative detailed wall and method pages also inspected at full size. Text/font and page presence checks passed.
- Independently reconstructed full selected point sets and used direct SVD, without the streaming statistic accumulators, to recalculate 3 walls / 14 zones. Counts, RMS, maximum absolute deviation and outside counts match; full raster count totals and maxima also match:

| Wall | Points | Zones | RMS mm | Maximum absolute mm |
|---|---:|---:|---:|---:|
| W003 | 850,293 | 8 | 10.112778 | 147.988893 |
| W024 | 301,177 | 4 | 49.839907 | 121.949806 |
| W035 | 130,887 | 2 | 2.662974 | 50.028780 |

The independent numerical check uses the same segmentation membership, so it verifies fitting/statistics, not semantic truth. Separate synthetic membership fixtures test contamination and retention of true defects.

## Review boundaries

Candidates are near-vertical geometric connected surfaces, not semantic rooms or certified walls. Source Z must be vertical. Sampling and local continuity can miss isolated unsampled protrusions; all unassigned regions remain unjudged. The 150 mm search band and local 25 mm depth allowance plus tangent spacing are disclosed in both report and instructions. No point removal occurs after membership, and map cells retain original-point extrema. Review flags do not claim to catch every mixed surface. Reference planes, coordinates, settings and source identity are retained for repeat analysis.

Source and report files remain local; no user model or report is uploaded. Report filenames are generated internally, HTML and PDF text is escaped, and CSV textual formula prefixes are escaped. Output publication uses an owned temporary sibling directory and atomic rename.

Review covered correctness, readability, module boundaries, user-data handling and bounded-memory performance. Tests and real-data evidence support the documented scope; no benchmark claim against RealWorks is made.

## Portable UI checks

The frozen executable loaded the full UNC LAS and completed automatic analysis from the UI. All 40 wall and 94 zone records were exactly equal to the development report. Wall W003 and zone W003-Z001 navigation were exercised with the native renderer, with no analysis overlay error. Cancellation of a repeat analysis returned controls to ready, removed its temporary job and preserved the earlier complete report. At an intermediate sample the worker peak working set was 1,058,308,096 bytes (approximately 1 GB); this is an observed value, not a guaranteed upper bound.

UI refinements include a compact region list, distinct overview/deviation legends, parent-centred report metadata dialog, same-wall original-color comparison, and direct offline HTML report opening with a PDF link. The Chinese PDF font is embedded and the report can be read without first associating a PDF viewer. The read-only original source and all successful older report folders are preserved.

Final portable build was run again on the full LAS with the project name entered through the centred metadata dialog. The resulting 40 walls / 94 zones exactly match the earlier records; original-source SHA-256 is unchanged. Same-wall original-color switching was visually verified, and the Report button opened the correct offline report in Chrome. All 50 final PDF pages were rendered and checked again. The final deliverable is under `output/溪瑞苑5栋_墙面巡检交付_20261106/wall_inspection`.

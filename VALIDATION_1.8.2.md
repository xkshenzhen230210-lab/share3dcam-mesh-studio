# 1.8.2 shared-directory inspection recovery

Date: 2026-11-06.

## Failure and correction

The running 1.8.1 application failed with WinError 59 on a private `.inspection-job-*` directory under the user's V: shared output directory. The source LAS and ordinary output parent were readable. Both failed private job directories returned access denied, while creating, writing, reading and renaming an ordinary test directory in the same parent succeeded. Python's Windows private temporary-directory ACL behavior is incompatible with this share's handling. Existing share permissions were not changed.

Inspection jobs now compute in the current user's local application cache. A completed report is copied to an ordinary sibling directory that inherits the selected destination permissions. Every file is read back and SHA-256 verified before the final folder is renamed into place. Transient copy errors are retried. If delivery fails, the completed local report is retained permanently, and the application shows and opens that actual location. Cancellation, source changes and existing report folders cannot publish a partial result or overwrite a report.

## Regression evidence

All 171 automated tests passed in 108.528 seconds. New coverage reproduces denial of private temporary directories on the output share, durable local fallback, transient partial-copy recovery, corrupted read-back rejection, cancellation, changed input and existing-output protection. The original isolated-worker, numerical analysis, viewer and conversion tests remain passing.

Review covered cancellation propagation, source identity checks, cleanup restricted to the call's owned stage, bounded 1 MB streaming copies, existing-output races, local fallback visibility and packaged module inclusion. No new dependency was added. Numerical wall segmentation and tolerance rules are unchanged from 1.8.1.

## Actual user data

Input: `室内建筑/溪瑞苑6栋_colorized_segmented.las`, 13,102,445 points, 786,147,859 bytes. The LAS WKT explicitly declares metres. The failed GUI had millimetres selected; the retry uses metres, adjustable tolerance ±5 mm and 2 m zones.

The first complete run finished in 158.63 seconds and successfully delivered to the original shared parent, under `SHARE3DCAM_export_20261106_093631/wall_inspection`. Results: 38 wall candidates, 104 zones, 6,107,669 assigned points and 6,994,776 unassigned points. The source file's SHA-256 before and after the run is unchanged:

`1dbc52936ab4e921d7985ed76f7c1f696863a09d034ac3a2938b1ed7e7de1215`

The 1.8.1 limitations continue to apply: geometric plane-deviation analysis is not a 2 m straightedge test or formal construction-acceptance certification. Marked overlap and insufficient-data regions require interpretation; invisible wall regions are not invented or passed.

## Packaged application and report review

The portable 1.8.2 application was launched, the same UNC LAS opened, and the original V: output parent selected. Clicking Analyse completed successfully and delivered `wall_inspection_02` on that share. All wall numerical records exactly match the development run. The isolated worker used CPU 31. Selecting W001 displayed its extracted surface, and the Report button opened the generated offline report from the share.

The complete final result was copied locally and every copied file verified byte-for-byte by SHA-256. Its 52 PDF pages were rendered and visually inspected in contact sheets, with the cover, W029 extraction, continuation table and methods also checked at full size. Tables, figures, fonts and page numbering are readable. The source LAS hash was checked again and remained unchanged. Final local report folder: `output/溪瑞苑6栋_墙面报告_1.8.2_20261106`.

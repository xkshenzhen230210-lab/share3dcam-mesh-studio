# SHARE3DCAM Mesh Studio 1.7.0 verification

Date: 2026-11-06. New functionality: explicit LAS import, point size, selected-wall least-squares plane deviation in millimeters, color preview, HTML/CSV/JSON report.

- Full suite: **142 tests passed**, 28.246 seconds, process exit 0. Includes 8 wall-analysis tests: known tilted and flat walls at large offsets, symmetric ±3 mm surfaces in m/cm/mm, a defect absent from sampled display but included in full statistics, inclusive selection, chunked covariance vs independent SVD, invalid/empty/line/volumetric selections, source changes, cancellation before/during output, and existing-folder protection.
- Native Release viewer build passed; packaged viewer SHA256 `873AEDA34EA814760F4DA994BC337285C905C0E305E971083A6DADF8322E5BBE`.
- Actual Tk callback + native viewer integration passed: LAS import, selection, analysis, original/color toggle, report target, PNG, tolerance invalidation, repeated output numbering, video-tab color isolation, invalid selection, Undo, source switch. Synthetic fixture has 120,701 points; measured maximum absolute 11.744384 mm, RMS 1.941738 mm, outside ±5 mm 4.753896%. Fixture explicitly named synthetic; this is not a scan accuracy claim.
- Continuous native viewer exercise: **194.47 seconds**, 181 state changes, 137 PNG checks, across mesh/LAS/Gaussian scenes. LAS repeatedly switches original/color overlay and point size. All three viewers exited normally. Longest snapshot 0.359 seconds.
- Real input: `C:/c/p大哥数据_colorized.las`, **3,592,954,711 bytes / 74,853,199 points**. Full source scanned to fit and measure 336,879 selected points, with 168,440 display points. Total 15.99 seconds including source SHA256 before and after. Analysis-process peak working set 54.23 MiB, peak committed memory 813.19 MiB; these exclude the UI/GPU and are local measurements, not guarantees on other PCs. Source SHA256 unchanged: `c98b52c086aaec1373cb41efa8e1318f4311e1677796ba53b2bb2289ac6c618f`.
- Real selection is a processing/scale test, not a calibrated known-flat wall. Its thick-selection warning is expected; no automatic outlier deletion or acceptance judgement is made.

Implementation review checked full-source statistics vs bounded preview, double-precision coordinate centering, explicit units, signed legend saturation, report provenance, cancellation cleanup, invalidation after edits, source immutability, no new dependency, native shader default compatibility and original-model video behavior.

Evidence files in the development workspace: `validation/v170/ui_report.json`, `validation/v170/real_report.json`, `validation/v170_native_soak_report.json`, `validation/v170/full_suite_result.json`. Final portable GUI and archive checks are recorded in the release copy of this document.

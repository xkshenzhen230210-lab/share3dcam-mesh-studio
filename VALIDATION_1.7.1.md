# SHARE3DCAM Mesh Studio 1.7.1 verification

Date: 2026-11-06. Real input: 溪瑞苑5栋_colorized_segmented.las, 657,411,439 bytes, 10,956,838 points, LAS 1.4 point format 7 with RGB and NormalX/Y/Z extra dimensions. Source CRS specifies metres. Source size and modification time were unchanged after analysis and crop.

## Real-file results

- Portable GUI opened the network source and displayed 296,131 preview points. Statistics read all selected source records, independently of this display sample.
- Initial box `[1.0787, -3.3799, 0.5, 1.7821, -2.5494, 1.8]` contained 67,792 points. Maximum absolute deviation: 110.340184 mm; RMS: 13.895382 mm. Large deviations clustered along its lower edge. This report was retained without outlier filtering.
- Raising only the lower Z boundary to 0.65 isolated the wall above that feature: 59,996 points; maximum absolute deviation 3.141728 mm; RMS 0.886662 mm; peak-to-valley range 5.796196 mm; 0% beyond the user-set ±5 mm tolerance.
- Independent centred SVD over every selected source point reproduced both analyses within 0.0000001 mm. These are selected-patch best-fit plane deviations, not scanner accuracy or an acceptance result for the building.
- Original-format LAS crop preserved all 60 bytes of every selected point record, including coordinates, RGB, classification, GPS time and normals. Independent checks also compared the complete raw VLR region, scales and offsets. Output: 3,600,919 bytes, 59,996 points.
- Portable 1.7.1 CLI repeated the crop from the original network source; its file was byte-identical to the independently checked output. LAS SHA256: `9ffe199efb1995b686ab77a063d45b0eee67a70225bbfd59a9a3c5f75bafe73a`.
- Portable 1.7.1 GUI reopened this LAS, displayed original colours, then analysed all 59,996 points and reproduced the original selection's statistics. The GUI was left displaying the wall heatmap.

## Compatibility fix and regression

The real file's Extra Bytes VLR user ID contains `LASF_Spec` followed by a NUL and nonzero padding. The previous raw metadata checker incorrectly treated those padding bytes as part of the identifier. It rejected the crop rather than publishing unchecked output. IDs now end at the first NUL, matching the LAS reader; original VLR and EVLR bytes are still restored and verified.

A synthetic regression covers both ordinary and extended VLR IDs with nonzero bytes after NUL. It failed before the fix and passed afterward, including exact metadata bytes, point records and unchanged source. Full suite: **143 tests passed in 27.230 seconds**. `git diff --check` passed.

PyInstaller portable build succeeded. An initial unpinned build failed inside Python's bytecode inspection; a process pinned to CPU 16 completed successfully. No dependency or runtime version was changed. Native viewer and render binaries were unchanged by this patch.

Detailed real-file reports, independent checks and viewport PNG are in the sibling output directory `溪瑞苑5栋_LAS实测_20261106`. The original failed export attempt is retained separately for diagnosis.

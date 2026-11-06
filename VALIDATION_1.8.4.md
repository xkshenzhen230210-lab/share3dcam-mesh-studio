# 1.8.4 unified model and point-cloud opening

Date: 2026-11-06.

Removed the duplicate LAS-only toolbar button and callback. The existing File action already supported LAS and calls the same model loader. The unified dialog now says "Open model or point cloud", shows all supported formats by default, and offers LAS and PLY filters. Loading, recent files, pasted paths, cancellation, clipping, wall inspection and video retain their existing handlers.

Verification:

- All 179 automated tests passed in 63.298 seconds. No implementation-mirroring test was added for removing a duplicate button.
- The portable 1.8.4 build completed successfully.
- In the packaged GUI, File opened `validation/original.osgb` and displayed its textured mesh.
- The same File action then opened the actual network source `溪瑞苑6栋_colorized_segmented.las`. Its point cloud displayed successfully, with Source output selected automatically.
- The Wall tab recognized the loaded LAS and enabled automatic analysis. No new analysis was run for this toolbar-only change.
- The toolbar was checked at its normal 1360-pixel window size: File, Folder, Recent and Open fit without the duplicate LAS button.
- Reviewed the busy-state widget list to remove the old button reference and verified the common load handler and all original supported extensions remain intact.

The new application was left open with the actual LAS loaded. Existing open application windows were preserved.

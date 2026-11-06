1. 解析样例和协议，验证 GLB 坐标、纹理和 Tiles 层级。
2. 完成流式 GLB→OBJ，添加坐标、材质、异常测试。
3. 编译 OSG 写入器，实现 OSGB 几何与分页树，读回验证。
4. 接入 Tiles 树及元数据输出，完成真实数据转换。
5. Windows GUI、取消和日志，打包 EXE，交付说明。

## 1.7.0 — LAS / wall plane deviation
1. Streaming analysis + source-coordinate tests (`wall_flatness.py`, `tests/test_wall_flatness.py`). Check full-resolution results and cancellation before integrating UI.
2. LAS import, point-size setting, native color overlay and wall panel (`studio.py`, `flatness_panel.py`, `native/viewer.cpp`, `native/point_scene.h`). Build and verify real UI callbacks and visible output.
3. Real LAS / repeated-use checks, documentation, portable release and archive verification. See `wall-flatness-spec.md` and `todo.md`.

## 1.8.0 — Automatic wall inspection and deliverable report
1. Detect connected near-vertical planes from a bounded spatial sample; assign all original points without duplicate membership, and explicitly account for unassigned and ambiguous points. Test separated coplanar walls, corners, defects, floors, units and sparse data before UI integration.
2. Fit each detected wall using its full assigned point set, partition it into a configurable metric grid, and report both wall and zone deviations against the wall reference plane. Keep membership distance independent of acceptance tolerance; flag clipping-band and data-quality concerns.
3. Generate a complete Chinese/English PDF, offline HTML, CSV, JSON, overview plan, indexed wall heatmaps and issue coordinates. Preserve source and isolate outputs. Render PDF pages and verify report totals and values.
4. Add one-click whole-scan analysis with project metadata, defaults, progress/cancel, region navigation and direct report access; retain manual single-wall analysis. Validate on 溪瑞苑5栋, package and verify portable 1.8.0.

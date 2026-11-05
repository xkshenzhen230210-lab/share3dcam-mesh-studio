1. 解析样例和协议，验证 GLB 坐标、纹理和 Tiles 层级。
2. 完成流式 GLB→OBJ，添加坐标、材质、异常测试。
3. 编译 OSG 写入器，实现 OSGB 几何与分页树，读回验证。
4. 接入 Tiles 树及元数据输出，完成真实数据转换。
5. Windows GUI、取消和日志，打包 EXE，交付说明。

## 1.7.0 — LAS / wall plane deviation
1. Streaming analysis + source-coordinate tests (`wall_flatness.py`, `tests/test_wall_flatness.py`). Check full-resolution results and cancellation before integrating UI.
2. LAS import, point-size setting, native color overlay and wall panel (`studio.py`, `flatness_panel.py`, `native/viewer.cpp`, `native/point_scene.h`). Build and verify real UI callbacks and visible output.
3. Real LAS / repeated-use checks, documentation, portable release and archive verification. See `wall-flatness-spec.md` and `todo.md`.

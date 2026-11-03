# Mesh 格式转换软件

目标：Windows 桌面软件，将 SHARE 2.7.5 mesh GLB 或本地 3D Tiles 转为真实 OSGB 和 OBJ，保留 Z-up 米制坐标、纹理、分块和可恢复的 LOD 结构。

样例：V:\给泽强\2.7版本\mesh\2.7.5新\藏经阁。输入只读。输出写入用户指定的全新目录。

## 输出契约
- obj/Model.obj、Model.mtl、纹理和 metadata.xml；Tiles 使用最终精度覆盖面，不叠加 REPLACE 祖先；ADD 节点累加。
- osgb/Model.osgb 入口，Block_*/Block_*.osgb 和原有 Level 名称；保留 Tiles 的树形加载关系，使用 OpenSceneGraph 3.6.5 写入真正 OSGB，图像内嵌。
- 单一 GLB 没有可恢复的 LOD 时按原节点分块，不能声称恢复原始简化层级。
- mesh_result.json / mesh_progress.json 描述结果，并输出 conversion_report.json，记录转换数、边界、警告和来源。
- GLB Y-up 转 Z-up；Tiles 累乘 transform；metadata.xml 保留源空间参考。不存在地理参考时标明 LOCAL，不臆造经纬度。
- 可选择 OBJ、OSGB 或同时导出；GUI 包含输入、输出、进度、日志、取消，提供便携 EXE 和 CLI。

## 技术与边界
Python 3.12 + NumPy 解析 GLB，内存映射大文件；Tkinter 原生界面；小型 C++ OpenSceneGraph 写入器，PyInstaller 打包。按 primitive 分批处理，防止一次解码整套纹理。静态三角网格为支持范围；不支持的压缩、动画、实例、隐式瓦片等明确失败，不静默丢失。

## 命令和目录
- `python -m unittest discover -s tests -v`
- `python app.py` / `python app.py --input INPUT --output OUTPUT --format both`
- `powershell -ExecutionPolicy Bypass -File build.ps1`
- `gltf.py` GLB 读取和坐标；`tiles.py` 层级；`converter.py` 输出流程；`native/writer.cpp` OSG；`tests/` 验证。

代码：清晰函数、显式异常、pathlib 路径，例如 `raise ValueError("缺少瓦片文件")`。始终检查文件引用和输出冲突，不覆盖输入，不改变现有项目。

## 验证
合成测试验证变换顺序、法线、UV、索引、叶节点选择、缺失引用；真实样例执行两种输入两种输出；用 OSG 重新读回 OSGB 检查几何、纹理与外部引用；记录完整数据运行结果。协议参考 Khronos glTF 2.0、OGC 3D Tiles 1.1 及 OSG 3.6.5 源码。

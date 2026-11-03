# SHARE Mesh 格式转换工具 1.0

Windows 10/11 x64 本地软件。支持 SHARE 2.7.5 生成的静态 GLB、3D Tiles 1.1（GLB 瓦片），以及经典 b3dm 内嵌 GLB 2.0。

## 使用

1. 解压整个软件包，双击 `MeshConverter.exe`。保留同目录 `_internal` 文件夹。
2. 输入选择 `Model.glb`、`tileset.json`，也可以选数据目录。
3. 输出选择一个独立的新目录或空目录。
4. 选择 OSGB + OBJ、仅 OSGB 或仅 OBJ，点击“开始转换”。
5. 完成后点击“打开输出目录”。读取入口分别为 `osgb/Model.osgb`、`obj/Model.obj`。

输入原始文件只读。大文件建议输出到本地 SSD，至少预留输入大小的 5～10 倍空间；KTX2 转 PNG、OSGB 页的贴图可能明显增大。取消后保留已生成部分和错误状态，重新转换请选新空目录。当前版本不做断点续传。

选择包含多格式的成果总目录时优先读取 `3dtiles/tileset.json`；选择 `glb` 目录时优先读取 `Model.glb`，避免同时合并其重复的分块 GLB。没有 Model.glb 的目录会递归读取其中 GLB。

## 与原始结构的关系

```text
输出目录/
  obj/
    Model.obj
    Model.mtl
    tex_*.jpg / tex_*.png
    metadata.xml
  osgb/
    Model.osgb
    Block_0/
      Block_0.osgb
      Block_0_Level*.osgb
      Block_0_Level*_children.osgb
    Block_1/...
    metadata.xml
  mesh_result.json
  mesh_progress.json
  conversion_report.json
```

- **3D Tiles → OSGB**：保留实际输入 Tileset 的父子关系、分块目录和瓦片名称。额外的 `_children.osgb` 是分页子组，切换时包含子节点粗模，避免父级退场后短暂空洞。支持 REPLACE 和 ADD。以几何误差和包围球映射为 OSG 屏幕像素 LOD 阈值（默认 16 像素误差），切换距离不声称与原 OSGB 二进制完全相同。
- **GLB → OSGB**：GLB 中若只有最终精度 mesh，就无法恢复丢失的简化层级。软件按源节点、每 8 个 primitive 分页，使用 `Block_*/Block_*_Node*_Part*.osgb`。这是静态分页，文件数量和原 OSGB 的 Level 编号不会一样。需要原有 LOD 时请选择配套 3D Tiles。
- **OBJ**：输出单个合并 OBJ、MTL 和去重纹理。Tiles REPLACE 分支只选最终精度；ADD 分支保留累加内容。OBJ 本身没有 LOD 或分页语义。
- **坐标**：输出 Z-up、米制，应用 GLB 节点矩阵和 Tiles 的累积变换。样例 `Z_UP_POSITIONS_WITH_Z_TO_Y_ROOT_NODE` 会被正确抵消；原始 `metadata.xml` 复制保留。
- 贴图名按内容哈希命名以避免重名，OSGB 图像内嵌。KTX2/Basis 转 PNG，不会恢复压缩前已丢失的图像细节。

**结构兼容意味着可从 Model 入口加载、分块和坐标规则一致；并非保证与原导出器文件逐个或字节一致。** GLB 和 Tiles 输入本身可能采用不同简化精度，导出器不会将它们当作相同几何。

## 支持边界

当前版本针对提供的 LOCAL 静态三角网格样例验收。支持 JPEG/PNG/KTX2 基础色纹理、UV、节点 TRS/矩阵、索引、法线、基础颜色和透明度。OBJ/传统 OSG 固定管线无法完整表达 glTF PBR，基础参数进行映射。

遇到 Draco/meshopt 压缩、sparse accessor、骨骼/动画、morph、顶点色、GPU 实例、需要额外贴图的复杂 PBR、隐式 Tiles、多 content、region 经纬度包围体、必需的未知扩展，会明确报错。地理参考数据请先核对自己的坐标契约：本版未作为通用地理坐标投影转换器验收。源 metadata.xml 缺失时创建 LOCAL 原点零元数据，不自动猜测坐标系。

## 命令行

```powershell
.\MeshConverterCLI.exe --input "V:\给泽强\2.7版本\mesh\2.7.5新\藏经阁\3dtiles\tileset.json" --inspect
.\MeshConverterCLI.exe --input "D:\模型\Model.glb" --output "D:\转换结果\模型_01" --format both
.\MeshConverterCLI.exe --input "D:\模型\tileset.json" --output "D:\转换结果\模型_02" --format osgb
```

失败退出码为 1，成功为 0。`mesh_result.json` 只有在全部完成后才会标记 `succeeded`。大数据转换建议关闭不必要的三维软件以释放内存。

## 源码开发

Python 3.12 x64、NumPy、Tkinter；OSGB 与 OBJ 批量写入器为 C++17。大规模 OBJ 文本在独立的原生进程生成，Python 负责分批读取和调度。发行程序自带 Python 和运行库，使用者无需安装开发环境。

```powershell
python -m pip install -r requirements.txt
powershell -ExecutionPolicy Bypass -File build.ps1
python -m unittest discover -s tests -v
python app.py
```

`bootstrap.py` 准备第三方开发依赖，CMake 需要 Visual Studio 2022 C++ Build Tools 和 Windows SDK。源码位置：gltf.py / tiles.py / converter.py / app.py / native/writer.cpp。验证说明见 VALIDATION.md。

## 协议和第三方

- [Khronos glTF 2.0](https://registry.khronos.org/glTF/specs/2.0/glTF-2.0.html)
- [OGC 3D Tiles 1.1](https://docs.ogc.org/cs/22-025r4/22-025r4.html)
- [OpenSceneGraph 3.6.5 源码](https://github.com/openscenegraph/OpenSceneGraph/tree/OpenSceneGraph-3.6.5)；[Windows 构建提供方](https://objexx.com/OpenSceneGraph.html)
- [Khronos KTX-Software 4.4.2](https://github.com/KhronosGroup/KTX-Software/releases/tag/v4.4.2)

第三方版权和许可见 `licenses`。所有模型转换都在本机进行。

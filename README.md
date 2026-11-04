# SHARE3DCAM Mesh Studio 1.5.0 · 模型工作台

SHARE3DCAM 电商销售中心 / SHARE3DCAM E-commerce Sales Center

## 1.5.0 漫游、3D Tiles、点云与高斯 / Navigation, tiles and splats

点击三维视图后使用 **W/S 前后、A/D 左右、Q 上升、E 下降**。W/S 沿相机视线移动，A/D 横移，Q/E 沿模型 Z 轴升降。按住 Shift 以 3× 加速，Ctrl 以 0.2× 慢速；上方“移动速度”以源坐标单位／秒设置。输入框内正常编辑文字，不触发漫游。原有鼠标旋转、平移、滚轮缩放继续可用。

网格输出格式新增 **3D Tiles**。选择此格式后，“转换完整模型”或“导出盒内模型”生成 `3dtiles/tileset.json`、分块目录中的 GLB、坐标元数据与后台验证报告。支持已有 GLB、3D Tiles、OSGB、OBJ 及受支持的网格 PLY/STL；保留基础颜色、透明、UV、纹理与读取器支持的法线。采用 3D Tiles 1.1 和 Y-up GLB 内容，瓦片坐标为 Z-up，以局部中心和双精度平移保留大坐标精度。每个 GLB 读回核对，检查引用和包围体后才发布成功。

这是静态最终精度瓦片集，不自动生成简化 LOD，也不自动地理定位；原有 3D Tiles → OBJ/OSGB 功能继续保留。GLB 顶点与 UV 使用标准 float32，坐标不是 double 逐位无损；原图片不缩小、不重新压缩，KTX2 按原尺寸转 PNG。

**LAS 点云和 PLY 高斯**也可用同一个打开、剪切盒和视频界面：

1. 选择 `.las` 或点／高斯 `.ply`，点击打开。PLY 中有三角面时仍走网格流程，无面的普通点 PLY、标准 Inria SH0–SH3 高斯自动识别。
2. 预览均匀抽样最多 30 万点，侧栏显示实际预览／原始点数。点云显示 RGB；高斯使用尺度、旋转、透明度、视角相关球谐颜色、各向异性椭圆与深度排序。点／高斯显示需要 OpenGL 3.2 / GLSL 1.50。
3. 开启剪切盒并设置范围，输出格式自动选择 **原格式 / Source**。点击“导出盒内模型”保存 LAS 或 PLY；选择“转换完整模型”可完整复制原格式。正式裁剪读取全量数据，不使用抽样缓存。
4. 选中的点记录逐字节保留。LAS 保留点格式、额外字段、scale/offset、VLR/EVLR 和 CRS；高斯保留全部 PLY 字段。**高斯按中心是否在盒内筛选，边界高斯保持完整，不切开椭球、不重新训练。** 后台核对所有输出记录及元数据，出错自动重建一次，持续失败不报告成功。
5. 在“视频”页记录关键帧、设置时长与倍率，导出 1080p 或 4K、24/30/60fps MP4。视频重新准备全量点／高斯；启用裁剪时先按原精度筛选。高斯视频采用浮点颜色缓冲完成透明合成，再输出视频。尺寸、时长、帧数及完整解码检查沿用现有自动流程。

点云／高斯的原格式导出保留属性；OBJ、OSGB 和本版网格 3D Tiles 导出不能承载高斯参数，因此点数据请选择“原格式 / Source”。LAS 当前按 LAS 1.0–1.4 非波形点记录验收；波形格式仅支持完整原文件复制。普通点 PLY 支持 ASCII、大小端二进制标量字段；压缩／打包高斯及非标准属性布局不在本版支持范围。完整视频需要容纳全量点的内存、显存和缓存空间。

## 1.4.0 播放时长与速度 / Duration and speed

视频页底部新增“时长 / Duration”和“速度 / Speed”。输入时长并点击“应用 / Set”，按比例调整全部关键帧时间，保持每个视角与各段时间比例不变。输入后直接点击播放、保存或导出也会应用该时长。

速度支持 0.25×、0.5×、1×、1.5×、2×、4×，同时作用于预览和导出。实际时长显示在设置下方，等于基准时长除以速度。例如时长 60 秒、1× 输出 60 秒；2× 输出 30 秒；0.5× 输出 120 秒。要导出一分钟 4K60，设置时长 60、速度 1×、4K、60 FPS；最终生成 3600 帧。

动画 JSON 现在同时保存时长对应的关键帧、速度、分辨率和帧率，并兼容 1.3.0 保存的动画文件。不同速度不会改动相机位置或模型源数据。

## 1.3.0 关键帧视频 / Keyframe video

打开模型后，选择右侧“视频 / Video”页：

1. 调整到起始视角，时间设为 `0`，点击“添加当前视角 / Add keyframe”。
2. 旋转、平移或缩放到下一视角，设置时间（例如 `3` 秒），再次添加。至少两帧，时间不可重复；每次添加后默认向后增加 3 秒。
3. 选中关键帧后可修改时间并“更新 / Update”（同时记录当前视角），也可删除或“查看选中帧”。拖动时间条查看中间画面，点击“播放 / Play”预览平滑运镜。保存/载入支持相机动画 JSON；换模型时清空当前关键帧。
4. 底部选择 `1080p`（1920×1080）或 `4K`（3840×2160），帧率 `24 / 30 / 60`，点击“导出 MP4 / Render video”，选择新的文件名。已有文件不会静默覆盖。下方“取消任务 / Cancel”可停止渲染。

视频页使用 16:9 构图；自动隐藏线框和剪切盒边线。启用剪切盒时，视频沿用该固定裁剪范围。相机方向使用四元数插值，关键帧间平滑起停；支持最长 30 分钟动画。当前版本为模型漫游视频，不包含灯光、音轨或字幕编辑。

视频逐帧离屏渲染，使用原始精度贴图和最高细节几何，独立于屏幕尺寸和预览播放速度。非 OSGB 模型首先在后台准备全精度渲染数据；此步骤和大模型整模渲染需要额外时间、磁盘、内存和显存，取消会清理本次临时数据。导出前无需用户手动检查：软件验证尺寸、帧率、时长、帧数并完整解码，通过后才发布 MP4。

MP4 使用 H.264、CRF 18 高质量压缩；原贴图不缩小不代表视频编码逐像素无损。预览缓存的 512 px 限制仅影响交互预览。FFmpeg 与 ffprobe 已随便携包附带，无需另行安装；许可证位于 `licenses/FFmpeg`。

## 1.2.1 目录识别与后台进程恢复

支持直接选择导出的上级目录、`obj` 子目录或 `Model.obj` 文件；也支持目录内唯一的非标准文件名模型。未完成、失败或取消的导出会明确提示，不把材质/贴图目录当成完整模型。

转换和预览缓存生成使用独立后台进程，进程异常退出时界面继续运行，并在独立尝试目录自动重试一次；仍失败会落盘明确的失败状态。转换请求、进度和日志保存在输出目录，完整结果通过检查后才发布。每个转换进程限制到一个可用逻辑 CPU，作为运行稳定性缓解措施，不改变系统设置或模型精度。普通输入错误不反复重试，取消会通知后台任务。

## 1.2.0 后台自动检查

正式导出 OBJ（包括 OSGB + OBJ）默认自动检查，无需手动验收按钮，不打开额外复核窗口。后台逐块重新解析 OBJ，核对源转换缓冲中的坐标、UV、法线、分组、材质引用和面索引；写出不一致会自动重新生成该块并复检。完成前校验完整 OBJ 的 SHA-256、MTL、坐标元数据和全部贴图字节，并完整解码图片。缺失或损坏的生成材质、贴图及复制结果自动从已校验暂存数据恢复。

只有检查通过才显示“导出完成，检查通过”。自动恢复仅处理本次生成文件，重试一次仍不通过则报告导出失败，不要求用户去检测，也不伪装成功。详细结果保存在输出目录 `quality_report.json`。保留原始模型缺陷，不通过减面、缩图、补面或修改源文件来通过检查。普通预览不运行正式导出检查；OSGB 单独导出不包含这项 OBJ 校验。

后台检查需要额外时间和临时磁盘空间（约一份 OBJ 与原图），结束或取消后自动清理本次临时数据。检查验证写出与转换输入一致，不等于自动识别所有视觉缺陷，也不保证不同格式材质语义完全等价。

## 1.1.2 滚轮方向修正

普通模型预览与 OBJ 原图复核统一使用：滚轮向前／向上滚动放大，向后／向下滚动缩小。

## 1.1.1 精度修正

OBJ 坐标、UV 和法线写出使用双精度可往返十进制精度（17 位有效数字），裁剪插值属性不再经过 float32 中间转换。对于本组原始 GLB 的 JPEG/PNG 烘焙贴图，正式导出直接复制图片字节，不缩放、不重压缩。裁剪不减面，盒内完整三角形不移动；跨边界三角形必须产生新顶点和新三角形，切口不封口。

1.1.1 曾提供手动原图复核入口；1.2.0 已移除此入口，由后台自动检查替代。

“无损”不表示跨格式逐字节相同：OBJ 无法表达完整 glTF PBR、LOD 树；本组基础色烘焙模型的保真程度以输出目录中的逐项校验报告为准。OSGB 的渲染顶点仍使用 OSG 常规 float32，本项双精度写出保证针对 OBJ。

## 1.1 新增 / What's new

- 官方 SHARE3DCAM 横版标识，中英双语界面。
- 集成三维查看器，旋转、平移、滚轮缩放，适应、顶视、正视、右视及线框。
- 打开这组成果中的 GLB、3D Tiles、OSGB、OBJ、PLY、STL。OSGB 直接分页显示，其余格式首次打开会生成分页缓存。
- 六面剪切盒：开启后拖动滑块，或输入坐标后按 Enter。点击“导出盒内模型 / Export clipped”真正裁切三角形、插值 UV，并导出 OSGB / OBJ。**切口不自动封口**。
- 完整转换与盒内导出独立。裁剪使用原始精度数据与原始贴图；缓存预览贴图限制为 512 px，直接打开的 OSGB 使用其原始贴图。
- OBJ/PLY/STL 和重新导出的 OSGB 生成静态分页结构；3D Tiles 输入保留源层级。

### 查看与裁剪 / View and clip

1. 双击 `MeshConverter.exe`，选择模型文件（3D Tiles 选 `tileset.json`，OSGB 选 `Model.osgb`），点击“打开 / Open”。
2. 左键旋转、中键平移、滚轮缩放。大模型首次生成缓存时可取消；完成后显示模型。
3. 勾选“启用六面剪切 / Enable clipping”，调整 X/Y/Z 最小值和最大值。右侧面板可以拖动滚动条，底部有重置按钮。
4. 指定独立的新输出目录，选择输出格式，点击“导出盒内模型 / Export clipped”。未开启剪切盒时，请使用“转换完整模型 / Export full”。

网格 PLY 支持本组 binary_little_endian 三角网格及逐面 `texcoord` / `texnumber` / `TextureFile`；点／高斯 PLY 支持见 1.5.0。STL 支持本组 binary STL；OBJ 支持三角面、正负索引、MTL 和基础颜色贴图（不支持 map_Kd 变换选项）。不是所有第三方格式变体都适用。XML、MTL、JPEG、PNG、KTX2、JSON 等辅助文件随模型读取，不作为独立三维模型打开。

Windows 10 1903+ / Windows 11 x64，支持 OpenGL 的显卡。预览缓存位于 `%LOCALAPPDATA%\SHARE3DCAM\MeshStudio\preview`；GLB/STL 可复用缓存，其余格式重新打开会重建缓存。关闭程序后可以手动删除该专用缓存目录。原始输入不会修改。

命令行裁剪示例：

```powershell
.\MeshConverterCLI.exe --input "D:\data\Model.glb" --output "D:\exports\crop01" --format both --clip -20 -10 -15 -10 0 5
```

以下为原有转换结构与技术说明，适用于 1.1 的对应功能。

Windows 10/11 x64 本地软件。支持 SHARE 2.7.5 生成的静态 GLB、3D Tiles 1.1（GLB 瓦片），以及经典 b3dm 内嵌 GLB 2.0。

## 使用

1. 解压整个软件包，双击 `MeshConverter.exe`。保留同目录 `_internal` 文件夹。
2. 输入选择 `Model.glb`、`tileset.json`，也可以选数据目录。
3. 输出选择一个独立的新目录或空目录。
4. 选择 OSGB + OBJ、OSGB 或 OBJ，点击“转换完整模型 / Export full”。
5. 完成后点击“输出文件夹 / Open output”。读取入口分别为 `osgb/Model.osgb`、`obj/Model.obj`。

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

Python 3.12.13 x64、NumPy、Pillow、Tkinter；OSGB 与 OBJ 批量读写器、嵌入式 OpenGL 查看器为 C++17。使用 uv 创建项目独立环境；本机原有 Python 3.12.10 在长时间读取与打包时出现底层异常，因此发行包统一使用已验证的隔离环境。发行程序自带 Python 和运行库，使用者无需安装开发环境。

```powershell
powershell -ExecutionPolicy Bypass -File build.ps1
.venv-studio\Scripts\python.exe -m unittest discover -s tests -v
.venv-studio\Scripts\python.exe app.py
```

`bootstrap.py` 准备第三方开发依赖，CMake 需要 Visual Studio 2022 C++ Build Tools 和 Windows SDK。源码位置：gltf.py / tiles.py / converter.py / app.py / native/writer.cpp。验证说明见 VALIDATION.md。

## 协议和第三方

- [Khronos glTF 2.0](https://registry.khronos.org/glTF/specs/2.0/glTF-2.0.html)
- [OGC 3D Tiles 1.1](https://docs.ogc.org/cs/22-025r4/22-025r4.html)
- [OpenSceneGraph 3.6.5 源码](https://github.com/openscenegraph/OpenSceneGraph/tree/OpenSceneGraph-3.6.5)；[Windows 构建提供方](https://objexx.com/OpenSceneGraph.html)
- [Khronos KTX-Software 4.4.2](https://github.com/KhronosGroup/KTX-Software/releases/tag/v4.4.2)

第三方版权和许可见 `licenses`。所有模型转换都在本机进行。

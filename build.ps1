$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
python bootstrap.py
if ($LASTEXITCODE -ne 0) { throw 'Dependency preparation failed' }
$osgRoot = Join-Path $PSScriptRoot 'vendor\osg\OpenSceneGraph-3.6.5-VC2022-64-2025-04'
cmake -S native -B build/native -G 'Visual Studio 17 2022' -A x64 "-DOSG_ROOT=$osgRoot"
if ($LASTEXITCODE -ne 0) { throw 'CMake configure failed' }
cmake --build build/native --config Release
if ($LASTEXITCODE -ne 0) { throw 'Native build failed' }
python prepare_runtime.py
if ($LASTEXITCODE -ne 0) { throw 'Runtime preparation failed' }
python -m unittest discover -s tests -v
if ($LASTEXITCODE -ne 0) { throw 'Tests failed' }
python -m PyInstaller --noconfirm package.spec
if ($LASTEXITCODE -ne 0) { throw 'Packaging failed' }
Copy-Item -LiteralPath README.md -Destination dist\MeshConverter\使用说明.md
Copy-Item -LiteralPath licenses -Destination dist\MeshConverter -Recurse -Force

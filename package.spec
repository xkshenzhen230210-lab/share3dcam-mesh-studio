# Build two entry points sharing one portable dependency directory.
a=Analysis(['app.py'],pathex=[],binaries=[],datas=[('runtime','runtime'),('assets','assets')],hiddenimports=[],
           hookspath=[],hooksconfig={},runtime_hooks=[],excludes=[])
pyz=PYZ(a.pure)
gui=EXE(pyz,a.scripts,[],exclude_binaries=True,name='MeshConverter',debug=False,
        bootloader_ignore_signals=False,strip=False,upx=False,console=False)
cli=EXE(pyz,a.scripts,[],exclude_binaries=True,name='MeshConverterCLI',debug=False,
        bootloader_ignore_signals=False,strip=False,upx=False,console=True)
coll=COLLECT(gui,cli,a.binaries,a.datas,strip=False,upx=False,name='MeshConverter')

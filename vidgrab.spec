# PyInstaller build spec:  pyinstaller vidgrab.spec
# Produces dist/VidGrab (Linux), dist/VidGrab.exe (Windows) or dist/VidGrab.app (macOS).
from PyInstaller.utils.hooks import collect_submodules

a = Analysis(
    ["packaging/launch.py"],
    pathex=["."],
    hiddenimports=collect_submodules("yt_dlp"),
    excludes=["tkinter"],
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, a.binaries, a.datas, name="VidGrab", console=True, upx=False)
import sys
if sys.platform == "darwin":
    app = BUNDLE(exe, name="VidGrab.app", bundle_identifier="local.vidgrab")

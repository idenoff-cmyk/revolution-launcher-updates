# Build with: python -m PyInstaller Revolution.spec --noconfirm
from pathlib import Path
from PyInstaller.utils.hooks import collect_submodules, copy_metadata

root = Path(SPECPATH)
datas = [(str(root / 'ui'), 'ui'), (str(root / 'docs'), 'docs'),
         (str(root / 'LICENSE'), '.'), (str(root / 'README.md'), '.')]
if (root / 'licenses').exists():
    datas += [(str(root / 'licenses'), 'licenses')]
for package in ['minecraft-launcher-lib', 'keyring', 'requests', 'pypresence', 'truststore', 'dnspython', 'cryptography']:
    datas += copy_metadata(package)
hidden = collect_submodules('minecraft_launcher_lib')
hidden += ['keyring.backends.Windows', 'win32ctypes.pywin32.win32cred', 'dns.resolver']
a = Analysis([str(root / 'main.py')], pathex=[str(root)], binaries=[], datas=datas,
             hiddenimports=hidden, hookspath=[], runtime_hooks=[],
             excludes=['webview', 'pythonnet', 'clr', 'pytest', 'tkinter', 'PyQt5', 'PyQt6'],
             noarchive=False)
# Qt uses the Windows ICU API (unversioned symbols). The bundled Python runtime
# can contain another ICU build; do not shadow the system implementation.
a.binaries = [entry for entry in a.binaries if Path(entry[0]).name.lower() not in {'icuuc.dll', 'icudt78.dll'}]
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='Revolution',
          debug=False, bootloader_ignore_signals=False, strip=False, upx=False,
          console=False, icon=str(root / 'ui/assets/revolution.ico'))
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='Revolution')

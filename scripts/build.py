"""Build from an explicit source entry; package only a fresh allowlisted folder."""
from pathlib import Path
import hashlib,importlib.metadata,shutil,subprocess,sys,zipfile,json
ROOT=Path(__file__).resolve().parents[1]

def main():
    if sys.platform!='win32': raise SystemExit('Windows上でビルドしてください。')
    if sys.version_info[:3]!=(3,13,5): raise SystemExit('公式配布ビルドにはPython 3.13.5を使用してください。')
    build=ROOT/'build'/'public'; dist=ROOT/'dist'; package=dist/'CodexUsageMeter'
    subprocess.run([sys.executable,'-m','PyInstaller','--noconfirm','--clean','--windowed','--name','CodexUsageMeter','--paths',str(ROOT/'src'),'--icon',str(ROOT/'src/codex_usage_meter/CodexUsageMeter.ico'),'--add-data',str(ROOT/'src/codex_usage_meter/CodexUsageMeter.ico')+';codex_usage_meter','--distpath',str(dist),'--workpath',str(build),'--specpath',str(build),str(ROOT/'scripts/pyinstaller_entry.py')],check=True,cwd=ROOT)
    for name in ('README.md','NOTICE.md','CHANGELOG.md','LICENSE','THIRD_PARTY_NOTICES.md','config.example.json'):
        shutil.copy2(ROOT/name,package/name)
    shutil.copy2(ROOT/'src/codex_usage_meter/CodexUsageMeter.ico',package/'CodexUsageMeter.ico')
    notices=package/'licenses';notices.mkdir(exist_ok=True)
    python_license=Path(sys.base_prefix)/'LICENSE.txt'
    if not python_license.is_file(): raise SystemExit('Python LICENSE.txt is missing.')
    shutil.copy2(python_license,notices/'Python-LICENSE.txt')
    shutil.copy2(ROOT/'licenses/CPython-3.13.5-license.html',notices/'CPython-3.13.5-license.html')
    tcl_root=Path(sys.base_prefix)/'tcl'
    for kind in ('tcl','tk'):
        found=list(tcl_root.glob(kind+'*/license.terms'))
        # Use the matching upstream Tcl notice when the installation omits it.
        if found: shutil.copy2(found[0],notices/(kind.title()+'-license.terms'))
        elif kind=='tcl':
            shutil.copy2(ROOT/'licenses/Tcl-8.6.15-license.terms',notices/'Tcl-license.terms')
        else: raise SystemExit('Tk license.terms is missing.')
    distribution=importlib.metadata.distribution('pyinstaller')
    copied=0
    for item in distribution.files or ():
        text=str(item).replace('\\','/')
        if '.dist-info/licenses/' in text:
            target=notices/'pyinstaller'/text.split('.dist-info/licenses/',1)[1]
            target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(distribution.locate_file(item),target);copied+=1
    if not copied: raise SystemExit('PyInstaller license files are missing.')
    forbidden={'auth.json','config.json','.env'}
    files=[p for p in package.rglob('*') if p.is_file()]
    if any(p.name.lower() in forbidden or p.suffix.lower() in ('.log','.lock') for p in files): raise SystemExit('Private runtime file found in package.')
    archive=dist/'CodexUsageMeter-Windows-x64.zip'
    with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as z:
        for item in files:z.write(item,Path('CodexUsageMeter')/item.relative_to(package))
    checksum=hashlib.sha256(archive.read_bytes()).hexdigest()
    (dist/'SHA256SUMS.txt').write_text(checksum+'  '+archive.name+'\n',encoding='utf8')
    print('Built',archive.name,checksum)

if __name__=='__main__': main()

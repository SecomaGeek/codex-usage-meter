"""OS file locks release automatically after normal exit or termination."""
from pathlib import Path
import os
from ..config import default_config_path

def default_lock_path(): return default_config_path().with_name('instance.lock')

class SingleInstance:
    def __init__(self,path,enabled=True):
        self.path=Path(path); self.enabled=enabled; self.acquired=False; self.file=None
    def __enter__(self):
        if not self.enabled: self.acquired=True; return self
        self.path.parent.mkdir(parents=True,exist_ok=True)
        self.file=self.path.open('a+b')
        self.file.seek(0,2)
        if self.file.tell()==0: self.file.write(b'0'); self.file.flush()
        self.file.seek(0)
        try:
            if os.name=='nt':
                import msvcrt
                msvcrt.locking(self.file.fileno(),msvcrt.LK_NBLCK,1)
            else:
                import fcntl
                fcntl.flock(self.file.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
            self.acquired=True
        except OSError:
            self.file.close(); self.file=None
        return self
    def __exit__(self,*args):
        if self.file:
            try:
                self.file.seek(0)
                if os.name=='nt':
                    import msvcrt
                    msvcrt.locking(self.file.fileno(),msvcrt.LK_UNLCK,1)
                else:
                    import fcntl
                    fcntl.flock(self.file.fileno(),fcntl.LOCK_UN)
            finally: self.file.close(); self.file=None
        self.acquired=False

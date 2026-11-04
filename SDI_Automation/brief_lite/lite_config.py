"""Single location for paths and local-only writable state."""
import os
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo

HERE = Path(os.environ.get('BRIEF_LITE_HOME', Path(__file__).resolve().parent)).resolve()
BASE = Path(os.environ.get('BRIEF_LITE_BASE', HERE.parent)).resolve()
if os.name == 'nt' and (HERE.drive.upper() != 'C:' or str(HERE).startswith('\\\\')):
    raise RuntimeError('Brief Lite writable storage must be on C:')
from dotenv import load_dotenv
load_dotenv(BASE / '.env', override=False)
OUT = HERE / 'out'
WORK = HERE / 'work'
UPLOADS = OUT / 'uploads'
DB = HERE / 'lite.db'
for directory in (OUT, WORK, UPLOADS):
    directory.mkdir(parents=True, exist_ok=True)
# Libraries that create temporary files inherit a safe, app-owned C: directory.
os.environ['TMP'] = os.environ['TEMP'] = str(WORK)
os.environ.setdefault('TF_CPP_MIN_LOG_LEVEL', '3')
PORT = int(os.environ.get('BRIEF_LITE_PORT', '5020'))
ZONE = ZoneInfo('Europe/London')

def now():
    return datetime.now(ZONE)

def stamp():
    return now().isoformat(timespec='microseconds')

def within(path, root):
    try:
        Path(path).resolve().relative_to(Path(root).resolve())
        return True
    except (ValueError, OSError):
        return False

def writable(path):
    path = Path(path).resolve()
    if not within(path, HERE) or (os.name == 'nt' and path.drive.upper() != 'C:'):
        raise ValueError('Writes are restricted to the Brief Lite folder on C:')
    return path

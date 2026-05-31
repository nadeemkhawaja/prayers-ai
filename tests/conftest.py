import os
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
os.environ.setdefault("REPO_PATH", str(ROOT))
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scraper"))

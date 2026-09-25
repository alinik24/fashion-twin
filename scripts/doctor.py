import importlib.util,sys
from pathlib import Path
print(f"python={sys.version.split()[0]}")
if sys.version_info < (3,10): print("MISSING: Python 3.10+"); raise SystemExit(1)
if not (Path("requirements.txt").exists() or Path("pyproject.toml").exists()): print("MISSING: dependency contract"); raise SystemExit(1)
print("doctor=PASS")

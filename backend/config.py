from pathlib import Path
import os

ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("MPLCONFIGDIR", str(ROOT / ".cache" / "matplotlib"))
DATA = ROOT / "data" / "processed"
MODELS = Path(os.environ.get("MATSCOPE_MODELS", str(ROOT / "artifacts" / "models")))
RUNTIME = Path(os.environ.get("MATSCOPE_RUNTIME", str(ROOT / "data" / "runtime")))
DATA_VERSION = "elastic-2015-v1"

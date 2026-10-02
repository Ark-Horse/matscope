import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.config import DATA
from backend.ml import train

if __name__ == "__main__":
    catalog = json.loads((DATA / "catalog.json").read_text(encoding="utf-8"))
    structures = json.loads((DATA / "structures.json").read_text(encoding="utf-8"))
    report = train(catalog, structures)
    print(json.dumps({"train_count": report["train_count"], "test_count": report["test_count"], "metrics": report["metrics"]}, indent=2))

import json
import numpy as np
import joblib
from sklearn.compose import TransformedTargetRegressor
from sklearn.ensemble import ExtraTreesRegressor
from sklearn.dummy import DummyRegressor
from sklearn.model_selection import GroupShuffleSplit
from sklearn.metrics import mean_absolute_error, r2_score
from pymatgen.core import Structure
from backend.config import DATA, MODELS
from backend.science import features, FEATURE_NAMES

MODEL_VERSION = "extra-trees-log-v1"


def train(catalog: list, structures: dict) -> dict:
    rows = [r for r in catalog if r["bulk_modulus"] > 0 and r["shear_modulus"] > 0]
    x = np.array([features(Structure.from_dict(structures[r["id"]])) for r in rows])
    y = np.array([[r["bulk_modulus"], r["shear_modulus"]] for r in rows])
    groups = [Structure.from_dict(structures[r["id"]]).composition.reduced_formula for r in rows]
    train_idx, test_idx = next(GroupShuffleSplit(n_splits=1, test_size=0.2, random_state=42).split(x, y, groups))
    estimator = ExtraTreesRegressor(n_estimators=240, min_samples_leaf=2, max_features=0.9, random_state=42, n_jobs=-1)
    model = TransformedTargetRegressor(regressor=estimator, func=np.log1p, inverse_func=np.expm1)
    model.fit(x[train_idx], y[train_idx])
    pred = model.predict(x[test_idx])
    baseline = DummyRegressor(strategy="mean").fit(x[train_idx], y[train_idx]).predict(x[test_idx])
    metrics = {}
    for j, name in enumerate(["bulk", "shear"]):
        metrics[name] = {"mae": round(float(mean_absolute_error(y[test_idx, j], pred[:, j])), 3), "r2": round(float(r2_score(y[test_idx, j], pred[:, j])), 4), "baseline_mae": round(float(mean_absolute_error(y[test_idx, j], baseline[:, j])), 3)}
    importance = model.regressor_.feature_importances_
    report = {"version": MODEL_VERSION, "algorithm": "ExtraTrees · log1p targets", "feature_count": len(FEATURE_NAMES), "seed": 42,
              "train_count": len(train_idx), "test_count": len(test_idx), "split": "按约化化学式分组，80% / 20% 留出测试", "metrics": metrics,
              "feature_importance": sorted([{"name": n, "value": round(float(v), 5)} for n, v in zip(FEATURE_NAMES, importance)], key=lambda r: -r["value"])[:12],
              "samples": [{"id": rows[i]["id"], "formula": rows[i]["formula"], "actual_bulk": float(y[i, 0]), "predicted_bulk": round(float(p[0]), 3), "actual_shear": float(y[i, 1]), "predicted_shear": round(float(p[1]), 3)} for i, p in zip(test_idx, pred)]}
    MODELS.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, MODELS / "elastic.joblib", compress=3)
    (DATA / "model_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    (DATA / "split.json").write_text(json.dumps({"train": [rows[i]["id"] for i in train_idx], "test": [rows[i]["id"] for i in test_idx]}, indent=2), encoding="utf-8")
    return report


def predict(model, structure: Structure) -> dict:
    prediction = model.predict(features(structure).reshape(1, -1))[0]
    return {"bulk_modulus": round(float(prediction[0]), 3), "shear_modulus": round(float(prediction[1]), 3), "model_version": MODEL_VERSION, "units": "GPa"}

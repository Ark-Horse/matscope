import json
import numpy as np
import pytest
from fastapi.testclient import TestClient
from pymatgen.core import Structure
from backend.config import DATA, ROOT
from backend.science import diffraction, parse_spectrum, process_spectrum, match_spectrum
import backend.main as service


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    service.RUNTIME = tmp_path_factory.mktemp("matscope-runtime")
    with TestClient(service.app) as test_client:
        yield test_client


def test_grouped_split_has_no_composition_leakage():
    split = json.loads((DATA / "split.json").read_text())
    structures = json.loads((DATA / "structures.json").read_text())
    groups = lambda ids: {Structure.from_dict(structures[i]).composition.reduced_formula for i in ids}
    assert not groups(split["train"]) & groups(split["test"])


def test_lattice_expansion_moves_same_hkl_to_lower_angle(client):
    material_id = client.get("/api/overview").json()["default_id"]
    structure = Structure.from_dict(client.get(f"/api/materials/{material_id}").json()["structure"])
    original = diffraction(structure)
    structure.scale_lattice(structure.volume * 1.03 ** 3)
    expanded = diffraction(structure)
    assert original[0]["hkl"] == expanded[0]["hkl"]
    assert expanded[0]["angle"] < original[0]["angle"]
    # Bragg law gives the same first-plane spacing after correcting for expansion.
    assert expanded[0]["d"] / original[0]["d"] == pytest.approx(1.03, abs=1e-4)


def test_noisy_silicon_retrieves_silicon(client):
    material_id = client.get("/api/overview").json()["default_id"]
    demo = client.get(f"/api/xrd/demo/{material_id}").json()
    assert demo["candidates"][0]["material_id"] == material_id
    assert demo["candidates"][0]["similarity"] > 0.95
    analysis_id = demo["analysis_id"]
    assert client.get(f"/api/history/{analysis_id}").json()["parameters"]["simulated"] is True
    report = client.get(f"/api/history/{analysis_id}/report")
    assert report.status_code == 200 and "相似度" in report.text


def test_uploaded_samples_support_entire_workflow(client):
    cif = (ROOT / "data/examples/silicon.cif").read_bytes()
    imported = client.post("/api/structures/import", files={"file": ("silicon.cif", cif)}).json()
    assert imported["formula"] == "Si"
    body = {"structure": imported["structure"]}
    simulated = client.post("/api/xrd/simulate", json=body)
    assert simulated.status_code == 200
    assert len(simulated.json()["x"]) == len(simulated.json()["y"]) == 1701
    predicted = client.post("/api/predict", json=body).json()
    assert predicted["reference"] is None and predicted["split"] == "external"
    assert predicted["bulk_modulus"] > 0 and predicted["shear_modulus"] > 0
    csv = (ROOT / "data/examples/silicon_simulated_noisy.csv").read_bytes()
    uploaded = client.post("/api/xrd/analyze", files={"file": ("demo.csv", csv)})
    assert uploaded.status_code == 200
    assert uploaded.json()["candidates"][0]["formula"] == "Si"


@pytest.mark.parametrize("text", ["2theta,intensity\n10,nan", "\n".join(f"{i},0" for i in range(10)), "broken file"])
def test_invalid_spectrum_returns_useful_error(client, text):
    response = client.post("/api/xrd/analyze", files={"file": ("bad.csv", text.encode())})
    assert response.status_code == 422
    assert isinstance(response.json()["detail"], str)


def test_constant_spectrum_rejected():
    with pytest.raises(ValueError, match="强度变化"):
        process_spectrum(np.linspace(5,90,100), np.ones(100))


def test_partial_range_match_does_not_pad_missing_measurements(client):
    spectrum = (ROOT / "data/examples/silicon_simulated_noisy.csv").read_text()
    x,y = parse_spectrum(spectrum)
    keep = (x >= 20) & (x <= 70)
    processed = process_spectrum(x[keep],y[keep])
    library = json.loads((DATA / "xrd_library.json").read_text())
    matches = match_spectrum(processed["x"], processed["y"], library)
    assert matches[0]["material_id"] == client.get("/api/overview").json()["default_id"]


def test_model_beats_mean_baseline(client):
    model = client.get("/api/overview").json()["model"]
    assert model["test_count"] > 100
    for metric in model["metrics"].values():
        assert metric["mae"] < metric["baseline_mae"]


def test_material_filter_and_prediction_reference(client):
    result = client.get("/api/materials", params={"max_density":4,"min_bulk":100}).json()
    assert result["total"] > 0
    assert all(r["density"]<=4 and r["bulk_modulus"]>=100 for r in result["items"])
    sample = client.get("/api/overview").json()["model"]["samples"][0]
    prediction = client.post("/api/predict",json={"material_id":sample["id"]}).json()
    assert prediction["split"] == "test"
    assert prediction["reference"]["bulk_modulus"] == pytest.approx(sample["actual_bulk"])
    assert client.get("/api/materials/nonexistent").status_code == 404

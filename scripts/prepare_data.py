"""Download a hash-verified public dataset and create portable offline artifacts."""
import argparse
import gzip
import hashlib
import json
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pymatgen.core import Structure
from backend.config import ROOT, DATA
from backend.science import describe, diffraction, broaden, GRID, spectrum_csv
from backend.ml import train

URL = "https://ndownloader.figshare.com/files/13220603"
MIRROR = "https://s3-eu-west-1.amazonaws.com/pfigshare-u-files/13220603/elastic_tensor_2015.json.gz"
SHA256 = "8c3b342f75da7e7baa1b769b59554485fd647f4cb1da9318d0d1ba3b3b838183"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--offline", action="store_true")
    args = parser.parse_args()
    raw = ROOT / "data/raw/elastic_tensor_2015.json.gz"
    if not raw.exists():
        if args.offline:
            raise SystemExit("Raw data missing. Run without --offline once.")
        raw.parent.mkdir(parents=True, exist_ok=True)
        print("Downloading elastic_tensor_2015...", flush=True)
        try:
            urllib.request.urlretrieve(URL, raw)
        except Exception:
            urllib.request.urlretrieve(MIRROR, raw)
    if hashlib.sha256(raw.read_bytes()).hexdigest() != SHA256:
        raise SystemExit("Dataset SHA256 mismatch. Remove the raw file and download again.")
    with gzip.open(raw, "rt", encoding="utf-8") as stream:
        document = json.load(stream)
    catalog, structures, skipped = [], {}, []
    for row in document["data"]:
        record = dict(zip(document["columns"], row))
        try:
            structure = Structure.from_dict(record["structure"])
            if not structure.is_ordered:
                raise ValueError("disordered structure")
            info = describe(structure)
            material_id = record["material_id"]
            info.pop("lattice")
            catalog.append({"id": material_id, **info, "bulk_modulus": float(record["K_VRH"]), "shear_modulus": float(record["G_VRH"]),
                            "poisson_ratio": float(record["poisson_ratio"]), "anisotropy": float(record["elastic_anisotropy"]), "source": "de Jong et al. · DFT-PBE · 2015"})
            structures[material_id] = structure.as_dict()
        except Exception as exc:
            skipped.append({"id": record.get("material_id"), "reason": str(exc)})
    # Put familiar, simple structures first while retaining all prepared entries.
    preferred = ["Si", "C", "Fe", "Cu", "Al", "TiO2", "MgO", "NaCl", "ZnO", "GaN", "SiC"]
    catalog.sort(key=lambda r: (preferred.index(r["formula"]) if r["formula"] in preferred else 99, r["nsites"], r["formula"]))
    DATA.mkdir(parents=True, exist_ok=True)
    (DATA / "catalog.json").write_text(json.dumps(catalog, ensure_ascii=False, indent=2), encoding="utf-8")
    (DATA / "structures.json").write_text(json.dumps(structures, separators=(",", ":")), encoding="utf-8")
    print(f"Prepared {len(catalog)} structures; skipped {len(skipped)}", flush=True)
    library = {}
    for record in [r for r in catalog if r["nsites"] <= 24][:120]:
        library[record["id"]] = diffraction(Structure.from_dict(structures[record["id"]]))
        if len(library) % 20 == 0:
            print(f"XRD library: {len(library)}", flush=True)
    (DATA / "xrd_library.json").write_text(json.dumps(library, separators=(",", ":")), encoding="utf-8")
    provenance = {"dataset": "elastic_tensor_2015", "url": URL, "storage_mirror": MIRROR, "sha256": SHA256, "original_count": 1181, "prepared_count": len(catalog), "xrd_count": len(library), "skipped": skipped,
                  "citation": "de Jong et al., Charting the complete elastic properties of inorganic crystalline compounds, Scientific Data 2, 150009 (2015).", "doi": "10.1038/sdata.2015.9",
                  "metadata_url": "https://raw.githubusercontent.com/hackingmaterials/matminer/main/src/matminer/datasets/dataset_metadata.json", "property_origin": "DFT-PBE computed reference values; not experimental measurements", "xrd_wavelength_angstrom": 1.5406}
    (DATA / "provenance.json").write_text(json.dumps(provenance, indent=2), encoding="utf-8")
    examples = ROOT / "data/examples"
    examples.mkdir(parents=True, exist_ok=True)
    from pymatgen.io.cif import CifWriter
    demo = next(r for r in catalog if r["formula"] == "Si" and r["space_group"] == 227)
    demo_structure = Structure.from_dict(structures[demo["id"]])
    (examples / "silicon.cif").write_text(str(CifWriter(demo_structure)), encoding="utf-8")
    import numpy as np
    rng = np.random.default_rng(42)
    signal = broaden(library[demo["id"]])
    noisy = np.maximum(signal + rng.normal(0, 1.0, len(signal)) + 3, 0)
    (examples / "silicon_simulated_noisy.csv").write_text(spectrum_csv(GRID, noisy), encoding="utf-8")
    report = train(catalog, structures)
    print(json.dumps(report["metrics"], indent=2), flush=True)


if __name__ == "__main__":
    main()

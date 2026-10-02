"""Pure scientific operations shared by preparation scripts and API."""
import csv
import io
import re
import numpy as np
from pymatgen.core import Structure
from pymatgen.analysis.diffraction.xrd import XRDCalculator
from pymatgen.symmetry.analyzer import SpacegroupAnalyzer
from pymatgen.io.cif import CifWriter
from scipy.ndimage import gaussian_filter1d
from scipy.signal import find_peaks, savgol_filter

WAVELENGTH = 1.5406  # Cu K-alpha1, angstrom
GRID = np.round(np.arange(5.0, 90.0001, 0.05), 4)
PROPERTIES = ["Z", "atomic_mass", "X", "atomic_radius", "row", "group"]
FEATURE_NAMES = [f"{p}_{s}" for p in PROPERTIES for s in ["mean", "std", "min", "max", "range"]] + ["density", "volume_per_atom", "element_count", "composition_entropy"]


def features(structure: Structure) -> np.ndarray:
    composition = structure.composition.element_composition.fractional_composition
    elements = list(composition.elements)
    weights = np.array([composition[e] for e in elements], dtype=float)
    values = []
    for prop in PROPERTIES:
        arr = np.array([float(getattr(e, prop) or 0) for e in elements])
        mean = float(arr @ weights)
        values.extend([mean, float(np.sqrt(((arr - mean) ** 2) @ weights)), float(arr.min()), float(arr.max()), float(np.ptp(arr))])
    values.extend([float(structure.density), structure.volume / len(structure), len(elements), float(-(weights * np.log(weights)).sum())])
    return np.array(values, dtype=float)


def describe(structure: Structure) -> dict:
    analyzer = SpacegroupAnalyzer(structure, symprec=0.01)
    lattice = structure.lattice
    return {
        "formula": structure.composition.reduced_formula,
        "elements": sorted(e.symbol for e in structure.composition.elements),
        "density": round(float(structure.density), 5),
        "volume": round(float(structure.volume), 5),
        "nsites": len(structure),
        "space_group": analyzer.get_space_group_number(),
        "symbol": analyzer.get_space_group_symbol(),
        "crystal_system": analyzer.get_crystal_system(),
        "lattice": {"a": lattice.a, "b": lattice.b, "c": lattice.c, "alpha": lattice.alpha, "beta": lattice.beta, "gamma": lattice.gamma, "matrix": lattice.matrix.tolist()},
    }


def crystal_payload(structure: Structure) -> dict:
    return {**describe(structure), "cif": str(CifWriter(structure)), "structure": structure.as_dict(),
            "atoms": [{"element": site.specie.symbol, "xyz": site.coords.tolist(), "fractional": site.frac_coords.tolist()} for site in structure]}


def diffraction(structure: Structure, wavelength: float = WAVELENGTH) -> list:
    pattern = XRDCalculator(wavelength=wavelength).get_pattern(structure, two_theta_range=(5, 90))
    return [{"angle": round(float(x), 5), "intensity": round(float(y), 5), "d": round(float(d), 5),
             "hkl": [list(h["hkl"]) for h in hkls]} for x, y, d, hkls in zip(pattern.x, pattern.y, pattern.d_hkls, pattern.hkls)]


def broaden(peaks: list, width: float = 0.18) -> np.ndarray:
    profile = np.zeros(len(GRID))
    sigma = width / 2.35482
    for peak in peaks:
        profile += peak["intensity"] * np.exp(-0.5 * ((GRID - peak["angle"]) / sigma) ** 2)
    if profile.max() > 0:
        profile *= 100 / profile.max()
    return profile


def parse_spectrum(text: str) -> tuple:
    """Accept two-column CSV, TSV or whitespace XY; allow an initial header."""
    rows = []
    for line in text.lstrip("\ufeff").splitlines():
        line = line.strip()
        if not line or line.startswith(("#", "!")):
            continue
        parts = re.split(r"[,;\s]+", line)
        try:
            x, y = float(parts[0]), float(parts[1])
        except (ValueError, IndexError):
            if not rows:
                continue
            raise ValueError("谱图中包含无法解析的数据行，请提供两列数值：2θ 和强度。")
        if not np.isfinite([x, y]).all():
            raise ValueError("谱图不能包含 NaN 或无穷大。")
        rows.append((x, y))
    if len(rows) < 10 or len(rows) > 100000:
        raise ValueError("请提供 10–100000 个谱图数据点。")
    arr = np.array(rows)
    arr = arr[np.argsort(arr[:, 0])]
    x, idx = np.unique(arr[:, 0], return_index=True)
    y = arr[idx, 1]
    if len(x) < 10 or x[0] < 0 or x[-1] > 180 or x[-1] - x[0] < 2:
        raise ValueError("2θ 应在 0°–180° 之间，并覆盖至少 2°。")
    if y.max() <= 0:
        raise ValueError("谱图强度需包含正值。")
    return x, y


def process_spectrum(x, y, smoothing: bool = True) -> dict:
    x, y = np.array(x, dtype=float), np.array(y, dtype=float)
    # Constant baseline correction; this deliberately avoids claiming full refinement.
    # For sparse diffraction peaks, the median estimates a constant background
    # without biasing it downward by the lowest noise samples.
    processed = np.maximum(y - np.median(y), 0)
    if smoothing and len(y) >= 11:
        processed = np.maximum(savgol_filter(processed, 11, 3), 0)
    if processed.max() <= 1e-10:
        raise ValueError("谱图缺少可辨识的强度变化。")
    processed *= 100 / processed.max()
    raw = y * 100 / y.max()
    indices, props = find_peaks(processed, prominence=3, distance=max(1, int(0.15 / np.median(np.diff(x)))))
    peaks = [{"angle": round(float(x[i]), 4), "intensity": round(float(processed[i]), 3), "prominence": round(float(p), 3)} for i, p in zip(indices, props["prominences"])]
    # Preserve measured range when matching; do not invent missing intensities.
    return {"x": x.tolist(), "raw": raw.tolist(), "y": processed.tolist(), "peaks": sorted(peaks, key=lambda p: -p["intensity"])[:40]}


def match_spectrum(x, y, library: dict, top_k: int = 5) -> list:
    x, y = np.asarray(x), np.asarray(y)
    mask = (GRID >= max(5, x.min())) & (GRID <= min(90, x.max()))
    if mask.sum() < 40:
        raise ValueError("谱图需在 5°–90° 范围内覆盖至少 2°。")
    query = np.interp(GRID[mask], x, y)
    # Slight smoothing makes the finite library matcher tolerant to peak-width changes.
    query = gaussian_filter1d(query, 1)
    results = []
    for material_id, peaks in library.items():
        # Apply the same peak-shape smoothing to both query and reference.
        ref = gaussian_filter1d(np.maximum(savgol_filter(broaden(peaks), 11, 3), 0), 1)
        best, best_shift = 0.0, 0.0
        for shift in [-0.2, -0.1, 0.0, 0.1, 0.2]:
            comparison = np.interp(GRID[mask] - shift, GRID, ref, left=0, right=0)
            denominator = np.linalg.norm(query) * np.linalg.norm(comparison)
            score = float(query @ comparison / denominator) if denominator else 0.0
            if score > best:
                best, best_shift = score, shift
        results.append({"material_id": material_id, "similarity": round(best, 5), "shift": best_shift})
    return sorted(results, key=lambda r: -r["similarity"])[:top_k]


def spectrum_csv(x, y) -> str:
    stream = io.StringIO()
    writer = csv.writer(stream)
    writer.writerow(["two_theta_deg", "intensity"])
    writer.writerows(zip(x, y))
    return stream.getvalue()

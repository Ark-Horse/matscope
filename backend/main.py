from contextlib import asynccontextmanager
import html
import json
import sqlite3
from datetime import datetime, timezone
import uuid
import numpy as np
import joblib
from fastapi import FastAPI, File, UploadFile, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response, HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from pymatgen.core import Structure
from backend.config import ROOT, DATA, MODELS, RUNTIME, DATA_VERSION
from backend.science import crystal_payload, diffraction, broaden, GRID, parse_spectrum, process_spectrum, match_spectrum
from backend.ml import train, predict

state = {}


def database():
    connection = sqlite3.connect(RUNTIME / "analyses.sqlite3")
    connection.row_factory = sqlite3.Row
    return connection


def save_analysis(kind: str, title: str, material_id, parameters: dict, result: dict):
    analysis_id = uuid.uuid4().hex[:12]
    with database() as conn:
        conn.execute("INSERT INTO analyses VALUES (?,?,?,?,?,?,?)", (analysis_id, datetime.now(timezone.utc).isoformat(), kind, title, material_id, json.dumps(parameters), json.dumps(result, ensure_ascii=False)))
    return analysis_id


@asynccontextmanager
async def lifespan(app):
    if not (DATA / "catalog.json").exists():
        raise RuntimeError("Prepared data missing. Run: uv run python scripts/prepare_data.py")
    for key, filename in [("catalog", "catalog.json"), ("structures", "structures.json"), ("library", "xrd_library.json"), ("provenance", "provenance.json")]:
        state[key] = json.loads((DATA / filename).read_text(encoding="utf-8"))
    state["index"] = {r["id"]: r for r in state["catalog"]}
    if not (MODELS / "elastic.joblib").exists():
        train(state["catalog"], state["structures"])
    state["model"] = joblib.load(MODELS / "elastic.joblib")
    state["model_report"] = json.loads((DATA / "model_report.json").read_text(encoding="utf-8"))
    state["test_ids"] = set(json.loads((DATA / "split.json").read_text(encoding="utf-8"))["test"])
    RUNTIME.mkdir(parents=True, exist_ok=True)
    with database() as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS analyses (id TEXT PRIMARY KEY, created_at TEXT, kind TEXT, title TEXT, material_id TEXT, parameters TEXT, result TEXT)")
    yield


app = FastAPI(title="MatScope API", version="0.1.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"], allow_methods=["*"], allow_headers=["*"])


@app.exception_handler(ValueError)
async def bad_input(request, exc):
    return JSONResponse(status_code=422, content={"detail": str(exc)})


class StructureRequest(BaseModel):
    material_id: str | None = None
    structure: dict | None = None
    scale: float = Field(default=1, ge=0.9, le=1.1)


class XRDRequest(StructureRequest):
    wavelength: float = Field(default=1.5406, ge=0.5, le=2.5)
    width: float = Field(default=0.18, ge=0.08, le=0.8)


def resolve(body: StructureRequest):
    if body.structure is not None:
        structure = Structure.from_dict(body.structure)
    elif body.material_id in state["structures"]:
        structure = Structure.from_dict(state["structures"][body.material_id])
    else:
        raise HTTPException(404, "请选择材料或上传 CIF 结构。")
    if not structure.is_ordered or len(structure) > 200:
        raise ValueError("当前版本支持不超过 200 个原子的有序晶体结构。")
    if not np.isfinite(structure.lattice.matrix).all() or structure.volume < 1 or structure.volume > 100000:
        raise ValueError("晶胞体积无效或超出本平台范围。")
    if body.scale != 1:
        structure.scale_lattice(structure.volume * body.scale ** 3)
    return structure


@app.get("/api/health")
def health():
    return {"status": "ok", "data_version": DATA_VERSION, "model_ready": bool(state.get("model"))}


@app.get("/api/overview")
def overview():
    catalog = state["catalog"]
    return {"material_count": len(catalog), "spectrum_count": len(state["library"]), "element_count": len({e for r in catalog for e in r["elements"]}),
            "systems": [{"name": k, "count": sum(r["crystal_system"] == k for r in catalog)} for k in sorted({r["crystal_system"] for r in catalog})],
            "provenance": state["provenance"], "model": state["model_report"], "default_id": next(r["id"] for r in catalog if r["formula"] == "Si" and r["space_group"] == 227)}


@app.get("/api/materials")
def materials(q: str = "", system: str = "", max_density: float = 30, min_bulk: float = 0, min_shear: float = 0, sort: str = "default"):
    query = q.strip().lower()
    rows = [dict(r, in_library=r["id"] in state["library"], split="test" if r["id"] in state["test_ids"] else "train") for r in state["catalog"]
            if (not query or query in r["formula"].lower() or query in r["id"] or any(query == e.lower() for e in r["elements"]))
            and (not system or r["crystal_system"] == system) and r["density"] <= max_density and r["bulk_modulus"] >= min_bulk and r["shear_modulus"] >= min_shear]
    if sort in ["bulk_modulus", "shear_modulus", "density"]:
        rows.sort(key=lambda r: r[sort], reverse=sort != "density")
    return {"items": rows, "total": len(rows)}


@app.get("/api/materials/{material_id}")
def material(material_id: str):
    if material_id not in state["index"]:
        raise HTTPException(404, "未找到该材料。")
    record = state["index"][material_id]
    structure = Structure.from_dict(state["structures"][material_id])
    return {**record, **crystal_payload(structure), "in_library": material_id in state["library"], "split": "test" if material_id in state["test_ids"] else "train"}


@app.get("/api/materials/{material_id}/cif")
def cif(material_id: str):
    detail = material(material_id)
    return Response(detail["cif"], media_type="chemical/x-cif", headers={"Content-Disposition": f'attachment; filename="{material_id}.cif"'})


@app.post("/api/structures/import")
async def import_structure(file: UploadFile = File(...)):
    contents = await file.read(2_000_001)
    if len(contents) > 2_000_000:
        raise ValueError("CIF 文件不能超过 2 MB。")
    try:
        structure = Structure.from_str(contents.decode("utf-8-sig"), fmt="cif")
        resolve(StructureRequest(structure=structure.as_dict()))
        return {"id": "uploaded", **crystal_payload(structure), "source": "用户上传 CIF", "split": "external", "in_library": False}
    except HTTPException:
        raise
    except Exception as exc:
        raise ValueError(f"无法解析 CIF：{exc}") from exc


@app.post("/api/structures/transform")
def transform(body: StructureRequest):
    return crystal_payload(resolve(body))


@app.post("/api/xrd/simulate")
def simulate(body: XRDRequest):
    structure = resolve(body)
    peaks = state["library"].get(body.material_id) if body.structure is None and body.scale == 1 and body.wavelength == 1.5406 else None
    if peaks is None:
        peaks = diffraction(structure, body.wavelength)
    return {"x": GRID.tolist(), "y": np.round(broaden(peaks, body.width), 5).tolist(), "peaks": peaks, "wavelength": body.wavelength, "width": body.width, "source": "pymatgen · 几何结构衍射模拟", "formula": structure.composition.reduced_formula}


@app.get("/api/xrd/demo/{material_id}")
def demo(material_id: str, noise: float = Query(default=1.0, ge=0, le=5)):
    if material_id not in state["library"]:
        raise HTTPException(404, "当前材料没有预计算谱，请先选择谱库中的材料。")
    signal = broaden(state["library"][material_id])
    measured = np.maximum(signal + np.random.default_rng(42).normal(0, noise, len(signal)) + 3, 0)
    result = process_spectrum(GRID, measured)
    matches = match_spectrum(result["x"], result["y"], state["library"])
    candidates = [{**m, "formula": state["index"][m["material_id"]]["formula"], "symbol": state["index"][m["material_id"]]["symbol"]} for m in matches]
    result.update({"candidates": candidates, "source": "模拟加噪演示谱 · Cu Kα₁", "filename": "simulated_demo.csv", "library_count": len(state["library"])})
    result["analysis_id"] = save_analysis("xrd", f'{state["index"][material_id]["formula"]} 衍射谱检索', material_id, {"noise": noise, "simulated": True, "wavelength": 1.5406}, result)
    return result


@app.post("/api/xrd/analyze")
async def analyze(file: UploadFile = File(...), smoothing: bool = True):
    contents = await file.read(3_000_001)
    if len(contents) > 3_000_000:
        raise ValueError("谱图文件不能超过 3 MB。")
    try:
        x, y = parse_spectrum(contents.decode("utf-8-sig"))
    except UnicodeDecodeError as exc:
        raise ValueError("请使用 UTF-8 编码的 CSV 或 XY 文件。") from exc
    result = process_spectrum(x, y, smoothing)
    matches = match_spectrum(result["x"], result["y"], state["library"])
    result.update({"candidates": [{**m, "formula": state["index"][m["material_id"]]["formula"], "symbol": state["index"][m["material_id"]]["symbol"]} for m in matches],
                   "source": "用户上传谱图 · 库内候选检索", "filename": file.filename, "library_count": len(state["library"])})
    result["analysis_id"] = save_analysis("xrd", "上传谱图候选检索", matches[0]["material_id"] if matches else None, {"smoothing": smoothing, "filename": file.filename}, result)
    return result


@app.post("/api/predict")
def prediction(body: StructureRequest):
    structure = resolve(body)
    result = predict(state["model"], structure)
    result.update({"formula": structure.composition.reduced_formula, "source": "机器学习预测", "split": "test" if body.material_id in state["test_ids"] else ("train" if body.material_id in state["index"] else "external")})
    reference = state["index"].get(body.material_id) if body.scale == 1 and body.structure is None else None
    result["reference"] = {"bulk_modulus": reference["bulk_modulus"], "shear_modulus": reference["shear_modulus"]} if reference else None
    result["analysis_id"] = save_analysis("prediction", f'{result["formula"]} 弹性性质预测', body.material_id, {"scale": body.scale}, result)
    return result


@app.get("/api/history")
def history():
    with database() as conn:
        return [dict(r) for r in conn.execute("SELECT id,created_at,kind,title,material_id FROM analyses ORDER BY created_at DESC LIMIT 100")]


@app.get("/api/history/{analysis_id}")
def analysis_record(analysis_id: str):
    with database() as conn:
        row = conn.execute("SELECT * FROM analyses WHERE id=?", (analysis_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "未找到分析记录。")
    return {**dict(row), "parameters": json.loads(row["parameters"]), "result": json.loads(row["result"])}


@app.get("/api/history/{analysis_id}/report", response_class=HTMLResponse)
def report(analysis_id: str):
    record = analysis_record(analysis_id)
    result = record["result"]
    if record["kind"] == "prediction":
        body = f'<table><tr><th>性质</th><th>预测 / GPa</th><th>DFT 参考 / GPa</th></tr>'
        for label, key in [("体积模量 K", "bulk_modulus"), ("剪切模量 G", "shear_modulus")]:
            ref = (result.get("reference") or {}).get(key, "—")
            body += f'<tr><td>{label}</td><td>{result[key]:.2f}</td><td>{ref}</td></tr>'
        body += '</table><p>参考值来自 DFT-PBE；预测为课程演示模型输出。</p>'
    else:
        body = '<table><tr><th>候选</th><th>空间群</th><th>相似度</th></tr>'
        for c in result["candidates"]:
            body += f'<tr><td>{html.escape(c["formula"])} · {html.escape(c["material_id"])}</td><td>{html.escape(c["symbol"])}</td><td>{c["similarity"]:.4f}</td></tr>'
        body += '</table><p>相似度是有限候选库中的谱形匹配分数，不是概率；候选不等于已确定结构。检索参考谱使用 Cu Kα₁ 1.5406 Å。</p>'
    return f'''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>MatScope 分析报告</title><style>body{{font:16px/1.8 system-ui;max-width:850px;margin:50px auto;color:#202d44}}h1{{color:#574ae2}}table{{width:100%;border-collapse:collapse}}td,th{{padding:12px;border-bottom:1px solid #ddd;text-align:left}}pre{{white-space:pre-wrap;background:#f4f5f8;padding:20px}}button{{padding:10px 20px}}@media print{{button{{display:none}}}}</style><body><p>MatScope / MATERIALS INTELLIGENCE</p><h1>{html.escape(record['title'])}</h1><p>记录：{analysis_id} · UTC {html.escape(record['created_at'])}</p>{body}<h3>分析参数</h3><pre>{html.escape(json.dumps(record['parameters'],ensure_ascii=False,indent=2))}</pre><p>数据：de Jong et al., Scientific Data 2, 150009 (2015). DOI: 10.1038/sdata.2015.9</p><button onclick="window.print()">打印 / 保存 PDF</button></body></html>'''


@app.get("/api/examples/{filename}")
def example(filename: str):
    if filename not in ["silicon.cif", "silicon_simulated_noisy.csv"]:
        raise HTTPException(404)
    return FileResponse(ROOT / "data/examples" / filename, filename=filename)


@app.get("/api/research")
def research():
    return {"paper_adapter": {"name": "XRDecoupler", "status": "not_installed", "repository": "https://github.com/baigeiguai/XRDecoupler", "paper": "https://ojs.aaai.org/index.php/AAAI/article/view/38657", "note": "当前实际算法为谱库匹配和 ExtraTrees 性质回归。论文模型为独立扩展接口，尚未部署。"}}


if (ROOT / "frontend/dist").exists():
    app.mount("/", StaticFiles(directory=ROOT / "frontend/dist", html=True), name="web")

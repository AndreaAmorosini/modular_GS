"""
FastAPI backend for the ModularGS web interface.

Replaces the previous Streamlit GUI. Serves the vanilla JS frontend from
core/gui/static/ and exposes a REST + WebSocket API on top of the existing
core modules (Validator, MethodInstaller, SignatureVerifier, JobManager).

Run with: python main.py web
"""

import asyncio
import json
import os
import platform
import shutil
import subprocess
import sys
import time

try:
    import tomllib as toml
except ImportError:
    import tomli as toml
import tomli_w
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, UploadFile, File, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.jobs import JobManager, python_executable
from core.utils import SignatureVerifier, get_dir_size

METHODS_DIR = PROJECT_ROOT / "methods"
PIPELINES_DIR = PROJECT_ROOT / "pipelines"
INPUTS_DIR = PROJECT_ROOT / "inputs"
OUTPUTS_DIR = PROJECT_ROOT / "output"
ENVS_DIR = PROJECT_ROOT / ".envs"
TMP_DIR = PROJECT_ROOT / ".tmp"
STATIC_DIR = Path(__file__).resolve().parent / "static"

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tiff"}
VIDEO_EXTS = {".mp4", ".mov", ".avi", ".mkv", ".webm"}

app = FastAPI(title="ModularGS", docs_url="/api/docs", openapi_url="/api/openapi.json")
job_manager = JobManager()
verifier = SignatureVerifier()


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

_disk_usage_cache = {"value": 0, "ts": 0.0}


def _du_bytes(path: Path) -> int:
    now = time.time()
    if now - _disk_usage_cache["ts"] < 60:
        return _disk_usage_cache["value"]
    total = get_dir_size(path)
    _disk_usage_cache["value"] = total
    _disk_usage_cache["ts"] = now
    return total


def _readable(n: int) -> str:
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if n < 1024:
            return f"{n:.2f} {unit}"
        n /= 1024
    return f"{n:.2f} PB"


def _env_name_for(method_id: str, metadata: dict) -> str:
    """Env folder name, matching main.py (derived from the method title)."""
    title = metadata.get("title", method_id)
    return str(title).replace(" ", "_").replace("-", "_").lower()


def _is_installed(method_id: str, metadata: dict) -> bool:
    for candidate in (_env_name_for(method_id, metadata), method_id):
        env_path = ENVS_DIR / candidate
        if (env_path / ".install_complete").exists():
            return True
    return False


def _get_registry() -> dict:
    from core.validation import Validator
    validator = Validator(methods_dir=METHODS_DIR, verbose=False)
    return validator.registry


def _parse_toml(path: Path) -> dict:
    with open(path, "rb") as f:
        return toml.load(f)


def _pipeline_method_ids(parsed: dict) -> List[str]:
    ids = []
    for step in parsed.get("steps", []) or []:
        ref = step.get("method", "") or ""
        stem = Path(ref).stem if ref else ""
        if stem and stem not in ids:
            ids.append(stem)
    return ids


def _pipeline_view(path: Path, registry: dict) -> dict:
    try:
        parsed = _parse_toml(path)
    except Exception as e:
        return {"name": path.stem, "file": path.name, "parse_error": str(e)}

    required = _pipeline_method_ids(parsed)
    missing = []
    for mid in required:
        entry = registry.get(mid, {})
        meta = entry.get("__metadata__", {})
        if not _is_installed(mid, meta):
            missing.append(mid)

    steps = []
    for i, step in enumerate(parsed.get("steps", []) or []):
        step_name = step.get("name") or f"Step_{i}"
        kwargs = step.get("kwargs", {}) or {}
        overridable = {k: v for k, v in kwargs.items() if k not in ("output_key", "primary_output")}
        method_id = Path(step.get("method", "")).stem if step.get("method") else None
        step_installed = False
        if method_id:
            step_meta = registry.get(method_id, {}).get("__metadata__", {})
            step_installed = _is_installed(method_id, step_meta)
        steps.append({
            "name": step_name,
            "method": step.get("method"),
            "method_id": method_id,
            "installed": step_installed,
            "inputs": step.get("inputs", {}) or {},
            "kwargs": kwargs,
            "overridable": overridable,
        })

    global_opts = parsed.get("global_options", {}) or {}
    return {
        "name": path.stem,
        "file": path.name,
        "title": parsed.get("title", path.stem),
        "description": parsed.get("description", ""),
        "signature_valid": verifier.verify(path),
        "required_methods": required,
        "missing_methods": missing,
        "runnable": len(missing) == 0,
        "global_options": global_opts,
        "steps": steps,
    }


def _build_overrides(parsed: dict) -> Dict[str, Any]:
    """Flat map 'StepName.param' -> default value, as in the old Home page."""
    overrides = {}
    for i, step in enumerate(parsed.get("steps", []) or []):
        step_name = step.get("name") or f"Step_{i}"
        for k, v in (step.get("kwargs", {}) or {}).items():
            if k in ("output_key", "primary_output"):
                continue
            overrides[f"{step_name}.{k}"] = v
    return overrides


def get_output_status(rel_or_abs: str) -> dict:
    out = {"exists": False, "empty": True, "status_json": None, "detected_steps": [], "entries_count": 0}
    p = Path(rel_or_abs)
    if not p.is_absolute():
        p = PROJECT_ROOT / p
    if not p.exists():
        return out
    out["exists"] = True
    try:
        entries = [e for e in p.iterdir() if e.name != ".gitkeep"]
    except OSError:
        return out
    out["entries_count"] = len(entries)
    out["empty"] = len(entries) == 0
    status_file = p / "pipeline_status.json"
    if status_file.is_file():
        try:
            parsed = json.loads(status_file.read_text(encoding="utf-8"))
            out["status_json"] = parsed
            out["detected_steps"] = list(parsed.keys())
            out["empty"] = False
            return out
        except Exception:
            pass
    out["detected_steps"] = [e.name for e in entries if e.is_dir()]
    return out


def open_folder(path: Path):
    """Open a folder in the system file explorer (WSL-aware)."""
    target = os.path.abspath(str(path))
    system = platform.system()
    if system == "Linux" and "microsoft" in platform.release().lower():
        try:
            win_path = subprocess.check_output(["wslpath", "-w", target]).decode().strip()
            subprocess.Popen(["explorer.exe", win_path])
            return
        except Exception:
            pass
    if system == "Windows":
        os.startfile(target)
    elif system == "Darwin":
        subprocess.Popen(["open", target])
    else:
        try:
            subprocess.Popen(["xdg-open", target])
        except Exception:
            pass


def _safe_subdir(base: Path, sub: str) -> Path:
    """Resolve sub under base, refusing path traversal."""
    if sub in ("", ".", "/"):
        return base
    candidate = (base / sub).resolve()
    if not str(candidate).startswith(str(base.resolve())):
        raise HTTPException(status_code=400, detail="Invalid folder path.")
    return candidate


# --------------------------------------------------------------------------
# Schemas
# --------------------------------------------------------------------------

class StartPipelineRequest(BaseModel):
    pipeline: str
    input: Optional[str] = None
    output: Optional[str] = None
    overrides: Dict[str, Any] = {}
    filter_enabled: bool = False
    filter_threshold: float = 0.1
    run_mode: str = "resume"   # "resume" | "restart"
    force: bool = False


class ForceRequest(BaseModel):
    force: bool = False


class OpenFolderRequest(BaseModel):
    path: str


class PipelineEditRequest(BaseModel):
    step_kwargs: Dict[str, Dict[str, Any]] = {}
    filter_enabled: Optional[bool] = None
    filter_threshold: Optional[float] = None


# --------------------------------------------------------------------------
# Methods API
# --------------------------------------------------------------------------

@app.get("/api/methods")
def list_methods():
    try:
        registry = _get_registry()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to load registry: {e}")

    methods = []
    categories = {}
    for method_id, entry in sorted(registry.items()):
        meta = entry.get("__metadata__", {})
        toml_path: Path = entry["__path__"]
        category = toml_path.parent.name
        installed = _is_installed(method_id, meta)
        has_help = bool(entry.get("has_help", True))
        sig_valid = verifier.verify(toml_path) if toml_path.exists() else False
        item = {
            "id": method_id,
            "title": meta.get("title", method_id),
            "description": meta.get("description", "No description"),
            "url": meta.get("url", ""),
            "type": meta.get("type", ""),
            "category": category,
            "installed": installed,
            "has_help": has_help,
            "signature_valid": sig_valid,
        }
        methods.append(item)
        categories.setdefault(category, []).append(item)

    installed_count = sum(1 for m in methods if m["installed"])
    return {
        "summary": {
            "total": len(methods),
            "installed": installed_count,
            "disk_usage": _readable(_du_bytes(ENVS_DIR)) if ENVS_DIR.exists() else "0 B",
        },
        "categories": dict(sorted(categories.items())),
        "methods": methods,
    }


def _find_method_entry(method_id: str):
    registry = _get_registry()
    entry = registry.get(method_id)
    if not entry:
        raise HTTPException(status_code=404, detail=f"Method '{method_id}' not found.")
    return registry, entry


@app.post("/api/methods/{method_id}/install")
def install_method(method_id: str, body: ForceRequest):
    registry, entry = _find_method_entry(method_id)
    toml_path: Path = entry["__path__"]
    meta = entry.get("__metadata__", {})
    if _is_installed(method_id, meta):
        raise HTTPException(status_code=409, detail=f"Method '{method_id}' is already installed.")

    sig_ok = verifier.verify(toml_path)
    if not sig_ok and not body.force:
        return JSONResponse(status_code=409, content={
            "needs_force": True,
            "detail": f"Signature verification FAILED for {toml_path.name}. Installation is not recommended.",
            "file": toml_path.name,
            "url": meta.get("url", ""),
        })

    cmd = [python_executable(), str(PROJECT_ROOT / "main.py"), "methods", "install", method_id, "-v"]
    if not sig_ok:
        cmd.append("--force")
    job = job_manager.start("method", f"install:{method_id}", cmd, str(PROJECT_ROOT))
    return {"job_id": job.id, "status": job.status}


@app.post("/api/methods/{method_id}/validate")
def validate_method(method_id: str, body: ForceRequest):
    registry, entry = _find_method_entry(method_id)
    toml_path: Path = entry["__path__"]
    sig_ok = verifier.verify(toml_path)
    if not sig_ok and not body.force:
        return JSONResponse(status_code=409, content={
            "needs_force": True,
            "detail": f"Signature verification FAILED for {toml_path.name}. Validation is not recommended.",
            "file": toml_path.name,
            "url": entry.get("__metadata__", {}).get("url", ""),
        })
    cmd = [python_executable(), str(PROJECT_ROOT / "main.py"), "methods", "validate", method_id, "-v"]
    if not sig_ok:
        cmd.append("--force")
    job = job_manager.start("method", f"validate:{method_id}", cmd, str(PROJECT_ROOT))
    return {"job_id": job.id, "status": job.status}


@app.post("/api/methods/{method_id}/uninstall")
def uninstall_method(method_id: str, body: ForceRequest):
    _find_method_entry(method_id)
    cmd = [python_executable(), str(PROJECT_ROOT / "main.py"), "methods", "uninstall", method_id, "--yes", "-v"]
    job = job_manager.start("method", f"uninstall:{method_id}", cmd, str(PROJECT_ROOT))
    return {"job_id": job.id, "status": job.status}


@app.post("/api/methods/{method_id}/help")
def method_help(method_id: str):
    _find_method_entry(method_id)
    cmd = [python_executable(), str(PROJECT_ROOT / "main.py"), "methods", "help", method_id]
    job = job_manager.start("help", f"help:{method_id}", cmd, str(PROJECT_ROOT))
    return {"job_id": job.id, "status": job.status}


# --------------------------------------------------------------------------
# Pipelines API
# --------------------------------------------------------------------------

@app.get("/api/pipelines")
def list_pipelines():
    registry = _get_registry()
    result = []
    if not PIPELINES_DIR.exists():
        return {"pipelines": []}
    for p in sorted(PIPELINES_DIR.glob("*.toml")):
        result.append(_pipeline_view(p, registry))
    return {"pipelines": result}


@app.get("/api/pipelines/{name}")
def get_pipeline(name: str):
    path = PIPELINES_DIR / f"{name}.toml"
    if not path.is_file() or ".." in name or "/" in name:
        raise HTTPException(status_code=404, detail="Pipeline not found.")
    registry = _get_registry()
    view = _pipeline_view(path, registry)
    view["overrides"] = _build_overrides(_parse_toml(path)) if "parse_error" not in view else {}
    return view


@app.put("/api/pipelines/{name}")
def edit_pipeline(name: str, body: PipelineEditRequest):
    path = PIPELINES_DIR / f"{name}.toml"
    if not path.is_file() or ".." in name or "/" in name:
        raise HTTPException(status_code=404, detail="Pipeline not found.")

    try:
        parsed = _parse_toml(path)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Cannot parse pipeline TOML: {e}")

    steps = parsed.get("steps", []) or []
    for i, step in enumerate(steps):
        step_name = step.get("name") or f"Step_{i}"
        if step_name in body.step_kwargs:
            step["kwargs"] = dict(body.step_kwargs[step_name])

    if body.filter_threshold is not None:
        if body.filter_enabled:
            parsed.setdefault("global_options", {})["filter_opacity_threshold"] = float(body.filter_threshold)
        else:
            go = parsed.get("global_options")
            if go is not None:
                go.pop("filter_opacity_threshold", None)
                if not go:
                    parsed.pop("global_options", None)

    try:
        with open(path, "wb") as f:
            tomli_w.dump(parsed, f)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error saving pipeline: {e}")

    return {"saved": True, "warning": "The TOML signature has been invalidated by this edit."}


# --------------------------------------------------------------------------
# Inputs API
# --------------------------------------------------------------------------

@app.get("/api/inputs")
def list_inputs():
    INPUTS_DIR.mkdir(parents=True, exist_ok=True)
    groups = {}
    for p in sorted(INPUTS_DIR.rglob("*")):
        if not p.is_file() or p.name == ".gitkeep":
            continue
        rel = p.relative_to(INPUTS_DIR)
        folder = rel.parent.as_posix()
        try:
            size = p.stat().st_size
        except OSError:
            size = 0
        ext = p.suffix.lower()
        groups.setdefault(folder, []).append({
            "name": p.name,
            "size": size,
            "is_image": ext in IMAGE_EXTS,
            "is_video": ext in VIDEO_EXTS,
        })

    result = []
    for folder, files in sorted(groups.items()):
        total = sum(f["size"] for f in files)
        has_images = any(f["is_image"] for f in files)
        has_videos = any(f["is_video"] for f in files)
        if has_images and not has_videos:
            typ = "Images"
        elif has_videos and not has_images:
            typ = "Video"
        elif has_images and has_videos:
            typ = "Mixed (images & video)"
        else:
            typ = "Other"
        result.append({
            "folder": folder,
            "type": typ,
            "total_size": total,
            "total_size_readable": _readable(total),
            "files": files,
        })
    return {"groups": result}


@app.post("/api/inputs/upload")
async def upload_input(folder: str = Query(...), file: UploadFile = File(...)):
    dest_dir = _safe_subdir(INPUTS_DIR, folder)
    dest_dir.mkdir(parents=True, exist_ok=True)
    filename = Path(file.filename or "upload.bin").name
    if not filename or filename.startswith("."):
        raise HTTPException(status_code=400, detail="Invalid file name.")
    dest = dest_dir / filename
    try:
        with open(dest, "wb") as out:
            while chunk := await file.read(1024 * 1024):
                out.write(chunk)
    except Exception as e:
        if dest.exists():
            dest.unlink(missing_ok=True)
        raise HTTPException(status_code=500, detail=f"Upload failed: {e}")
    finally:
        await file.close()
    return {"saved": str(dest.relative_to(INPUTS_DIR)), "size": dest.stat().st_size}


@app.delete("/api/inputs")
def delete_input(folder: str = Query(...)):
    target = _safe_subdir(INPUTS_DIR, folder)
    if target == INPUTS_DIR:
        # Root: delete children only
        for child in target.iterdir():
            if child.is_dir():
                shutil.rmtree(child)
            else:
                child.unlink()
        return {"deleted": "inputs/*"}
    if not target.exists():
        raise HTTPException(status_code=404, detail="Folder not found.")
    if target.is_dir():
        shutil.rmtree(target)
    else:
        target.unlink()
    return {"deleted": folder}


@app.post("/api/inputs/open")
def open_inputs(body: OpenFolderRequest):
    target = _safe_subdir(INPUTS_DIR, body.path)
    if not target.exists():
        raise HTTPException(status_code=404, detail="Folder not found.")
    open_folder(target)
    return {"opened": str(target)}


# --------------------------------------------------------------------------
# Outputs API
# --------------------------------------------------------------------------

def _find_sfm_path(run_dir: Path) -> Optional[str]:
    base = run_dir / "StructureFromMotion"
    for c in [base / "colmap" / "sparse" / "0", base / "sparse" / "0", base / "colmap" / "sparse"]:
        if c.exists():
            return str(c)
    return None


def _find_gs_ply(run_dir: Path) -> Optional[str]:
    final = run_dir / "final_result" / "final_gaussian.ply"
    if final.exists():
        return str(final)
    plys = [p for p in run_dir.rglob("*.ply") if "sparse" not in str(p)]
    if not plys:
        return None
    plys.sort(key=lambda x: x.stat().st_mtime, reverse=True)
    return str(plys[0])


@app.get("/api/outputs")
def list_outputs():
    if not OUTPUTS_DIR.exists():
        return {"runs": []}
    runs = []
    for d in sorted([p for p in OUTPUTS_DIR.iterdir() if p.is_dir()], key=lambda p: p.name.lower()):
        item = {
            "name": d.name,
            "path": str(d.relative_to(PROJECT_ROOT)),
            "sfm_path": _find_sfm_path(d),
            "sfm_points": _find_sfm_points_file(d) is not None,
            "ply_path": _find_gs_ply(d),
            "summary": None,
        }
        status_file = d / "pipeline_status.json"
        if status_file.is_file():
            try:
                item["summary"] = json.loads(status_file.read_text(encoding="utf-8"))
            except Exception:
                pass
        runs.append(item)
    return {"runs": runs}


@app.get("/api/outputs/status")
def output_status(path: str):
    if ".." in path:
        raise HTTPException(status_code=400, detail="Invalid path.")
    return get_output_status(path)


@app.delete("/api/outputs/{name}")
def delete_output(name: str):
    target = OUTPUTS_DIR / name
    if ".." in name or "/" in name or not target.is_dir() or target.resolve() == OUTPUTS_DIR.resolve():
        raise HTTPException(status_code=404, detail="Run not found.")
    shutil.rmtree(target)
    return {"deleted": name}


@app.post("/api/outputs/open")
def open_output(body: OpenFolderRequest):
    p = Path(body.path)
    if not p.is_absolute():
        p = PROJECT_ROOT / p
    p = p.resolve()
    if not str(p).startswith(str(PROJECT_ROOT.resolve())):
        raise HTTPException(status_code=400, detail="Path outside project root.")
    if not p.exists():
        raise HTTPException(status_code=404, detail="Path not found.")
    open_folder(p)
    return {"opened": str(p)}


def _get_run_dir(run: str) -> Path:
    if ".." in run or "/" in run or "\\" in run or not run:
        raise HTTPException(status_code=400, detail="Invalid run name.")
    run_dir = OUTPUTS_DIR / run
    if not run_dir.is_dir():
        raise HTTPException(status_code=404, detail="Run not found.")
    return run_dir


def _is_filtered_ply(name: str) -> bool:
    ln = name.lower()
    return "filter" in ln


# PLYs larger than this are converted to the compact .splat format (~10x smaller,
# no SH) for the browser viewer. The converted file is cached in the run dir.
COMPACT_THRESHOLD_BYTES = 150 * 1024 * 1024


def _splat_cache_path(run_dir: Path, source: Path) -> Path:
    return run_dir / ".viewer_cache" / f"{source.stem}_{source.stat().st_size}.splat"


def _serve_splat(run_dir: Path, target: Path, compact: str) -> "FileResponse":
    """Serve a splat PLY, converting to .splat when requested or when the file
    exceeds the compact threshold. Response carries X-Splat-Format so the
    client picks the right loader."""
    if not target.is_file():
        raise HTTPException(status_code=404, detail="PLY file not found.")

    use_compact = compact == "1" or (compact != "0" and target.stat().st_size > COMPACT_THRESHOLD_BYTES)
    if not use_compact:
        resp = FileResponse(target, media_type="application/octet-stream", filename=target.name)
        resp.headers["X-Splat-Format"] = "ply"
        return resp

    cache = _splat_cache_path(run_dir, target)
    if not (cache.exists() and cache.stat().st_mtime >= target.stat().st_mtime):
        from core.splat_convert import convert_ply_to_splat
        try:
            convert_ply_to_splat(target, cache, logger=None)
        except Exception as e:
            # Fall back to serving the raw PLY rather than failing the viewer
            resp = FileResponse(target, media_type="application/octet-stream", filename=target.name)
            resp.headers["X-Splat-Format"] = "ply"
            resp.headers["X-Splat-Warning"] = f"conversion failed: {e}"
            return resp

    resp = FileResponse(cache, media_type="application/octet-stream", filename=cache.name)
    resp.headers["X-Splat-Format"] = "splat"
    return resp


def _serve_ply(target: Path):
    if not target.is_file():
        raise HTTPException(status_code=404, detail="PLY file not found.")
    return FileResponse(target, media_type="application/octet-stream", filename=target.name)


@app.get("/api/outputs/{run}/splat")
def get_splat_ply(run: str, path: Optional[str] = None, compact: str = "auto"):
    """Serve the gaussian splat PLY for a run: the best one by default, or a
    specific variant via ?path= (relative to the run dir, traversal-guarded).
    Files above the compact threshold (or ?compact=1) are converted to the
    .splat format for the browser; ?compact=0 always serves the raw PLY."""
    run_dir = _get_run_dir(run)
    if path:
        target = (run_dir / path).resolve()
        if not str(target).startswith(str(run_dir.resolve())):
            raise HTTPException(status_code=400, detail="Invalid path.")
    else:
        found = _find_gs_ply(run_dir)
        if not found:
            raise HTTPException(status_code=404, detail="No splat PLY found for this run.")
        target = Path(found)
    return _serve_splat(run_dir, target, compact)


def _find_sfm_points_file(run_dir: Path) -> Path | None:
    """Find a sparse point cloud for a run: points3D.ply directly, else
    points3D.bin (converted to PLY on demand by the serving endpoint)."""
    sfm_dir = _find_sfm_path(run_dir)
    candidates = []
    if sfm_dir:
        candidates.append(Path(sfm_dir) / "points3D.ply")
    candidates += list(run_dir.rglob("points3D.ply"))
    for c in candidates:
        if c.is_file():
            return c
    if sfm_dir and (Path(sfm_dir) / "points3D.bin").is_file():
        return Path(sfm_dir) / "points3D.bin"
    for c in run_dir.rglob("points3D.bin"):
        return c
    return None


@app.get("/api/outputs/{run}/sfm")
def get_sfm_ply(run: str):
    """Serve the sparse COLMAP point cloud for a run. Handles both points3D.ply
    (served as-is) and points3D.bin (converted to PLY on demand and cached)."""
    run_dir = _get_run_dir(run)
    found = _find_sfm_points_file(run_dir)
    if not found:
        raise HTTPException(status_code=404, detail="No sparse point cloud (points3D.ply/.bin) found for this run.")
    if found.suffix == ".ply":
        return _serve_ply(found)

    # Binary COLMAP format: convert once, cache next to it
    cache = run_dir / ".viewer_cache" / f"{found.stem}_{found.stat().st_size}.ply"
    if not (cache.exists() and cache.stat().st_mtime >= found.stat().st_mtime):
        from core.colmap_points import convert_points3d_bin_to_ply
        try:
            convert_points3d_bin_to_ply(found, cache)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to convert points3D.bin: {e}")
    return _serve_ply(cache)


@app.get("/api/outputs/{run}/variants")
def get_splat_variants(run: str):
    """List the available splat PLY variants (final / original / filtered) for a run,
    so the viewer can offer a toggle between them. Each variant carries the
    format the client should load (ply or splat)."""
    run_dir = _get_run_dir(run)
    by_id = {}

    final = run_dir / "final_result" / "final_gaussian.ply"
    if final.is_file():
        by_id["final"] = {
            "id": "final",
            "label": "Final (post-processed)",
            "path": str(final.relative_to(run_dir)),
            "size": final.stat().st_size,
        }

    plys = [p for p in run_dir.rglob("*.ply") if "sparse" not in str(p)]
    originals = sorted(
        (p for p in plys if not _is_filtered_ply(p.name)),
        key=lambda x: x.stat().st_mtime, reverse=True,
    )
    filtered = sorted(
        (p for p in plys if _is_filtered_ply(p.name)),
        key=lambda x: x.stat().st_mtime, reverse=True,
    )
    if originals:
        p = originals[0]
        by_id.setdefault("original", {
            "id": "original",
            "label": "Original",
            "path": str(p.relative_to(run_dir)),
            "size": p.stat().st_size,
        })
    if filtered:
        p = filtered[0]
        by_id.setdefault("filtered", {
            "id": "filtered",
            "label": "Filtered (opacity)",
            "path": str(p.relative_to(run_dir)),
            "size": p.stat().st_size,
        })

    # Drop duplicates by resolved path, keep deterministic order
    order = ["final", "filtered", "original"]
    seen = set()
    variants = []
    for key in order:
        v = by_id.get(key)
        if not v:
            continue
        rp = (run_dir / v["path"]).resolve()
        if rp in seen:
            continue
        seen.add(rp)
        v["format"] = "splat" if v["size"] > COMPACT_THRESHOLD_BYTES else "ply"
        variants.append(v)

    return {"variants": variants}


# --------------------------------------------------------------------------
# Jobs API (pipeline runs + generic job control)
# --------------------------------------------------------------------------

@app.get("/api/jobs")
def list_jobs(kind: Optional[str] = None):
    return {"jobs": job_manager.list(kind)}


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str):
    job = job_manager.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found.")
    return job.snapshot()


@app.get("/api/jobs/{job_id}/logs")
def get_job_logs(job_id: str, since: int = 0):
    job = job_manager.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found.")
    lines, cursor = job.read_since(since)
    return {"lines": lines, "cursor": cursor, "status": job.status, "returncode": job.returncode}


@app.post("/api/pipelines/run")
def run_pipeline(body: StartPipelineRequest):
    pipeline_path = PIPELINES_DIR / f"{body.pipeline}.toml"
    if not pipeline_path.is_file() or ".." in body.pipeline or "/" in body.pipeline:
        raise HTTPException(status_code=404, detail="Pipeline not found.")

    try:
        parsed = _parse_toml(pipeline_path)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Cannot parse pipeline TOML: {e}")

    sig_ok = verifier.verify(pipeline_path)
    if not sig_ok and not body.force:
        return JSONResponse(status_code=409, content={
            "needs_force": True,
            "detail": f"Signature verification FAILED for {pipeline_path.name}.",
            "file": pipeline_path.name,
        })

    pipeline_file_to_run = pipeline_path
    tmp_files = []
    if body.filter_enabled:
        TMP_DIR.mkdir(parents=True, exist_ok=True)
        tmp_path = TMP_DIR / f"{body.pipeline}_{int(time.time())}_tmp.toml"
        parsed.setdefault("global_options", {})["filter_opacity_threshold"] = float(body.filter_threshold)
        with open(tmp_path, "wb") as f:
            tomli_w.dump(parsed, f)
        pipeline_file_to_run = tmp_path
        tmp_files.append(tmp_path)

    cmd = [python_executable(), str(PROJECT_ROOT / "main.py"), "run", str(pipeline_file_to_run)]
    if body.input:
        input_path = Path(body.input)
        if not input_path.is_absolute():
            input_path = INPUTS_DIR / body.input
        if not input_path.exists():
            raise HTTPException(status_code=400, detail=f"Input not found: {input_path}")
        cmd += ["--input", str(input_path)]
    if body.output:
        cmd += ["--output", str(body.output)]
    for key, val in (body.overrides or {}).items():
        if "=" in key:
            raise HTTPException(status_code=400, detail=f"Invalid override key: {key}")
        if isinstance(val, bool):
            valstr = "true" if val else "false"
        else:
            valstr = str(val)
        cmd += ["--set", f"{key}={valstr}"]
    cmd += ["--gui", "--verbose"]
    if body.run_mode == "restart":
        cmd += ["--restart"]

    job = job_manager.start("pipeline", body.pipeline, cmd, str(PROJECT_ROOT), tmp_files=tmp_files)
    return {"job_id": job.id, "status": job.status, "command": cmd}


@app.post("/api/jobs/{job_id}/stop")
def stop_job(job_id: str):
    if not job_manager.stop(job_id):
        raise HTTPException(status_code=409, detail="Job is not running.")
    return {"stopped": job_id}


@app.websocket("/ws/jobs/{job_id}")
async def ws_job_logs(websocket: WebSocket, job_id: str):
    await websocket.accept()
    job = job_manager.get(job_id)
    if job is None:
        await websocket.send_json({"type": "error", "detail": "Job not found."})
        await websocket.close()
        return

    cursor = 0
    try:
        await websocket.send_json({"type": "status", "job": job.snapshot()})
        while True:
            lines, cursor = job.read_since(cursor)
            if lines:
                await websocket.send_json({"type": "log", "lines": lines, "cursor": cursor})
            if job.status != "running" and not lines:
                await websocket.send_json({"type": "status", "job": job.snapshot()})
                break
            await asyncio.sleep(0.3)
    except WebSocketDisconnect:
        pass
    except Exception as e:
        try:
            await websocket.send_json({"type": "error", "detail": str(e)})
        except Exception:
            pass
    finally:
        try:
            await websocket.close()
        except Exception:
            pass


# --------------------------------------------------------------------------
# Static frontend
# --------------------------------------------------------------------------

@app.get("/logo.png")
def logo():
    logo_path = Path(__file__).resolve().parent / "images" / "logo.png"
    if logo_path.exists():
        return FileResponse(logo_path)
    raise HTTPException(status_code=404)


app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")

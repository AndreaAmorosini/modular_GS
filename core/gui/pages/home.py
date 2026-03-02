import streamlit as st
import sys
import subprocess
import time
import os
from pathlib import Path
import signal
import tomli_w
import json

try:
    import tomllib as toml
except Exception:
    import tomli as toml

st.set_page_config(
    page_title = "Modular Gaussian Splatting - Home",
    layout = "wide",
    page_icon = "🏠"
)

current_file = Path(__file__).resolve()
project_root = current_file.parent
while not (project_root / "pipelines").exists():
    if project_root == project_root.parent:
        project_root = current_file.parents[3]
        break
    project_root = project_root.parent

if str(project_root) not in sys.path:
    sys.path.append(str(project_root))
    
from core.utils import SignatureVerifier

st.title("Welcome to Modular Gaussian Splatting!")
st.markdown("""
This is the home page of the Modular Gaussian Splatting web interface. Use the sidebar to navigate between pages and manage your methods and pipelines.
""")

pipelines_dir = project_root / "pipelines"
inputs_dir = project_root / "inputs"
outputs_dir = project_root / "output"

verifier = SignatureVerifier()

def required_methods_from_pipeline(parsed: dict):
    req = set()
    steps = parsed.get("steps", []) or []
    for step in steps:
        method_ref = step.get("method", "") or ""
        # estrai nome metodo dal path (es. "sfm/colmap.toml" -> "colmap")
        method_name = Path(method_ref).stem if method_ref else ""
        if method_name:
            req.add(method_name)
    return req

@st.cache_data(ttl=300)
def installed_methods(envs: Path):
    res = set()
    if not envs.exists():
        return res
    for d in envs.iterdir():
        if d.is_dir() and (d / ".install_complete").exists():
            res.add(d.name)
    return res

st.cache_data(ttl=300)
def load_pipeline_files(d: Path):
    """Return pipeline files that have all required methods installed."""
    all_files = sorted([p for p in d.iterdir() if p.is_file() and p.suffix == ".toml"])
    if not all_files:
        return []
    envs_dir = project_root / ".envs"
    installed = installed_methods(envs_dir)
    valid = []
    for p in all_files:
        try:
            parsed = parse_toml_file(p)
            if "_parse_error" in parsed:
                continue
            req = required_methods_from_pipeline(parsed)
            missing = [m for m in req if m not in installed]
            if not missing:
                valid.append(p)
        except Exception:
            continue
    return valid

st.cache_data(ttl=1300)
def parse_toml_file(p: Path):
    try:
        text = p.read_text(encoding="utf-8")
        return toml.loads(text)
    except Exception as e:
        st.error(f"Error parsing TOML file {p}: {e}")
        return {"_parse_error": str(e)}
    
def build_overrides_from_steps(parsed: dict, prefix: str):
    overrides = {}
    steps = parsed.get("steps", [])
    for i, step in enumerate(steps):
        step_name = step.get("name") or step.get("id") or f"Step_{i}"
        kwargs = step.get("kwargs", {}) or {}
        for k, v in kwargs.items():
            if k in ("output_key", "primary_output"):
                continue
            overrides[f"{step_name}.{k}"] = v
    return overrides

def get_output_status(path: Path, project_root: Path):
    """Check if output path exists and return status message."""
    
    out = {"exists": False, "empty":True, "status_json": None, "detected_steps": [], "entries_count": 0}
    if not path:
        return out
    
    p = Path(path)
    if not p.is_absolute():
        p = project_root / p
        
    out["exists"] = p.exists()
    if not p.exists():
        return out
    
    entries = [e for e in p.iterdir() if e.name != ".gitkeep"]
    out["entries_count"] = len(entries)
    out["empty"] = len(entries) == 0
    
    status_file = p / "pipeline_status.json"
    if status_file.exists() and status_file.is_file():
        try:
            text = status_file.read_text(encoding="utf-8")
            parsed = json.loads(text)
            out["status_json"] = parsed
            out["detected_steps"] = list(parsed.keys())
            out["empty"] = False
            return out
        except Exception:
            pass
        
    # Fallback: try to detect steps from file names
    out["detected_steps"] = [e.name for e in entries if e.is_dir()]
    return out

def _fmt(x):
    return "--select an option--" if x is None else x

pipeline_files = load_pipeline_files(pipelines_dir)
# pipeline_options = ["-- select --"] + [p.stem for p in pipeline_files]
pipeline_options = [None] + [p.stem for p in pipeline_files]


st.markdown("## Run a Pipeline")
col_left, col_right = st.columns([3, 1])
with col_left:
    selected_name = st.selectbox("Select a pipeline to run:", pipeline_options, format_func = _fmt, index = 0)
with col_right:
    if st.button("Refresh Pipeline"):
        st.rerun()
        
if selected_name and selected_name != "-- select --":
    selected_name_1 = selected_name + ".toml"
    selected_path = pipelines_dir / selected_name_1
    parsed = parse_toml_file(selected_path)
    if "_parse_error" in parsed:
        st.error(f"Cannot run pipeline due to TOML parsing error: {parsed['_parse_error']}")
    else:
        meta = parsed.get("pipeline", {}) or {}
        st.subheader(meta.get("name", selected_path.stem))
        if meta.get("description"):
            st.markdown(meta["description"])
            
        global_opts = parsed.get("global_options", {}) or {}
        has_threshold = "filter_opacity_threshold" in global_opts
        default_threshold = float(global_opts.get("filter_opacity_threshold", 0.1))
        state_key_global = f"global_opts_{selected_name}"
        
        if state_key_global not in st.session_state:
            st.session_state[state_key_global] = {"use_filter": bool(has_threshold), "threshold": default_threshold}
            
        with st.expander("Global Options", expanded=has_threshold):
            use_filter = st.checkbox("Use opacity filter", value=st.session_state[state_key_global]["use_filter"], key=f"use_filter_{selected_name}")
            st.session_state[state_key_global]["use_filter"] = use_filter
            
            if use_filter:
                thr = st.number_input(
                    "Opacity Threshold",
                    min_value = 0.0,
                    max_value = 1.0,
                    value = float(st.session_state[state_key_global]["threshold"]),
                    step = 0.01,
                    format="%.2f",
                    key=f"{state_key_global}_threshold_{selected_name}"
                )
                st.session_state[state_key_global]["threshold"] = float(thr)
            else:
                thr = st.session_state[state_key_global]["threshold"]  # Keep previous value even if not used
            
        default_overrides = build_overrides_from_steps(parsed, selected_name)
        edits = {}
        if default_overrides:
            st.markdown("### Override Parameters")
            for k, v in default_overrides.items():
                step, param = k.split(".", 1)
                input_key = f"run_{selected_name}_{step}_{param}"
                if isinstance(v, bool):
                    newv = st.checkbox(f"{step} - {param}", value=bool(v), key=input_key)
                elif isinstance(v, int):
                    newv = st.number_input(f"{step} - {param}", value=int(v), key=input_key)
                else:
                    newv = st.text_input(f"{step} - {param}", value=str(v), key=input_key)
                    if isinstance(newv, str) and newv.lower() in ("true", "false"):
                        newv = True if newv.lower() == "true" else False
                edits[f"{step}.{param}"] = newv
        else:
            st.info("No parameters found in the pipeline steps to override.")
            
        st.markdown("### Input")
        # input_candidates = ["-- none --"]
        input_candidates = [None]
        for d in sorted([p for p in inputs_dir.iterdir() if p.is_dir()]):
            input_candidates.append(d.name)
        for f in sorted([p for p in inputs_dir.iterdir() if p.is_file() and p.name != ".gitkeep"]):
            input_candidates.append(str(f.name))
        selected_input = st.selectbox("Select input data:", input_candidates, key=f"input_{selected_name}", format_func=_fmt, index=0)
        
        output_key = f"output_{selected_name}"
        prev_input_key = f"prev_input_{selected_name}"
        
        if selected_input and selected_input != "-- none --":
            input_base = Path(selected_input).stem
        else:
            input_base = "input"
            
        input_base = "".join(ch if (ch.isalnum() or ch in "-_") else "_" for ch in input_base)
        default_out = f"output/{input_base}_{selected_name}"
        
        if st.session_state.get(prev_input_key) != selected_input:
            st.session_state[output_key] = default_out
            st.session_state[prev_input_key] = selected_input
        
        output_name = st.text_input("Output name (relative to project root):", value=st.session_state.get(output_key, default_out), key=f"output_{selected_name}")
        
        resolved_output = Path(output_name) if Path(output_name).is_absolute() else (project_root / output_name)
        out_status = get_output_status(resolved_output, project_root)
        has_prev_run = out_status["exists"] and not out_status["empty"]
        
        if has_prev_run:
            mode_labels = {
                "restart": "Restart (overwrite existing output)",
                "resume": "Resume (keep existing output and skip completed steps)",
            }
            st.radio(
                "Output path already exists. Choose how to proceed:",
                options = list(mode_labels.keys()),
                format_func = lambda x: mode_labels[x],
                index = 0,
                key = f"run_action_{selected_name}"
            )
        else:
            st.session_state.pop(f"run_action_{selected_name}", None)
        
        if not out_status["exists"]:
            st.info(f"Output path `{output_name}` does not exist. It will be created by the pipeline.")
        else:
            if out_status["empty"]:
                st.warning(f"Output path `{output_name}` already exists but is empty. Make sure this is intentional to avoid overwriting important data.")
            else:
                if out_status["status_json"]:
                    st.warning(f"Output path `{output_name}` already exists and contains a `pipeline_status.json` indicating detected steps: {', '.join(out_status['detected_steps'])}.")
                    with st.expander("Pipeline Status Details", expanded=False):
                        st.json(out_status["status_json"])
                elif out_status["detected_steps"]:
                    st.warning(f"Output path `{output_name}` already exists and contains {out_status['entries_count']} entries, with detected steps: {', '.join(out_status['detected_steps'])}.")
                else:
                    st.warning(f"Output path `{output_name}` already exists and contains {out_status['entries_count']} entries. Make sure this is intentional to avoid overwriting important data.")
        
        c1, c2 = st.columns(2)
        start_clicked = c1.button("Start Pipeline", key=f"start_{selected_name}", disabled=st.session_state.get("pipeline_running", False))
        stop_clicked = c2.button("Stop Pipeline", key=f"stop_{selected_name}", disabled=not st.session_state.get("pipeline_running", False))
        status_area = st.empty()
        
        if "pipeline_proc" not in st.session_state:
            st.session_state.pipeline_proc = None
            st.session_state.pipeline_cmd = None
            st.session_state.pipeline_running = False
            st.session_state.pipeline_status = None
            
        if stop_clicked and st.session_state.pipeline_proc:
            proc = st.session_state.pipeline_proc
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
                time.sleep(0.5)
                if proc.poll() is None:
                    os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                status_area.info("Pipeline stopped by user.")
            except Exception as e:
                status_area.error(f"Error stopping process: {e}")
            finally:
                st.session_state.pipeline_proc = None
                st.session_state.pipeline_cmd = None
                st.session_state.pipeline_running = False
                st.session_state.pipeline_status = {"type": "info", "msg" : "Pipeline stopped."}
                # Clean tmp file if created
                tmp = st.session_state.get("pipeline_tmp", None)
                if tmp:
                    try:
                        Path(tmp).unlink()
                    except Exception:
                        pass
                st.rerun()
                
        if st.session_state.get("pipeline_status"):
            status = st.session_state.pipeline_status
            if status["type"] == "success":
                status_area.success(status["msg"])
            elif status["type"] == "error":
                status_area.error(status["msg"])
            else:
                status_area.info(status["msg"])
                
        attempt_key = f"attempted_run_{selected_name}"
        force_key = f"force_run_{selected_name}"

        # Start logic
        if start_clicked:
            st.session_state[attempt_key] = True
            
        if (st.session_state.get(attempt_key) or st.session_state.get(force_key, False)) and not st.session_state.get("pipeline_running", False):
            # signature check only when starting
            proceed_run = True
            ok = True
            try:
                ok = verifier.verify(selected_path)
            except Exception:
                ok = False
                

            if not ok and not st.session_state.get(force_key, False):
                st.warning(f"Signature verification FAILED for `{selected_path.name}`. Press 'Proceed anyway' to continue.")
                c_p1, c_p2 = st.columns([1, 5])
                with c_p1:
                    if st.button("Proceed anyway", key=f"proceed_run_{selected_name}"):
                        st.session_state[force_key] = True
                        st.rerun()
                with c_p2:
                    if st.button("Cancel", key=f"cancel_run_{selected_name}"):
                        st.session_state[attempt_key] = False
                        st.rerun()
                
                proceed_run = False
                
            if proceed_run:
                st.session_state[attempt_key] = False
                st.session_state.pop(force_key, None)
                st.session_state.pipeline_status = None
                
                pipeline_file_to_run = selected_path
                
                global_state = st.session_state[state_key_global]
                if global_state.get("use_filter", False):
                    tmp_dir = project_root / ".tmp"
                    tmp_dir.mkdir(parents=True, exist_ok=True)
                    tmp_path = tmp_dir / f"{selected_name}_tmp.toml"
                    
                    parsed_copy = parsed.copy()
                    go = parsed_copy.setdefault("global_options", {})
                    go["filter_opacity_threshold"] = float(global_state.get("threshold", default_threshold))
                    
                    with open(tmp_path, "wb") as f:
                        tomli_w.dump(parsed_copy, f)
                    pipeline_file_to_run = tmp_path
                    st.session_state["pipeline_tmp"] = str(pipeline_file_to_run)
                else:
                    pipeline_file_to_run = selected_path
                    st.session_state["pipeline_tmp"] = None
                
                cmd = [sys.executable, str(project_root / "main.py"), "run", str(selected_path)]
                if selected_input and selected_input != "-- none --":
                    cmd += ["--input", str(project_root / "inputs" / selected_input)]
                if output_name:
                    cmd += ["--output", str(project_root /  output_name)]
                for k, v in edits.items():
                    if isinstance(v, bool):
                        valstr = "true" if v else "false"
                    else:
                        valstr = str(v)
                    cmd += ["--set", f"{k}={valstr}"]
                cmd += ["--gui"]
                cmd += ["--verbose"]
                
                # if out_status.get("exists") and not out_status.get("empty"):
                #     cmd += ["--restart"]
                
                run_action = st.session_state.get(f"run_action_{selected_name}", None)
                if run_action == "restart":
                    cmd += ["--restart"]
                elif run_action == "resume":
                    pass

                try:
                    proc = subprocess.Popen(cmd, cwd=str(project_root), start_new_session=True)
                    st.session_state.pipeline_proc = proc
                    st.session_state.pipeline_cmd = cmd
                    st.session_state.pipeline_running = True
                    st.rerun()
                    status_area.success(f"Started pipeline (pid={proc.pid}).")
                except Exception as e:
                    status_area.error(f"Failed to start pipeline: {e}")
        
        if st.session_state.get("pipeline_proc"):
            proc = st.session_state.pipeline_proc
            try:
                ret = proc.poll()
            except Exception as e:
                ret = None
                
            if ret is None:
                status_area.info(f"Pipeline running (pid={proc.pid})")
                st.code(" ".join(st.session_state.pipeline_cmd or []), language="bash")
                st.markdown(
                    """
                    <div style="display: flex; align-items: center; gap: 10px; margin-top: 10px;">
                        <div style="border: 3px solid #f3f3f3; border-top: 3px solid #3498db; border-radius: 50%; width: 24px; height: 24px; animation: spin 1s linear infinite;"></div>
                        <span style="color: #666;">Pipeline is running...</span>
                    </div>
                    <style>@keyframes spin { 0% { transform: rotate(0deg); } 100% { transform: rotate(360deg); } }</style>
                """,
                    unsafe_allow_html=True,
                )

                time.sleep(2)
                st.rerun()
            else:
                if ret == 0:
                    st.session_state.pipeline_status = {"type": "success", "msg": f"Pipeline finished successfully (exit code {ret})."}
                else:
                    st.session_state.pipeline_status = {"type": "error", "msg": f"Pipeline finished with errors (exit code {ret})."}
                st.session_state.pipeline_proc = None
                st.session_state.pipeline_cmd = None
                st.session_state.pipeline_running = False
                
                #Clean tmp file if created
                tmp = st.session_state.get("pipeline_tmp", None)
                if tmp:
                    try:
                        Path(tmp).unlink()
                    except Exception:
                        pass
                st.rerun()           
                

st.markdown("---")
# st.info("Use the sidebar to manage methods, pipelines and inputs. Reload the page to refresh pipeline list.")

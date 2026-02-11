import streamlit as st
import sys
from pathlib import Path
import tomli_w

try:
    import tomllib as toml
except Exception:
    import tomli as toml

# Project root
current_file = Path(__file__).resolve()
# Risaliamo le directory finché non troviamo la cartella 'methods'
project_root = current_file.parent
while not (project_root / "pipelines").exists():
    if project_root == project_root.parent:
        # Fallback di sicurezza
        project_root = current_file.parents[3]
        break
    project_root = project_root.parent

if str(project_root) not in sys.path:
    sys.path.append(str(project_root))
    
try:
    from core.gui.web_ui import render_sidebar
except ImportError as e:
    print(f"Error importing render_sidebar: {e}")

st.set_page_config(
    page_title="ModularGS - Pipeline Manager", layout="wide", page_icon="🧭"
)
# render_sidebar(project_root)
st.title("Pipeline Manager")

# base_path_input = st.sidebar.text_input("Project Root Path", value=str(project_root))
base_path = Path(project_root)


envs_path = base_path / ".envs"
if not envs_path.exists():
    st.sidebar.warning("Folder '.envs' not found.")

pipelines_dir = base_path / "pipelines"
if not pipelines_dir.exists():
    st.warning("Folder 'pipelines' not found.")
    st.stop()


def load_pipeline_files(d: Path):
    return sorted([p for p in d.iterdir() if p.is_file() and p.suffix == ".toml"])


def parse_toml_file(p: Path):
    try:
        text = p.read_text(encoding="utf-8")
        return toml.loads(text)
    except Exception as e:
        return {"_parse_error": str(e)}


def required_methods_from_pipeline(parsed: dict):
    req = {}
    steps = parsed.get("steps", []) or []
    for i in steps:
        method_name = i.get("method").split("/")[-1].split(".")[0] or ""
        if method_name != "":
            kwargs = i.get("kwargs", {}) or {}
            args = {}
            if kwargs != {}:
                for k, v in kwargs.items():
                    if k not in ["output_key","primary_output"]:
                        args[k] = v
            req[method_name] = args
    return req


def installed_methods(envs: Path):
    res = set()
    if not envs.exists():
        return res
    for d in envs.iterdir():
        if d.is_dir() and (d / ".install_complete").exists():
            res.add(d.name)
    return res


pipeline_files = load_pipeline_files(pipelines_dir)
installed = installed_methods(envs_path)

st.sidebar.markdown(f"Found pipelines: **{len(pipeline_files)}**")
st.sidebar.markdown(f"Installed methods: **{len(installed)}**")

for pf in pipeline_files:
    parsed = parse_toml_file(pf)
    if "_parse_error" in parsed:
        st.error(f"{pf.name} — Error parsing: {parsed['_parse_error']}")
        continue

    meta = parsed.get("pipeline", {}) or {}
    name = meta.get("name", pf.stem)
    desc = meta.get("description", "")
    required = required_methods_from_pipeline(parsed)
    missing = [m for m in required if m not in installed]
    runnable = len(missing) == 0

    header = f"{name}"
    if runnable:
        st.success(header + " — Ready for execution")
    else:
        st.error(header + f" — Missing Tools: {', '.join(missing)}")
        
    #Editing session state for pipeline details
    state_key = f"pipeline_edit_{pf.name}"
    if state_key not in st.session_state:
        st.session_state[state_key] = required.copy()

    with st.expander("Pipeline Details"):
        if desc:
            st.write(desc)
        
        global_opts = parsed.get("global_options", {}) or {}
        has_threshold = "filter_opacity_threshold" in global_opts
        default_threshold = global_opts.get("filter_opacity_threshold", 0.1)
        
        state_key_global = f"{state_key}_global"
        if state_key_global not in st.session_state:
            st.session_state[state_key_global] = {
                "use_filter": bool(has_threshold),
                "threshold": default_threshold,
            }
            
        with st.expander("Global Options", expanded=False):
            use_filter = st.checkbox(
                "Use Opacity Filter",
                value =st.session_state[state_key_global]["use_filter"],
                key=f"{state_key}_use_filter"
            )
            st.session_state[state_key_global]["use_filter"] = use_filter
            
            if use_filter:
                thr = st.number_input(
                    "Opacity Threshold",
                    min_value = 0.0,
                    max_value = 1.0,
                    value = st.session_state[state_key_global]["threshold"],
                    step = 0.01,
                    format="%.2f",
                    key=f"{state_key}_threshold"
                )
                st.session_state[state_key_global]["threshold"] = thr
            else:
                thr = st.session_state[state_key_global]["threshold"]  # Keep previous value even if not used   
        
        st.write("Steps:")
        steps = required.keys()
        for step_name in steps:
            step_conf = parsed.get("step", {}).get(step_name, {}) or {}
            method = step_conf.get("method", "<no-method>")
            status = "✓" if step_name in installed else "✗"
            
            with st.expander(f"{step_name} - [{status}]", expanded=False):
                st.write(f"Stato: {status}")
                edit_container = st.container()
                current_kwargs = st.session_state[state_key].get(step_name, {})
                
                new_kwargs = {}
                for k, v in current_kwargs.items():
                    input_key = f"{state_key}_{step_name}_{k}"
                    if isinstance(v, bool):
                        new_v = edit_container.checkbox(k, value=v, key=input_key)
                    elif isinstance(v, int):
                        new_v = edit_container.number_input(k, value=v, key=input_key)
                    else:
                        new_v = edit_container.text_input(k, value=v, key=input_key)
                        
                        if new_v.lower() in ("true", "false"):
                            new_v = True if new_v.lower() == "true" else False
                        # else:
                        #     try:
                        #         if "." in new_v:
                        #             new_v = float(new_v)
                        #         else:
                        #             new_v = int(new_v)
                        #     except ValueError:
                        #         pass
                            
                    new_kwargs[k] = new_v
                    
                st.session_state[state_key][step_name] = new_kwargs
                
                if st.button(f"Aggiungi parametro a {step_name}", key=f"add_param_{state_key}_{step_name}"):
                    st.session_state[state_key][step_name][f"new_param_{len(current_kwargs)}"] = ""
                    st.rerun()
                    
        st.write("File:", pf.name)
        
        if st.button(f"Salva modifiche in {pf.name}", key=f"save_{pf.name}"):
            try:
                edits = st.session_state[state_key]
                steps_section = parsed.setdefault("step", {})
                for step_name, kws in edits.items():
                    if step_name not in steps_section:
                        steps_section[step_name] = {}
                    steps_section[step_name]["kwargs"] = kws
                    
                global_state = st.session_state[state_key_global]
                if global_state.get("use_filter", False):
                    go = parsed.setdefault("global_options", {})
                    go["filter_opacity_threshold"] = float(global_state.get("threshold", default_threshold))
                else:
                    if "global_options" in parsed and "filter_opacity_threshold" in parsed["global_options"]:
                        parsed["global_options"].pop("filter_opacity_threshold", None)
                        if not parsed["global_options"]:
                            parsed.pop("global_options", None)
                    
                with open(pf, "wb") as f:
                    tomli_w.dump(parsed, f)
                st.success(f"Args Saved in {pf.name}")
            except Exception as e:
                st.error(f"Error saving: {e}")
    st.divider()

st.info("Reload the page to update the pipeline status after installing/uninstalling methods.")

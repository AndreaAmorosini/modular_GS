import streamlit as st
import sys
from pathlib import Path

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
    req = []
    steps = parsed.get("steps", []) or []
    for i in steps:
        method_name = i.get("method").split("/")[-1].split(".")[0] or ""
        if method_name != "":
            req.append(method_name)
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

    header = f"{name} — {pf.name}"
    if runnable:
        st.success(header + " — Ready for execution")
    else:
        st.error(header + f" — Missing Tools: {', '.join(missing)}")

    with st.expander("Pipeline Details"):
        if desc:
            st.write(desc)
        st.write("Steps:")
        steps = required
        for step_name in steps:
            step_conf = parsed.get("step", {}).get(step_name, {}) or {}
            # method = step_conf.get("method", "<no-method>")
            status = "✓" if step_name in installed else "✗"
            # st.write(f"- {step_name}: {method} {status}")
            st.write(f"- {step_name}: {status}")

        st.write("File:", pf.name)

    st.divider()

st.info("Reload the page to update the pipeline status after installing/uninstalling methods.")

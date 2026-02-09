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

st.set_page_config(
    page_title="ModularGS - Pipeline Manager", layout="wide", page_icon="🧭"
)
st.title("Pipeline Manager")

base_path_input = st.sidebar.text_input("Project Root Path", value=str(project_root))
base_path = Path(base_path_input)

envs_path = base_path / ".envs"
if not envs_path.exists():
    st.sidebar.warning("Cartella '.envs' non trovata nella root specificata.")

pipelines_dir = base_path / "pipelines"
if not pipelines_dir.exists():
    st.warning("Cartella 'pipelines' non trovata nella root del progetto.")
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
    # TODO: Da fixare
    req = []
    steps = parsed.get("steps", []) or []
    print(f"Parsing pipeline steps: {steps}")
    for i in steps:
        print(f"Step: {i}")
        print(f"Step method name: {i.get('method')}")
    step_sections = parsed.get("step", {}) or {}
    for step_name in steps:
        step_conf = step_sections.get(step_name, {}) or {}
        method = step_conf.get("method")
        if method:
            req.append(method)
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
        st.error(f"{pf.name} — Errore parsing: {parsed['_parse_error']}")
        continue

    meta = parsed.get("pipeline", {}) or {}
    name = meta.get("name", pf.stem)
    desc = meta.get("description", "")
    required = required_methods_from_pipeline(parsed)
    missing = [m for m in required if m not in installed]
    runnable = len(missing) == 0

    header = f"{name} — {pf.name}"
    if runnable:
        st.success(header + " — Pronta per l'esecuzione")
    else:
        st.error(header + f" — Mancano strumenti: {', '.join(missing)}")

    with st.expander("Dettagli pipeline"):
        if desc:
            st.write(desc)
        st.write("Passi (ordine):")
        steps = meta.get("steps", []) or []
        for step_name in steps:
            step_conf = parsed.get("step", {}).get(step_name, {}) or {}
            method = step_conf.get("method", "<no-method>")
            status = "✓" if method in installed else "✗"
            st.write(f"- {step_name}: {method} {status}")
        st.write("File:", pf.name)

    st.divider()

st.info("Aggiorna la pagina per ricaricare lo stato dei metodi installati.")

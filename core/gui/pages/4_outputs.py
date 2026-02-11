import streamlit as st
import sys
from pathlib import Path

# Rileva project root (stesso comportamento delle altre pagine)
current_file = Path(__file__).resolve()
project_root = current_file.parent
while not (project_root / "output").exists():
    if project_root == project_root.parent:
        project_root = current_file.parents[3]
        break
    project_root = project_root.parent

if str(project_root) not in sys.path:
    sys.path.append(str(project_root))


st.set_page_config(page_title="Outputs", layout="wide", page_icon="📁")

st.title("Outputs")

outputs_dir = project_root / "output"
if not outputs_dir.exists():
    st.warning(f"Folder 'output' non trovata in: {outputs_dir}")
else:
    dirs = sorted(
        [p for p in outputs_dir.iterdir() if p.is_dir()], key=lambda p: p.name.lower()
    )
    if not dirs:
        st.info("Nessuna cartella trovata in 'output/'.")
    else:
        st.markdown("### Cartelle trovate")
        for d in dirs:
            # Mostra solo nome della cartella e la sua posizione (relativa al project root)
            rel = d.relative_to(project_root)
            st.write(f"- **{d.name}** — {rel}")

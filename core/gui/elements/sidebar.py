from pathlib import Path
import streamlit as st

def render_sidebar(base_path: Path):
    logo_path = base_path / "core" / "gui" / "images" / "logo.png"
    if logo_path.exists():
        st.sidebar.image(str(logo_path), width=400)
    st.sidebar.title("ModularGS")
    st.sidebar.caption("A modular pipeline for Gaussian Splatting. Use the sidebar to navigate between pages and manage your methods and pipelines.")
    st.sidebar.markdown("[Github](https://github.com/AndreaAmorosini/modular_GS)")
    st.sidebar.markdown("---")

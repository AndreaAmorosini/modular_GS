import streamlit as st
import sys
import os
import json
import yaml
from pathlib import Path

# Root Path Configuration
current_file = Path(__file__).resolve()
project_root = current_file.parent.parent.parent
if str(project_root) not in sys.path:
    sys.path.append(str(project_root))
# print(f"Project Root: {project_root}")

try:
    from core.components.base import MethodRunner
    from core.utils import RichLogger
    from core.gui.elements.sidebar import render_sidebar
except ImportError as e:
    print(f"Error importing MethodRunner: {e}")
    st.stop()
    
# Streamlit Page Configuration
st.set_page_config(
    page_title = "ModularGS Pipeline",
    layout = "wide",
    page_icon = "🧩"
)
render_sidebar(project_root)
base_path = Path(project_root)

pages = [
    st.Page("pages/home.py", title="Home", icon="🏠"),
    st.Page("pages/1_manage_tools.py", title="Manage Methods", icon="📦"),
    st.Page("pages/2_manage_pipeline.py", title="Pipeline Manager", icon="🧭"),
    st.Page("pages/3_inputs.py", title="Inputs", icon="📁"),
    st.Page("pages/4_outputs.py", title="Outputs", icon="▶️"),
]

#Magari position="top" per avere il logo su nella sidebar
pg = st.navigation(pages, position="sidebar", expanded=True)
pg.run()
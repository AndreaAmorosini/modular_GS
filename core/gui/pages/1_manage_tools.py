import streamlit as st
import sys
from pathlib import Path
import shutil
import subprocess
import tomli as tomllib

st.set_page_config(
    page_title = "Manage Methods",
    page_icon = "📦",
    layout = "wide"
)

current_file = Path(__file__).resolve()
# Risaliamo le directory finché non troviamo la cartella 'methods'
project_root = current_file.parent
while not (project_root / "methods").exists():
    if project_root == project_root.parent:
        # Fallback di sicurezza
        project_root = current_file.parents[3]
        break
    project_root = project_root.parent

if str(project_root) not in sys.path:
    sys.path.append(str(project_root))

try:
    from core.components.base import MethodRunner
    from core.installer import MethodInstaller
    from core.validation import Validator
    from core.gui.elements.sidebar import render_sidebar
    from main import uninstall_method
except ImportError as e:
    st.error(f"Error importing core modules: {e}")
    st.stop()


# render_sidebar(project_root)

st.title("📦 Manage Methods")

st.markdown("""
Manage the installation of methods in the Modular Gaussian Splatting pipeline.
This page let you list, install and uninstall methods. Each method is defined by a configuration file that specifies how to set it up and run it.
""")


methods_dir = project_root / "methods"
if not methods_dir.exists():
    st.error(f"Methods folder not found in `{project_root}`.")
    st.stop()
    
try:
    validator = Validator(methods_dir=methods_dir, verbose=True)
    registry = validator.registry
except Exception as e:
    st.error(f"Failed Initialization of Validator: {e}")
    st.stop()

if not registry:
    st.info("No method Found.")
    st.stop()

# Group methods by category (using parent directort name)
categories = {}
for method_id, config in registry.items():
    toml_path = config.get("__path__")
    if toml_path:
        category = toml_path.parent.name
        if category not in categories:
            categories[category] = []
        categories[category].append((method_id, config))

envs_dir = project_root / ".envs"

for category in sorted(categories.keys()):
    # st.markdown(f"### 📂 {category.upper()}")
    with st.expander(f"📂 {category.upper()}", expanded=False):
        for method_id, config in categories[category]:
            env_path = envs_dir / method_id

            # Check if installed
            is_installed = (env_path / ".install_complete").exists()

            with st.container(border=True):
                c1, c2, c3 = st.columns([3, 2, 4])

                with c1:
                    st.markdown(f"**{config.get('title', method_id)}**")
                    st.caption(f"ID: `{method_id}`")

                with c2:
                    if is_installed:
                        st.success("✅ Installed")
                    else:
                        st.warning("❌ Not Installed")

                with c3:
                    b1, b2, b3 = st.columns(3)

                    if b1.button(
                        "Install",
                        key=f"inst_{method_id}",
                        disabled=is_installed,
                        use_container_width=True,
                    ):
                        with st.spinner(f"Installing {method_id}..."):
                            try:
                                # MethodInstaller gestisce l'installazione nell'env_path specificato
                                installer = MethodInstaller(
                                    method_config=config,
                                    base_path=project_root,
                                    verbose=True,
                                )
                                installer.install(env_path)
                                st.success("Installation Complete!")
                                st.rerun()
                            except Exception as e:
                                st.error(f"Error installing: {e}")

                    if b2.button(
                        "Validate",
                        key=f"val_{method_id}",
                        disabled=not is_installed,
                        use_container_width=True,
                    ):
                        with st.spinner(f"Validating {method_id}..."):
                            # Validator esegue il comando pixi run validate
                            success = validator.validate_method(method_id, all=True)
                            if success:
                                st.success("Validation OK!")
                            else:
                                st.error(
                                    "Validation Failed! Check the logs for details."
                                )

                    if b3.button(
                        "Uninstall",
                        key=f"uninst_{method_id}",
                        disabled=not is_installed,
                        use_container_width=True,
                    ):
                        if env_path.exists():
                            with st.spinner(f"Uninstalling {method_id}..."):
                                try:
                                    uninstall_method(method_id, verbose=True, subcall=False, from_CLI=False)
                                    st.success("Uninstallation Complete!")
                                    st.rerun()
                                except Exception as e:
                                    st.error("Error during uninstallation. Check logs for details.")
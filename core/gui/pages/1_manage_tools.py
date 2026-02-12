import streamlit as st
import sys
from pathlib import Path
import shutil
import subprocess
import tomli as tomllib
import os

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
    from core.installer import MethodInstaller
    from core.validation import Validator
    from core.utils import SignatureVerifier
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
    
verifier = SignatureVerifier()

if not registry:
    st.info("No method Found.")
    st.stop()
    
def _get_dir_size_bytes(p: Path) -> int:
    try:
        proc = subprocess.run(
            ["du", "-sb", str(p)],
            capture_output=True,
            text=True,
            check=True,
        )
        out = proc.stdout.strip().split()
        if out:
            return int(out[0])
    except Exception as e:
        st.error(f"Error calculating size for {p}: {e}")
    return 0


total_tools = len(registry)
installed_count = 0
envs_dir = project_root / ".envs"
total_bytes = 0

for method_id , cfg in registry.items():
    env_path = envs_dir / method_id
    if (env_path / ".install_complete").exists():
        installed_count += 1
        
if envs_dir.exists():
    total_bytes = _get_dir_size_bytes(envs_dir)
    # for child in envs_dir.iterdir():
    #     if child.is_dir():
    #         total_bytes += _get_dir_size_bytes(child)
            
def _readable(n: int) -> str:
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if n < 1024:
            return f"{n:.2f} {unit}"
        n /= 1024
    return f"{n:.2f} PB"

st.sidebar.markdown("### Tools Summary")
st.sidebar.write(f"Total Tools: **{total_tools}**")
st.sidebar.write(f"Installed: **{installed_count}**")
st.sidebar.write(f"Disk Usage: **{_readable(total_bytes)}**")

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
    with st.expander(f"📂 {category.upper()}", expanded=False):
        for method_id, config in categories[category]:
            env_path = envs_dir / method_id
            toml_path = config.get("__path__")

            # Check if installed
            is_installed = (env_path / ".install_complete").exists()
            
            #Check for help section in toml (calculated in validation)
            has_help = bool(config.get("has_help", False))
                    
            show_args_disabled = (not is_installed) or (not has_help)

            with st.container(border=True):
                c1, c2, c3 = st.columns([3, 2, 4])

                with c1:
                    st.markdown(f"**{config.get('title', method_id)}**")
                    st.markdown(f"{config.get('description', 'No description')}")
                    st.markdown(f'<a href="{config.get("url", "")}" target="_blank" rel="noopener noreferrer">{config.get("url", "")}</a>', unsafe_allow_html=True)

                with c2:
                    if is_installed:
                        st.success("✅ Installed")
                    else:
                        st.warning("❌ Not Installed")

                with c3:
                    b1, b2, b3, b4 = st.columns(4)

                    # if b1.button(
                    #     "Install",
                    #     key=f"inst_{method_id}",
                    #     disabled=is_installed,
                    #     use_container_width=True,
                    # ):
                    #     #SIGNATURE VERIFICATION
                    #     proceed_install = True
                    #     if toml_path and toml_path.exists():
                    #         ok = verifier.verify(Path(toml_path))
                    #         if not ok and not st.session_state.get(f"force_install_{method_id}", False):
                    #             st.warning(f"Signature verification FAILED for {toml_path.name}. Installation is not recommended. You can choose to force the installation, but proceed with caution.")
                    #             if st.button("Proceed Anyway", key=f"proceed_install_{method_id}"):
                    #                 st.session_state[f"force_install_{method_id}"] = True
                    #                 st.rerun()
                    #             proceed_install = False
                                
                    #     if proceed_install:        
                    #         with st.spinner(f"Installing {method_id}..."):
                    #             try:
                    #                 # MethodInstaller gestisce l'installazione nell'env_path specificato
                    #                 installer = MethodInstaller(
                    #                     method_config=config,
                    #                     base_path=project_root,
                    #                     verbose=True,
                    #                 )
                    #                 installer.install(env_path)
                    #                 st.success("Installation Complete!")
                    #                 st.session_state.pop(f"force_install_{method_id}", None)  # Reset force flag after installation
                    #                 st.rerun()
                    #             except Exception as e:
                    #                 st.error(f"Error installing: {e}")

                    # if b2.button(
                    #     "Validate",
                    #     key=f"val_{method_id}",
                    #     disabled=not is_installed,
                    #     use_container_width=True,
                    # ):
                    #     #SIGNATURE VERIFICATION
                    #     proceed_validate = True
                    #     if toml_path and toml_path.exists():
                    #         ok = verifier.verify(Path(toml_path))
                    #         if not ok and not st.session_state.get(f"force_validate_{method_id}", False):
                    #             st.warning(f"Signature verification FAILED for {toml_path.name}. You can proceed anyway, but be cautious.")
                    #             if st.button("Proceed Anyway", key=f"proceed_validate_{method_id}"):
                    #                 st.session_state[f"force_validate_{method_id}"] = True
                    #                 st.rerun()
                    #             proceed_validate = False

                    #     if proceed_validate:
                    #         with st.spinner(f"Validating {method_id}..."):
                    #             # Validator esegue il comando pixi run validate
                    #             success = validator.validate_method(method_id, all=True)
                    #             if success:
                    #                 st.success("Validation OK!")
                    #             else:
                    #                 st.error("Validation Failed! Check the logs for details.")
                    #             st.session_state.pop(f"force_validate_{method_id}", None)  # Reset force flag after validation

                    # if b3.button(
                    #     "Uninstall",
                    #     key=f"uninst_{method_id}",
                    #     disabled=not is_installed,
                    #     use_container_width=True,
                    # ):
                    #     if env_path.exists():
                    #         with st.spinner(f"Uninstalling {method_id}..."):
                    #             try:
                    #                 uninstall_method(method_id, verbose=True, subcall=False, from_CLI=False)
                    #                 st.success("Uninstallation Complete!")
                    #                 st.rerun()
                    #             except Exception as e:
                    #                 st.error("Error during uninstallation. Check logs for details.")
                                    
                    # if b4.button(
                    #     "Show Arguments",
                    #     key = f"args_{method_id}",
                    #     disabled=show_args_disabled,
                    #     use_container_width=True,
                    # ):
                    #     if not has_help:
                    #         st.warning("No help section found in the method configuration.")
                    #         continue
                        
                    #     # Signature check for help action
                    #     proceed_help = True
                    #     if toml_path and toml_path.exists():
                    #         ok = verifier.verify(Path(toml_path))
                    #         if not ok and not st.session_state.get(f"force_help_{method_id}", False):
                    #             st.warning(f"Signature verification FAILED for `{toml_path.name}`. Press 'Proceed anyway' to continue.")
                    #             if st.button("Proceed anyway", key=f"proceed_help_{method_id}"):
                    #                 st.session_state[f"force_help_{method_id}"] = True
                    #                 st.experimental_rerun()
                    #             proceed_help = False
                                
                    #     if not proceed_help:
                    #         continue
                        
                    #     cmd = [
                    #         sys.executable,
                    #         str(project_root / "main.py"),
                    #         "methods",
                    #         "help",
                    #         method_id,
                    #     ]
                    #     with st.spinner(f"Fetching parameters for {method_id}..."):
                    #         try:
                    #             proc = subprocess.run(
                    #                 cmd,
                    #                 cwd=str(project_root),
                    #                 capture_output=True,
                    #                 text=True,
                    #             )
                    #             stdout = proc.stdout or ""
                    #             stderr = proc.stderr or ""
                    #             exit_code = proc.returncode

                    #             # Mostra in modal (fallback a expander se modal non disponibile)
                    #             try:
                    #                 with st.modal(f"Parameters — {method_id}"):
                    #                     if stdout:
                    #                         st.subheader("Output")
                    #                         st.code(stdout, language="bash")
                    #                     else:
                    #                         st.info(
                    #                             "No stdout produced by the command."
                    #                         )
                    #                     st.caption(f"Exit code: {exit_code}")
                    #                     st.button(
                    #                         "Close", key=f"close_params_{method_id}"
                    #                     )
                    #             except Exception:
                    #                 # Fallback
                    #                 with st.expander(
                    #                     f"Parameters — {method_id}", expanded=True
                    #                 ):
                    #                     if stdout:
                    #                         st.subheader("Output")
                    #                         st.code(stdout, language="bash")
                    #                     else:
                    #                         st.info(
                    #                             "No stdout produced by the command."
                    #                         )
                    #                     # if stderr:
                    #                     #     st.subheader("Errors / Stderr")
                    #                     #     st.code(stderr, language="bash")
                    #                     st.caption(f"Exit code: {exit_code}")
                            # except Exception as e:
                            #     st.error(f"Error fetching parameters: {e}")
                            
                    b1_clicked = b1.button(
                        "Install",
                        key=f"inst_{method_id}",
                        disabled=is_installed,
                        use_container_width=True,
                    )
                    b2_clicked = b2.button(
                        "Validate",
                        key=f"val_{method_id}",
                        disabled=not is_installed,
                        use_container_width=True,
                    )
                    b3_clicked = b3.button(
                        "Uninstall",
                        key=f"uninst_{method_id}",
                        disabled=not is_installed,
                        use_container_width=True,
                    )
                    b4_clicked = b4.button(
                        "Show Arguments",
                        key=f"args_{method_id}",
                        disabled=show_args_disabled,
                        use_container_width=True,
                    )

                    # --- INSTALL ---
                    attempt_install_key = f"attempt_install_{method_id}"
                    force_install_key = f"force_install_{method_id}"
                    
                    if b1_clicked:
                        st.session_state[attempt_install_key] = True

                    if st.session_state.get(attempt_install_key, False) and not is_installed:
                        proceed_install = True
                        if toml_path and toml_path.exists():
                            ok = verifier.verify(Path(toml_path))
                            if not ok and not st.session_state.get(
                                force_install_key, False
                            ):
                                st.warning(
                                    f"Signature verification FAILED for {toml_path.name}. Installation is not recommended."
                                )
                                c_i1, c_i2 = st.columns([1, 5])
                                with c_i1:
                                    if st.button(
                                        "Proceed Anyway", key=f"proceed_install_{method_id}"
                                    ):
                                        st.session_state[force_install_key] = True
                                        st.rerun()
                                with c_i2:
                                    if st.button(
                                        "Cancel", key=f"cancel_install_{method_id}"
                                    ):
                                        st.session_state[attempt_install_key] = False
                                        st.rerun()
                                proceed_install = False

                        if proceed_install:
                            with st.spinner(f"Installing {method_id}..."):
                                try:
                                    installer = MethodInstaller(
                                        method_config=config,
                                        base_path=project_root,
                                        verbose=True,
                                    )
                                    installer.install(env_path)
                                    st.success("Installation Complete!")
                                    # cleanup one-shot flags
                                    st.session_state.pop(force_install_key, None)
                                    st.session_state[attempt_install_key] = False
                                    st.rerun()
                                except Exception as e:
                                    st.error(f"Error installing: {e}")

                    # --- VALIDATE ---
                    attempt_validate_key = f"attempt_validate_{method_id}"
                    force_validate_key = f"force_validate_{method_id}"
                    
                    if b2_clicked:
                        st.session_state[attempt_validate_key] = True

                    if st.session_state.get(attempt_validate_key, False) and is_installed:
                        proceed_validate = True
                        if toml_path and toml_path.exists():
                            ok = verifier.verify(Path(toml_path))
                            if not ok and not st.session_state.get(
                                force_validate_key, False
                            ):
                                st.warning(
                                    f"Signature verification FAILED for {toml_path.name}. Validation is not recommended."
                                )
                                c_v1, c_v2 = st.columns([1, 5])
                                with c_v1:
                                    if st.button(
                                        "Proceed Anyway",
                                        key=f"proceed_validate_{method_id}",
                                    ):
                                        st.session_state[force_validate_key] = True
                                        st.rerun()
                                with c_v2:
                                    if st.button(
                                        "Cancel", key=f"cancel_validate_{method_id}"
                                    ):
                                        st.session_state[attempt_validate_key] = False
                                        st.rerun()
                                proceed_validate = False

                        if proceed_validate:
                            with st.spinner(f"Validating {method_id}..."):
                                success = validator.validate_method(method_id, all=True)
                                if success:
                                    st.success("Validation OK!")
                                else:
                                    st.error(
                                        "Validation Failed! Check the logs for details."
                                    )
                                st.session_state.pop(force_validate_key, None)
                                st.session_state[attempt_validate_key] = False

                    # --- UNINSTALL (unchanged) ---
                    if b3_clicked:
                        if env_path.exists():
                            with st.spinner(f"Uninstalling {method_id}..."):
                                try:
                                    uninstall_method(
                                        method_id,
                                        verbose=True,
                                        subcall=False,
                                        from_CLI=False,
                                    )
                                    st.success("Uninstallation Complete!")
                                    st.rerun()
                                except Exception as e:
                                    st.error(
                                        "Error during uninstallation. Check logs for details."
                                    )

                    # --- SHOW ARGUMENTS ---
                    attempt_help_key = f"attempt_help_{method_id}"
                    force_help_key = f"force_help_{method_id}"
                    
                    if b4_clicked:
                        st.session_state[attempt_help_key] = True

                    if st.session_state.get(attempt_help_key, False):
                        if not has_help:
                            st.warning(
                                "No help section found in the method configuration."
                            )
                            st.session_state[attempt_help_key] = False
                        else:
                            proceed_help = True
                            if toml_path and toml_path.exists():
                                ok = verifier.verify(Path(toml_path))
                                if not ok and not st.session_state.get(
                                    force_help_key, False
                                ):
                                    st.warning(
                                        f"Signature verification FAILED for `{toml_path.name}`. Fetching parameters is not recommended."
                                    )
                                    c_h1, c_h2 = st.columns([1, 5])
                                    with c_h1:
                                        if st.button(
                                            "Proceed Anyway",
                                            key=f"proceed_help_{method_id}",
                                        ):
                                            st.session_state[force_help_key] = True
                                            st.rerun()
                                    with c_h2:
                                        if st.button(
                                            "Cancel", key=f"cancel_help_{method_id}"
                                        ):
                                            st.session_state[attempt_help_key] = False
                                            st.rerun()
                                    proceed_help = False

                            if proceed_help:
                                # run the help command
                                cmd = [
                                    sys.executable,
                                    str(project_root / "main.py"),
                                    "methods",
                                    "help",
                                    method_id,
                                ]
                                with st.spinner(
                                    f"Fetching parameters for {method_id}..."
                                ):
                                    try:
                                        proc = subprocess.run(
                                            cmd,
                                            cwd=str(project_root),
                                            capture_output=True,
                                            text=True,
                                        )
                                        stdout = proc.stdout or ""
                                        exit_code = proc.returncode

                                        st.session_state.pop(force_help_key, None)
                                        st.session_state[attempt_help_key] = False

                                        try:
                                            with st.modal(f"Parameters — {method_id}"):
                                                if stdout:
                                                    st.subheader("Output")
                                                    st.code(stdout, language="bash")
                                                else:
                                                    st.info(
                                                        "No stdout produced by the command."
                                                    )
                                                st.caption(f"Exit code: {exit_code}")
                                                st.button(
                                                    "Close",
                                                    key=f"close_params_{method_id}",
                                                )
                                        except Exception:
                                            with st.expander(
                                                f"Parameters — {method_id}",
                                                expanded=True,
                                            ):
                                                if stdout:
                                                    st.subheader("Output")
                                                    st.code(stdout, language="bash")
                                                else:
                                                    st.info(
                                                        "No stdout produced by the command."
                                                    )
                                                st.caption(f"Exit code: {exit_code}")

                                    except Exception as e:
                                        st.error(f"Error fetching parameters: {e}")
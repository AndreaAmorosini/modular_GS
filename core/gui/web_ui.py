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
print(f"Project Root: {project_root}")

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
]

#Magari position="top" per avere il logo su nella sidebar
pg = st.navigation(pages, position="sidebar", expanded=True)
pg.run()



# st.title("Modular Gaussian Splatting - Web GUI")
# st.markdown("This is a web interface for the Modular Gaussian Splatting pipeline. Use the sidebar to configure and run methods.")

# # Sidebar Configuration
# st.sidebar.header("Pipeline Configuration")
# # base_path_input = st.sidebar.text_input("Project Root Path", value=str(project_root))


# # Load envs Configuration
# envs_path = base_path / ".envs"
# if not envs_path.exists():
#     st.sidebar.warning("Folder '.envs' not found.")
#     envs_path_input = st.sidebar.text_input("Percorso cartella .envs", value=str(base_path / ".envs"))
#     envs_path = Path(envs_path_input)

# # Load Method Configurations
# methods_dir = base_path / "methods"
# if not methods_dir.exists():
#     st.sidebar.warning("Folder 'methods' not found.")
#     methods_dir_input = st.sidebar.text_input("Methods dir path", value=str(base_path / "methods"))
#     methods_dir = Path(methods_dir_input)    

# # Utility Function
# def load_all_methods(directory: Path):
#     #Load all methods from the specified directory. Each method is expected to be in its own subdirectory with a config.yaml file.
#     if not directory.exists():
#         return []
    
#     methods = []
    
#     for d in directory.iterdir():
#         if d.is_dir() and not d.name.startswith("."):
#             for f in d.iterdir():
#                 if f.suffix == ".toml":
#                     methods.append(f)
                
#     return methods

# def load_installed_methods(directory: Path):
#     # Load all installed method by checking if they are installed
    
#     all_methods = load_all_methods(directory)
#     all_methods_name = [m.name.split(".")[0] for m in all_methods]
    
#     installed_methods = []
#     for d in envs_path.iterdir():
#         if d.is_dir() and d.name in all_methods_name:
#             if Path(d/".install_complete").exists():
#                 installed_methods.append(d)
                    
#     return installed_methods


# def load_config(method_path: Path):
#     #Load the config.yaml (for standalone methods) or config.json (for methods in shared env) file for a given method. Returns a dictionary of the configuration.
#     yaml_path = method_path / "config.yaml"
#     json_path = method_path / "config.json"
    
#     if yaml_path.exists():
#         with open(yaml_path, "r") as f:
#             return yaml.safe_load(f)
#     elif json_path.exists():
#         with open(json_path, "r") as f:
#             return json.load(f)
        
#     return None

# # Method Selection
# available_methods = load_all_methods(methods_dir)
# installed_methods = load_installed_methods(methods_dir)
# print(f"Available Methods: {[m.name for m in available_methods]}")
# method_names = [m.name for m in available_methods]

# if not available_methods:
#     st.warning("No valid method configurations found in the methods directory. Please ensure there are subdirectories with .TOML files.")
#     st.stop()
    
# selected_method_name = st.sidebar.selectbox("Select Method", method_names)
# selected_method_path = next(m for m in available_methods if m.name == selected_method_name)

# config = load_config(selected_method_path)

# if config:
#     st.header(f"Selected Method: {config.get('title', selected_method_name)}")
    
#     with st.expander("Method Configuration"):
#         st.json(config)
        
#     col1, col2 = st.columns(2)
    
#     with col1:
#         st.subheader("Inputs")
#         st.info("Input fields will be generated here based on the method configuration.")
        
#         if "inputs" not in st.session_state:
#             st.session_state.inputs = {}
            
#         with st.form("add_input_form", clear_on_submit=True):
#             input_key = st.text_input("Input Key (e.g. video)")
#             input_value = st.text_input("Input Value (e.g. /path/to/video.mp4)")
#             submitted = st.form_submit_button("Add Input")
            
#             if submitted and input_key and input_value:
#                 st.session_state.inputs[input_key] = input_value
#                 st.success(f"Added input: {input_key} -> {input_value}")
                
#         if st.session_state.inputs:
#             st.write("Current Inputs:")
#             st.json(st.session_state.inputs)
#             if st.button("Clear Inputs"):
#                 st.session_state.inputs = {}
#                 st.success("Inputs cleared.")
                
#     with col2:
#         st.subheader("Parameters")
#         st.info("Optional Parameter fields will be generated here based on the method configuration.")
        
#         if "kwargs" not in st.session_state:
#             st.session_state.kwargs = {}
            
#         with st.form("add_param_form", clear_on_submit=True):
#             param_key = st.text_input("Parameter Key (e.g. threshold)")
#             param_value = st.text_input("Parameter Value (e.g. 0.5)")
#             submitted = st.form_submit_button("Add Parameter")
            
#             if submitted and param_key:
#                 if param_value.lower() == "true" : val_parsed = True
#                 elif param_value.lower() == "false" : val_parsed = False
#                 else:
#                     try:
#                         val_parsed = int(param_value)
#                     except ValueError:
#                         try:
#                             val_parsed = float(param_value)
#                         except ValueError:
#                             val_parsed = param_value
#                 st.session_state.kwargs[param_key] = val_parsed
#                 st.success(f"Added parameter: {param_key} -> {val_parsed}")
                
#         if st.session_state.kwargs:
#             st.write("Current Parameters:")
#             st.json(st.session_state.kwargs)
#             if st.button("Clear Parameters"):
#                 st.session_state.kwargs = {}
#                 st.success("Parameters cleared.")
                
#     st.divider()
#     st.subheader("Run Method")
    
#     out_dir_name = st.text_input("Output Directory Name (relative to project root)", value=f"outputs/{selected_method_name}")
#     step_output_dir = base_path / "outputs" / out_dir_name
    
#     if st.button("Run Method", type="primary"):
#         st.write(f"Output will be saved to: {step_output_dir}")
        
#         runner = MethodRunner(
#             method_config = config,
#             env_path = selected_method_path,
#             base_path = base_path,
#             verbose = True
#         )
        
#         progress_bar = st.progress(0)
#         status_text = st.empty()
        
#         try:
#             status_text.text("Starting pipeline...")
#             progress_bar.progress(10)
            
#             with st.spinner("Running method..."):
#                 outputs = runner.run(
#                     inputs = st.session_state.inputs,
#                     kwargs = st.session_state.kwargs,
#                     step_output_dir = step_output_dir
#                 )
            
#             progress_bar.progress(100)
#             status_text.text("Method execution completed.")
#             st.success("Method executed successfully!")
            
#             st.subheader("Generated Outputs")
#             st.json(outputs)
            
#         except Exception as e:
#             st.error(f"Error during method execution, {e}")
#             st.exception(e)
            
# else:
#     st.error("No valid method configurations found in the methods directory. Please ensure there are subdirectories with .TOML files.")

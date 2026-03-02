import streamlit as st
import sys
import os
import platform
import subprocess
from pathlib import Path
import json
from datetime import datetime
import shutil

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

st.set_page_config(
    page_title="Modular Gaussian Splatting - Outputs", layout="wide", page_icon="📁"
)

st.title("Outputs")
st.markdown(
    "### **To visualize the sparse reconstruction you can use [ColmapView](https://colmapview.github.io/latest/)**"
)
st.markdown(
    "### **To visualize the resulting splat you can use the [Supersplat editor](https://superspl.at/editor)**"
)

        
def open_folder(path="."):
    """Apre il file explorer gestendo correttamente i percorsi WSL -> Windows."""
    # Normalizza il percorso per il sistema attuale
    target_path = os.path.abspath(path)
    system = platform.system()

    # 1. CASO WSL (Linux con kernel Microsoft)
    if system == "Linux" and "microsoft" in platform.release().lower():
        try:
            # Converte il percorso Linux in formato Windows UNC via wslpath
            win_path = (
                subprocess.check_output(["wslpath", "-w", target_path]).decode().strip()
            )
            subprocess.run(["explorer.exe", win_path])
        except subprocess.CalledProcessError:
            # Fallback se wslpath fallisce (es. percorsi non validi)
            subprocess.run(["explorer.exe", target_path])

    # 2. CASO WINDOWS NATIVO
    elif system == "Windows":
        os.startfile(target_path)

    # 3. CASO MACOS
    elif system == "Darwin":
        subprocess.run(["open", target_path])

    # 4. CASO LINUX STANDARD
    else:
        subprocess.run(["xdg-open", target_path])


def find_sfm_path(run_dir: Path):
    """Find the sparse reconstruction folder."""
    run_dir = run_dir / "StructureFromMotion"
    candidates = [
        run_dir / "colmap" / "sparse" / "0",
        run_dir / "sparse" / "0",
        run_dir / "colmap" / "sparse",
    ]
    for c in candidates:
        if c.exists(): return c
    return None

def find_gs_ply(run_dir: Path):
    """Find the best .ply file for Gaussian Splatting."""
    # 1. Check for final result
    final = run_dir / "final_result" / "final_gaussian.ply"
    if final.exists(): return final
    
    # 2. Search recursively for any .ply (excluding sparse ones)
    plys = list(run_dir.rglob("*.ply"))
    plys = [p for p in plys if "sparse" not in str(p)]
    
    if not plys: return None
    
    # 3. Return the most recently modified
    plys.sort(key=lambda x: x.stat().st_mtime, reverse=True)
    return plys[0]

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
        st.markdown("### Runs")
        for d in dirs:
            c1, c2, c3, c4, c5 = st.columns([4, 1, 1, 1, 1])
            
            with c1:
                st.markdown(f"**{d.name}**")
                st.caption(f"Path: `{d.relative_to(project_root)}`")
            
            with c2:
                if st.button("📂 Project Folder", key=f"open_{d.name}", use_container_width=True):
                    open_folder(d)
            
            with c3:
                sfm_path = find_sfm_path(d)
                disabled_sfm = sfm_path is None
                if st.button("📂 SFM Files", key=f"sfm_{d.name}", disabled=disabled_sfm, use_container_width=True):
                    open_folder(sfm_path)

            with c4:
                gs_path = find_gs_ply(d)
                disabled_gs = gs_path is None
                if st.button("📂 Final Splat", key=f"gs_{d.name}", disabled=disabled_gs, use_container_width=True):
                    open_folder(gs_path.parent)
                    
            with c5:
                if st.button("🗑️ Delete", key=f"del_{d.name}", use_container_width=True):
                    try:
                        shutil.rmtree(d)
                        st.success(f"Deleted {d.name}")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Error deleting {d.name}: {e}")
            
            status_file = d / "pipeline_status.json"
            if status_file.exists():
                try:
                    data = json.loads(status_file.read_text(encoding="utf-8"))
                    summary = data.get("_pipeline_summary", {})
                    if summary:
                        with st.expander("Pipeline Summary", expanded=False):
                            # Format end_time
                            end_raw = summary.get("end_time")
                            end_display = end_raw
                            if end_raw:
                                try:
                                    # try common ISO formats
                                    for fmt in ("%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d %H:%M:%SZ", "%Y-%m-%dT%H:%M:%S"):
                                        try:
                                            dt = datetime.strptime(end_raw, fmt)
                                            end_display = dt.strftime("%Y-%m-%d %H:%M:%SZ")
                                            break
                                        except Exception:
                                            continue
                                except Exception:
                                    end_display = end_raw
                            if end_display:
                                st.write(f"**End Time:** {end_display}")

                            # Format duration as dd:HH:mm:ss (prefer explicit formatted field if present)
                            if "total_duration" in summary and summary.get("total_duration"):
                                dur_display = summary.get("total_duration")
                            else:
                                total_secs = int(round(summary.get("total_duration_s", 0)))
                                days = total_secs // 86400
                                rem = total_secs % 86400
                                hours = rem // 3600
                                rem = rem % 3600
                                minutes = rem // 60
                                seconds = rem % 60
                                dur_display = f"{days:02d}:{hours:02d}:{minutes:02d}:{seconds:02d}"
                            st.write(f"**Total Duration:** {dur_display}")

                            # keep numeric seconds for reference if present
                            if "total_duration_s" in summary:
                                try:
                                    st.write(f"**Total Duration (s):** {float(summary.get('total_duration_s')):.2f}")
                                except Exception:
                                    pass

                            for key in ("original_splats", "filtered_splats"):
                                if key in summary:
                                    display_key = key.replace("_", " ").capitalize()
                                    st.write(f"**{display_key}:** {summary.get(key)}")

                            if "methods_used" in summary:
                                st.write("**Methods used:**")
                                for m in summary.get("methods_used", []):
                                    step = m.get("step", "")
                                    method = m.get("method", "")
                                    st.write(f"- {step}: {method}")

                            overrides = summary.get("overrides_applied")
                            if overrides:
                                with st.expander("Overrides Applied", expanded=False):
                                    for step_name, vals in overrides.items():
                                        with st.expander(step_name, expanded=False):
                                            st.json(vals)
                except Exception as e:
                    st.error(f"Could not read pipeline_status.json for {d.name}: {e}")
            st.divider()
            
            

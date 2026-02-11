import streamlit as st
import sys
from pathlib import Path
import shutil
import time

st.set_page_config(page_title="Inputs", page_icon="📁", layout="wide")

# Trova project root risalendo finché non trova la cartella 'inputs' (fallback a 3 livelli)
current_file = Path(__file__).resolve()
project_root = current_file.parent
while not (project_root / "inputs").exists():
    if project_root == project_root.parent:
        project_root = current_file.parents[3]
        break
    project_root = project_root.parent

if str(project_root) not in sys.path:
    sys.path.append(str(project_root))

inputs_dir = project_root / "inputs"
if not inputs_dir.exists():
    inputs_dir.mkdir(parents=True, exist_ok=True)

st.title("📁 Inputs")

st.markdown(
    "Show the files available in the `inputs/` folder and let you upload new ones. You can upload photos or a single video that will be used as input for the pipeline."
    "The uploaded files will be saved in a subfolder of `inputs/` with the name you specify. If no name is given, a timestamp-based folder will be created. You can also choose to overwrite existing files or keep both by automatically renaming the new ones."
)

# Upload modal trigger
with st.expander("Upload files", expanded=False):
    st.write(
        "Load photos (multiple) or a single video. Uploaded files will be saved in a subfolder of `inputs/` with the name you specify."
    )
    photos = st.file_uploader(
        "Load Photos (jpg/png)",
        type=["jpg", "jpeg", "png"],
        accept_multiple_files=True,
        help="You can select multiple images.",
    )
    video = st.file_uploader(
        "Load a single video (mp4,mov,avi,mkv)",
        type=["mp4", "mov", "avi", "mkv"],
        accept_multiple_files=False,
        help="If you upload a video, do not upload photos in the same operation (optional).",
    )
    col1, col2 = st.columns(2)
    with col1:
        overwrite = st.checkbox("Overwrite existing files", value=False)
    with col2:
        folder_name = st.text_input(
            "Destination folder name (required if uploading files)", value=""
        ).strip()

    uploaded_count = len(photos or []) + (1 if video is not None else 0)
    if uploaded_count == 0:
        st.info("No file selected.")
    if st.button("Save uploaded files", type="primary"):
        if uploaded_count > 0 and folder_name == "":
            st.error(
                "Give a name for the destination folder to save the uploaded files."
            )
        else:
            safe_folder = (
                Path(folder_name).name
                if folder_name
                else time.strftime("%Y%m%d_%H%M%S")
            )
            target_dir = inputs_dir / safe_folder
            target_dir.mkdir(parents=True, exist_ok=True)
            saved = 0
            errors = []
            # Save photos
            for f in photos or []:
                try:
                    dest = target_dir / f.name
                    if dest.exists() and not overwrite:
                        base = dest.stem
                        ext = dest.suffix
                        i = 1
                        while (target_dir / f"{base}_{i}{ext}").exists():
                            i += 1
                        dest = target_dir / f"{base}_{i}{ext}"
                    with open(dest, "wb") as out:
                        out.write(f.getbuffer())
                    saved += 1
                except Exception as e:
                    errors.append(f"{f.name}: {e}")
            # Save video (single)
            if video is not None:
                try:
                    dest = target_dir / video.name
                    if dest.exists() and not overwrite:
                        base = dest.stem
                        ext = dest.suffix
                        i = 1
                        while (target_dir / f"{base}_{i}{ext}").exists():
                            i += 1
                        dest = target_dir / f"{base}_{i}{ext}"
                    with open(dest, "wb") as out:
                        out.write(video.getbuffer())
                    saved += 1
                except Exception as e:
                    errors.append(f"{video.name}: {e}")
            if saved:
                st.success(
                    f"Saved {saved} files in `{str(target_dir.relative_to(project_root))}`"
                )
            if errors:
                for e in errors:
                    st.error(e)
            st.rerun()
            
# Lista file e anteprime
st.subheader("inputs/ Contents")
# Escludi .gitkeep e mostra file organizzati per cartella
all_files = sorted(
    [p for p in inputs_dir.rglob("*") if p.is_file() and p.name != ".gitkeep"]
)

if not all_files:
    st.info("No file in `inputs/`.")
else:
    # Raggruppa file per cartella relativa sotto inputs_dir
    groups = {}
    for p in all_files:
        rel = p.relative_to(inputs_dir)
        folder = rel.parent.as_posix()  # "" per root
        groups.setdefault(folder, []).append(p)

    for folder, files in sorted(groups.items()):
        disp_folder = folder or "/"
        with st.expander(f"{disp_folder} — {len(files)} file", expanded=False):
            # mostra cartelle annidate: se folder contiene sottocartelle, mostrale come sottogruppi
            # raggruppiamo per subfolder immediato
            subgroups = {}
            for p in files:
                rel = p.relative_to(inputs_dir)
                parts = rel.parts
                if len(parts) > 1:
                    sub = parts[0]
                else:
                    sub = ""  # file nella cartella corrente
                subgroups.setdefault(sub, []).append(p)

            for sub, subfiles in sorted(subgroups.items()):
                if sub:
                    st.markdown(f"**{sub}/** — {len(subfiles)} file")
                cols = st.columns(3)
                i = 0
                for p in subfiles:
                    c = cols[i % 3]
                    i += 1
                    name = p.name
                    suffix = p.suffix.lower()
                    try:
                        if suffix in [".jpg", ".jpeg", ".png", ".webp"]:
                            with c:
                                st.image(str(p), caption=name, width=200)
                                st.write(name)
                                st.download_button(
                                    label="Download",
                                    data=p.read_bytes(),
                                    file_name=name,
                                    key=f"dl_{p}",
                                )
                        elif suffix in [".mp4", ".mov", ".avi", ".mkv", ".webm"]:
                            with c:
                                st.video(str(p))
                                st.write(name)
                                st.download_button(
                                    label="Download",
                                    data=p.read_bytes(),
                                    file_name=name,
                                    key=f"dl_{p}",
                                )
                        else:
                            with c:
                                st.write(name)
                                st.download_button(
                                    label="Download",
                                    data=p.read_bytes(),
                                    file_name=name,
                                    key=f"dl_{p}",
                                )
                    except Exception as e:
                        with c:
                            st.write(name)
                            st.error(f"Preview not available: {e}")

st.caption("Ricarica la pagina dopo l'upload per vedere i nuovi file se necessario.")

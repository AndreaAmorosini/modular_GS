import streamlit as st
import sys
from pathlib import Path
import shutil
import time
import os
import platform
import subprocess

st.set_page_config(
    page_title="Modular Gaussian Splatting - Inputs", page_icon="📁", layout="wide"
)


def open_folder(path="."):
    """Apre il file explorer gestendo correttamente i percorsi WSL -> Windows."""
    target_path = os.path.abspath(path)
    system = platform.system()

    if system == "Linux" and "microsoft" in platform.release().lower():
        try:
            win_path = (
                subprocess.check_output(["wslpath", "-w", target_path]).decode().strip()
            )
            subprocess.run(["explorer.exe", win_path])
            return
        except Exception:
            pass

    if system == "Windows":
        os.startfile(target_path)
    elif system == "Darwin":
        subprocess.run(["open", target_path])
    else:
        try:
            subprocess.run(["xdg-open", target_path])
        except Exception:
            st.info(f"Open folder: {target_path}")


def human_readable_size(nbytes: int) -> str:
    if nbytes < 1024:
        return f"{nbytes} B"
    for unit in ("KB", "MB", "GB", "TB"):
        nbytes /= 1024.0
        if nbytes < 1024.0:
            return f"{nbytes:.2f} {unit}"
    return f"{nbytes:.2f} PB"


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

# Upload area (unchanged)
with st.expander("Upload files", expanded=False):
    st.write(
        "Load photos (multiple) or a single video. Uploaded files will be saved in a subfolder of `inputs/` with the name you specify."
    )
    photos = st.file_uploader(
        "Load Photos (jpg/png)",
        type=["jpg", "jpeg", "png"],
        accept_multiple_files=True,
        help="You can select multiple images.",
        max_upload_size=3000,  # 3GB limit for photos
    )
    video = st.file_uploader(
        "Load a single video (mp4,mov,avi,mkv)",
        type=["mp4", "mov", "avi", "mkv"],
        accept_multiple_files=False,
        help="If you upload a video, do not upload photos in the same operation (optional).",
        max_upload_size=5000,  # 5GB limit for videos
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

st.subheader("inputs/ Contents")
all_files = sorted(
    [p for p in inputs_dir.rglob("*") if p.is_file() and p.name != ".gitkeep"]
)

if not all_files:
    st.info("No file in `inputs/`.")
else:
    groups = {}
    for p in all_files:
        rel = p.relative_to(inputs_dir)
        folder = rel.parent.as_posix()  # "" per root
        groups.setdefault(folder, []).append(p)

    image_exts = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tiff"}
    video_exts = {".mp4", ".mov", ".avi", ".mkv", ".webm"}

    for folder, files in sorted(groups.items()):
        disp_folder = folder or "/"
        folder_key = folder.replace("/", "__") if folder else "root"
        folder_path = inputs_dir / folder if folder else inputs_dir

        with st.expander(f"{disp_folder} — {len(files)} file", expanded=False):
            cols = st.columns([4, 1, 1])
            # Compute summary
            total_size = 0
            has_images = False
            has_videos = False
            for p in files:
                try:
                    total_size += p.stat().st_size
                    suf = p.suffix.lower()
                    if suf in image_exts:
                        has_images = True
                    if suf in video_exts:
                        has_videos = True
                except Exception:
                    continue

            if has_images and not has_videos:
                typ = "Images"
            elif has_videos and not has_images:
                typ = "Video"
            elif has_images and has_videos:
                typ = "Mixed (images & video)"
            else:
                typ = "Other"

            with cols[0]:
                st.write(f"**Type:** {typ}")
                st.write(f"**Size:** {human_readable_size(total_size)}")
                st.write(f"**Files:** {len(files)}")

            with cols[1]:
                if st.button(
                    "📂 Open Folder",
                    key=f"open_folder_{folder_key}",
                    use_container_width=True,
                ):
                    open_folder(folder_path)

            # Delete with confirmation
            confirm_key = f"confirm_delete_{folder_key}"
            if confirm_key not in st.session_state:
                st.session_state[confirm_key] = False

            with cols[2]:
                if not st.session_state[confirm_key]:
                    if st.button(
                        "🗑️ Delete", key=f"del_{folder_key}", use_container_width=True
                    ):
                        st.session_state[confirm_key] = True
                        st.rerun()
                else:
                    st.warning(f"Confirm delete `{disp_folder}`?")
                    c1, c2 = st.columns(2)
                    if c1.button("Confirm", key=f"del_confirm_{folder_key}"):
                        try:
                            if folder_path.exists():
                                if folder_path.is_dir():
                                    # If root (""), delete children not the inputs_dir itself
                                    if folder == "":
                                        for child in folder_path.iterdir():
                                            if child.is_dir():
                                                shutil.rmtree(child)
                                            else:
                                                child.unlink()
                                    else:
                                        shutil.rmtree(folder_path)
                                else:
                                    folder_path.unlink()
                            st.success(f"Deleted `{disp_folder}`")
                        except Exception as e:
                            st.error(f"Delete failed: {e}")
                        finally:
                            st.session_state[confirm_key] = False
                            st.rerun()
                    if c2.button("Cancel", key=f"del_cancel_{folder_key}"):
                        st.session_state[confirm_key] = False
                        st.rerun()

st.caption("Ricarica la pagina dopo l'upload per vedere i nuovi file se necessario.")

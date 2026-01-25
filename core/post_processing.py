import os
import numpy as np
from plyfile import PlyData, PlyElement


def filter_ply_by_opacity(
    input_path: str, output_path: str, threshold: float = 0.05, verbose: bool = True
) -> None:
    """
    Filter a .ply file to remove points based on an opacity threshold.
    """
    if not os.path.exists(input_path):
        if verbose:
            print(
                f"[Core] Warning: Input PLY not found at {input_path}. Skipping filter."
            )
        return

    if verbose:
        print(
            f"[Core] Post-processing: Filtering {input_path} (Threshold: {threshold})"
        )

    try:
        plydata = PlyData.read(input_path)
    except Exception as e:
        print(f"[Core] Error reading PLY: {e}")
        return

    if "vertex" not in plydata:
        print("[Core] Error: 'vertex' element not found in PLY.")
        return

    vertex = plydata["vertex"]

    if "opacity" not in vertex.data.dtype.names:
        print("[Core] Error: 'opacity' property not found in vertex data.")
        return

    opacities = vertex.data["opacity"]

    # Euristica: Rileva se le opacità sono Logit (possono essere <0 o >1) o Attivate [0,1]
    is_logit = (opacities.min() < 0.0) or (opacities.max() > 1.0)

    real_threshold = threshold
    if is_logit:
        # Conversione soglia da [0,1] a logit: logit(x) = log(x / (1 - x))
        t = np.clip(threshold, 1e-6, 1.0 - 1e-6)
        real_threshold = np.log(t / (1 - t))
        if verbose:
            print(
                f"Detected logits format. Converting threshold {threshold} -> {real_threshold:.4f}"
            )

    mask = opacities >= real_threshold
    new_data = vertex.data[mask]

    if verbose:
        before = len(vertex.data)
        after = len(new_data)
        print(f"Splats: {before} -> {after} (Removed: {before - after})")

    new_element = PlyElement.describe(new_data, "vertex")

    # Scrittura del nuovo file
    PlyData([new_element], text=plydata.text).write(output_path)

    if verbose:
        print(f"Filtered PLY saved to: {output_path}")

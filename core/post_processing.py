import os
import numpy as np
from plyfile import PlyData, PlyElement
import logging


def filter_ply_by_opacity(
    input_path: str, output_path: str, threshold: float = 0.05, verbose: bool = True, logger=None
) -> None:
    """
    Filter a .ply file to remove points based on an opacity threshold.
    """
    if not os.path.exists(input_path):
        if verbose:
            logging.warning(
                f"[Core] Warning: Input PLY not found at {input_path}. Skipping filter."
            )
        return

    if verbose:
        logging.info(
            f"[Core] Post-processing: Filtering {input_path} (Threshold: {threshold})"
        )

    try:
        plydata = PlyData.read(input_path)
    except Exception as e:
        logging.warning(f"[Core] Error reading PLY: {e}")
        return

    if "vertex" not in plydata:
        logging.error("[Core] Error: 'vertex' element not found in PLY.")
        return

    vertex = plydata["vertex"]

    if "opacity" not in vertex.data.dtype.names:
        logging.error("[Core] Error: 'opacity' property not found in vertex data.")
        return

    opacities = vertex.data["opacity"]

    # Check if it is Logit (<0 or >1) or  [0,1]
    is_logit = (opacities.min() < 0.0) or (opacities.max() > 1.0)

    real_threshold = threshold
    if is_logit:
        # Conversion from [0,1] to logit: logit(x) = log(x / (1 - x))
        t = np.clip(threshold, 1e-6, 1.0 - 1e-6)
        real_threshold = np.log(t / (1 - t))
        if verbose:
            logging.info(
                f"Detected logits format. Converting threshold {threshold} -> {real_threshold:.4f}"
            )

    mask = opacities >= real_threshold
    new_data = vertex.data[mask]

    if verbose:
        before = len(vertex.data)
        after = len(new_data)
        logger.info(f"Splats: {before} -> {after} (Removed: {before - after})")

    new_element = PlyElement.describe(new_data, "vertex")

    PlyData([new_element], text=plydata.text).write(output_path)

    if verbose:
        logger.info(f"Filtered PLY saved to: {output_path}")

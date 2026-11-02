"""
Server-side conversion of gaussian splat PLYs to the compact antimatter15
.splat format (32 bytes per splat), used by the web viewer for large files.

Layout per splat (little endian):
  bytes  0-11  position: 3 x float32
  bytes 12-23  scale:    3 x float32 (exp() of the PLY log-scale)
  bytes 24-27  color:    4 x uint8   (RGB from f_dc via SH C0, alpha = sigmoid(opacity))
  bytes 28-31  rotation: 4 x uint8   (normalized quaternion, (v * 128 + 128))
"""

import numpy as np
from pathlib import Path

SH_C0 = 0.28209479177387814
ROW_BYTES = 32


def convert_ply_to_splat(ply_path: str | Path, out_path: str | Path, logger=None) -> Path:
    """Convert a gaussian splat PLY to .splat. Raises ValueError if the PLY
    lacks the required properties. Returns the output path."""
    from plyfile import PlyData

    ply = PlyData.read(str(ply_path))
    if "vertex" not in ply:
        raise ValueError("PLY has no vertex element.")
    v = ply["vertex"].data
    names = v.dtype.names
    required = ["x", "y", "z", "f_dc_0", "f_dc_1", "f_dc_2", "opacity", "scale_0", "scale_1", "scale_2", "rot_0", "rot_1", "rot_2", "rot_3"]
    missing = [p for p in required if p not in names]
    if missing:
        raise ValueError(f"PLY is missing required properties: {', '.join(missing)}")

    n = len(v)
    out = np.zeros((n, ROW_BYTES), dtype=np.uint8)

    # position (float32)
    out_view = out.view(np.float32).reshape(n, 8)
    out_view[:, 0] = v["x"]
    out_view[:, 1] = v["y"]
    out_view[:, 2] = v["z"]

    # scale: exp() of the log-scale (float32)
    out_view[:, 3] = np.exp(v["scale_0"].astype(np.float64)).astype(np.float32)
    out_view[:, 4] = np.exp(v["scale_1"].astype(np.float64)).astype(np.float32)
    out_view[:, 5] = np.exp(v["scale_2"].astype(np.float64)).astype(np.float32)

    # color: SH DC -> rgb in [0,1] -> uint8
    rgb = 0.5 + SH_C0 * np.stack([v["f_dc_0"], v["f_dc_1"], v["f_dc_2"]], axis=1)
    rgb = np.clip(rgb, 0.0, 1.0)
    out[:, 24:27] = (rgb * 255.0 + 0.5).astype(np.uint8)

    # alpha: sigmoid of opacity
    alpha = 1.0 / (1.0 + np.exp(-v["opacity"].astype(np.float64)))
    out[:, 27] = np.clip(alpha * 255.0 + 0.5, 0, 255).astype(np.uint8)

    # rotation: normalize quaternion (rot_0 is the w component), map [-1,1] -> uint8
    q = np.stack([v["rot_0"], v["rot_1"], v["rot_2"], v["rot_3"]], axis=1).astype(np.float64)
    norms = np.linalg.norm(q, axis=1, keepdims=True)
    degenerate = norms[:, 0] < 1e-12
    q[degenerate] = [1.0, 0.0, 0.0, 0.0]
    norms[degenerate] = 1.0
    q = q / norms
    out[:, 28:32] = np.clip(q * 128.0 + 128.0, 0, 255).astype(np.uint8)

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out.tofile(str(out_path))

    if logger:
        logger.info(f"[ViewerCache] Converted {n:,} splats: {Path(ply_path).name} -> {out_path.name}")
    return out_path

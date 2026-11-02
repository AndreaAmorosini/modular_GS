"""
Convert COLMAP binary point clouds (points3D.bin) to binary PLY so the web
viewer can render sparse reconstructions of runs that only ship the .bin file.

points3D.bin layout (little endian):
    uint64   num_points
    per point:
        uint64  point3D_id
        double  x, y, z
        uint8   r, g, b
        double  error
        uint64  track_length
        track_length x (uint32 image_id, uint32 point2D_idx)
"""

import struct
from pathlib import Path


def convert_points3d_bin_to_ply(bin_path: str | Path, out_path: str | Path, logger=None) -> Path:
    """Convert points3D.bin to a binary PLY (x/y/z float32 + red/green/blue uchar).
    Returns the output path."""
    data = Path(bin_path).read_bytes()
    offset = 0
    (num_points,) = struct.unpack_from("<Q", data, offset)
    offset += 8

    positions = []
    colors = []
    for _ in range(num_points):
        offset += 8  # point3D_id (uint64), not needed for visualization
        x, y, z = struct.unpack_from("<ddd", data, offset)
        offset += 24
        r, g, b = data[offset], data[offset + 1], data[offset + 2]
        offset += 3
        offset += 8  # error (double)
        (track_len,) = struct.unpack_from("<Q", data, offset)
        offset += 8
        offset += track_len * 8  # track entries: (uint32 image_id, uint32 point2D_idx)
        positions.append((x, y, z))
        colors.append((r, g, b))

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    import numpy as np

    n = len(positions)
    positions_arr = np.asarray(positions, dtype="<f4")
    colors_arr = np.asarray(colors, dtype=np.uint8)
    vertex = np.empty(n, dtype=[("x", "<f4"), ("y", "<f4"), ("z", "<f4"),
                                ("red", "u1"), ("green", "u1"), ("blue", "u1")])
    vertex["x"] = positions_arr[:, 0]
    vertex["y"] = positions_arr[:, 1]
    vertex["z"] = positions_arr[:, 2]
    vertex["red"] = colors_arr[:, 0]
    vertex["green"] = colors_arr[:, 1]
    vertex["blue"] = colors_arr[:, 2]

    header = (
        "ply\n"
        "format binary_little_endian 1.0\n"
        f"element vertex {n}\n"
        "property float x\n"
        "property float y\n"
        "property float z\n"
        "property uchar red\n"
        "property uchar green\n"
        "property uchar blue\n"
        "end_header\n"
    )
    with open(out_path, "wb") as f:
        f.write(header.encode("ascii"))
        vertex.tofile(f)

    if logger:
        logger.info(f"[ViewerCache] Converted {len(positions):,} points: {Path(bin_path).name} -> {out_path.name}")
    return out_path

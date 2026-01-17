#!/usr/bin/env python3
print("Running Mast3r Glomap CLI")
import os
import sys
import shutil
import tempfile
import argparse
import torch
import numpy as np
import copy
import PIL.Image
from scipy.spatial.transform import Rotation
import matplotlib.pyplot as pl
import numpy as np

MAST3R_REPO_PATH = "submodules"
sys.path.insert(0, MAST3R_REPO_PATH)


import pycolmap
import trimesh

from mast3r.colmap.mapping import (
    kapture_import_image_folder_or_list,
    run_mast3r_matching,
    glomap_run_mapper,
)
from mast3r.demo import set_scenegraph_options
from mast3r.retrieval.processor import Retriever
from mast3r.image_pairs import make_pairs
import mast3r.utils.path_to_dust3r  # noqa

from dust3r.utils.image import load_images
from dust3r.viz import add_scene_cam, CAM_COLORS, OPENGL
from dust3r.demo import get_args_parser as dust3r_get_args_parser

from kapture.converter.colmap.database_extra import kapture_to_colmap
from kapture.converter.colmap.database import COLMAPDatabase
from mast3r.utils.misc import hash_md5


# --- Helper Classes ---
class GlomapRecon:
    def __init__(self, world_to_cam, intrinsics, points3d, imgs):
        self.world_to_cam = world_to_cam
        self.intrinsics = intrinsics
        self.points3d = points3d
        self.imgs = imgs


class GlomapReconState:
    def __init__(
        self, glomap_recon, should_delete=False, cache_dir=None, outfile_name=None
    ):
        self.glomap_recon = glomap_recon
        self.cache_dir = cache_dir
        self.outfile_name = outfile_name
        self.should_delete = should_delete

    def __del__(self):
        if not self.should_delete:
            return
        if self.cache_dir is not None and os.path.isdir(self.cache_dir):
            shutil.rmtree(self.cache_dir)
        self.cache_dir = None
        if self.outfile_name is not None and os.path.isfile(self.outfile_name):
            os.remove(self.outfile_name)
        self.outfile_name = None


# --- Modified Argument Parser ---
def get_args_parser():
    parser = dust3r_get_args_parser()
    # Add CLI arguments for input files, output directory and scene settings.
    parser.add_argument(
        "--input_files", required=True, help="List of input image files"
    )
    parser.add_argument(
        "--output_dir", type=str, required=True, help="Directory to save all outputs"
    )
    parser.add_argument(
        "--transparent_cams", action="store_true", help="Display transparent cameras"
    )
    parser.add_argument(
        "--cam_size", type=float, default=0.01, help="Camera size for visualization"
    )
    parser.add_argument(
        "--scenegraph_type",
        type=str,
        default="swin",
        choices=["complete", "swin", "logwin", "oneref", "retrieval"],
        help="Method to generate image pairs",
    )
    parser.add_argument(
        "--winsize", type=int, default=15, help="Window size for scenegraph"
    )
    parser.add_argument(
        "--win_cyclic", action="store_true", help="Use cyclic window for scenegraph"
    )
    parser.add_argument(
        "--refid", type=int, default=0, help="Reference id for scenegraph"
    )
    parser.add_argument(
        "--shared_intrinsics",
        action="store_true",
        help="Use shared intrinsics for all views",
    )
    # Retain existing arguments
    parser.add_argument(
        "--gradio_delete_cache", default=0, type=int, help="(Unused in CLI mode)"
    )
    parser.add_argument(
        "--glomap_bin", default="glomap", type=str, help="Path to the glomap binary"
    )
    parser.add_argument(
        "--retrieval_model", default=None, type=str, help="Path to the retrieval model"
    )
    # parser.add_argument('--mast3r_model_name', type=str, default="MASt3R_ViTLarge_BaseDecoder_512_catmlpdpt_metric",
    #                     choices=["MASt3R_ViTLarge_BaseDecoder_512_catmlpdpt_metric"])

    actions = parser._actions
    for action in actions:
        if action.dest == "model_name":
            action.choices = ["MASt3R_ViTLarge_BaseDecoder_512_catmlpdpt_metric"]
    # change defaults
    parser.prog = "mast3r demo"

    return parser


# --- Reconstruction Functions ---
def get_reconstructed_scene(
    glomap_bin,
    outdir,
    model,
    retrieval_model,
    device,
    silent,
    image_size,
    current_scene_state,
    filelist,
    transparent_cams,
    cam_size,
    scenegraph_type,
    winsize,
    win_cyclic,
    refid,
    shared_intrinsics,
    **kw,
):
    imgs = load_images(filelist, size=image_size, verbose=not silent)
    if len(imgs) == 1:
        imgs = [imgs[0], copy.deepcopy(imgs[0])]
        imgs[1]["idx"] = 1
        filelist = [filelist[0], filelist[0]]

    # Construct scenegraph string based on input parameters.
    scene_graph_params = [scenegraph_type]
    if scenegraph_type in ["swin", "logwin"]:
        scene_graph_params.append(str(winsize))
    elif scenegraph_type == "oneref":
        scene_graph_params.append(str(refid))
    elif scenegraph_type == "retrieval":
        scene_graph_params.append(str(winsize))
        scene_graph_params.append(str(refid))
    if scenegraph_type in ["swin", "logwin"] and not win_cyclic:
        scene_graph_params.append("noncyclic")
    scene_graph = "-".join(scene_graph_params)

    sim_matrix = None
    if "retrieval" in scenegraph_type:
        assert retrieval_model is not None
        retriever = Retriever(retrieval_model, backbone=model, device=device)
        with torch.no_grad():
            sim_matrix = retriever(filelist)

        del retriever
        torch.cuda.empty_cache()

    pairs = make_pairs(
        imgs,
        scene_graph=scene_graph,
        prefilter=None,
        symmetrize=True,
        sim_mat=sim_matrix,
    )

    # Use the provided output directory directly.
    cache_dir = outdir

    file_names = os.listdir(filelist)
    file_names.sort()
    filelist = [os.path.join(filelist, filename) for filename in file_names]

    root_path = os.path.commonpath(filelist)
    filelist_relpath = [
        os.path.relpath(filename, root_path).replace("\\", "/") for filename in filelist
    ]
    kdata = kapture_import_image_folder_or_list(
        (root_path, filelist_relpath), shared_intrinsics
    )
    image_pairs = [
        (filelist_relpath[img1["idx"]], filelist_relpath[img2["idx"]])
        for img1, img2 in pairs
    ]

    colmap_db_path = os.path.join(cache_dir, "colmap.db")
    if os.path.isfile(colmap_db_path):
        os.remove(colmap_db_path)
    os.makedirs(os.path.dirname(colmap_db_path), exist_ok=True)
    colmap_db = COLMAPDatabase.connect(colmap_db_path)
    try:
        kapture_to_colmap(
            kdata,
            root_path,
            tar_handler=None,
            database=colmap_db,
            keypoints_type=None,
            descriptors_type=None,
            export_two_view_geometry=False,
        )
        colmap_image_pairs = run_mast3r_matching(
            model,
            image_size,
            16,
            device,
            kdata,
            root_path,
            image_pairs,
            colmap_db,
            False,
            5,
            1.001,
            False,
            3,
        )
        colmap_db.close()
    except Exception as e:
        print(f"Error during matching: {e}")
        colmap_db.close()
        exit(1)

    if len(colmap_image_pairs) == 0:
        raise Exception("No matches were kept.")

    # Write pairs.txt and verify matches.
    pairs_txt = os.path.join(cache_dir, "pairs.txt")
    f = open(pairs_txt, "w")
    for image_path1, image_path2 in colmap_image_pairs:
        f.write("{} {}\n".format(image_path1, image_path2))
    f.close()
    pycolmap.verify_matches(colmap_db_path, pairs_txt)

    reconstruction_path = os.path.join(cache_dir, "colmap", "sparse")
    if os.path.isdir(reconstruction_path):
        shutil.rmtree(reconstruction_path)
    os.makedirs(reconstruction_path, exist_ok=True)
    glomap_run_mapper(glomap_bin, colmap_db_path, reconstruction_path, root_path)

    outfile_name = os.path.join(outdir, "scene.glb")
    output_recon = pycolmap.Reconstruction(os.path.join(reconstruction_path, "0"))
    print(output_recon.summary())

    colmap_world_to_cam = {}
    colmap_intrinsics = {}
    colmap_image_id_to_name = {}
    images = {}
    num_reg_images = output_recon.num_reg_images()
    for idx, (colmap_imgid, colmap_image) in enumerate(output_recon.images.items()):
        colmap_image_id_to_name[colmap_imgid] = colmap_image.name
        cam_from_world = colmap_image.cam_from_world
        if hasattr(cam_from_world, "matrix"):
            if callable(colmap_image.cam_from_world.matrix):
                colmap_world_to_cam[colmap_imgid] = colmap_image.cam_from_world.matrix()
            else:
                colmap_world_to_cam[colmap_imgid] = colmap_image.cam_from_world.matrix
        else:
            colmap_world_to_cam[colmap_imgid] = np.asarray(cam_from_world)
        camera = output_recon.cameras[colmap_image.camera_id]
        K = np.eye(3)
        K[0, 0] = camera.focal_length_x
        K[1, 1] = camera.focal_length_y
        K[0, 2] = camera.principal_point_x
        K[1, 2] = camera.principal_point_y
        colmap_intrinsics[colmap_imgid] = K
        with PIL.Image.open(os.path.join(root_path, colmap_image.name)) as im:
            images[colmap_imgid] = np.asarray(im)

        if idx + 1 == num_reg_images:
            break

    points3D = []
    num_points3D = output_recon.num_points3D()
    for idx, (pt3d_id, pts3d) in enumerate(output_recon.points3D.items()):
        points3D.append((pts3d.xyz, pts3d.color))
        if idx + 1 == num_points3D:
            break

    try:
        P = np.stack([p[0] for p in points3D], axis=0)  # [N,3]
        center = np.nanmean(P, axis=0)
        radii = np.linalg.norm(P - center, axis=1)
        r = np.percentile(radii[np.isfinite(radii)], 90) if radii.size else 1.0
        suggested_scale = float(1.0 / max(r, 1e-6))
        with open(os.path.join(outdir, "suggested_dataparser_scale.txt"), "w") as f:
            f.write(f"{suggested_scale}\n")
        print(
            f"[INFO] suggested dataparser scale ~= {suggested_scale:.6f} (p90 radius {r:.6f})"
        )
    except Exception as e:
        print(f"[WARN] could not compute suggested_dataparser_scale: {e}")

    # Correzzione dei path per compatibilita' con formato COLMAP per GaussianSplatting Graphdeco
    # TODO: Rendere questa parte dipendente da variabili nel TOML ed estrapolarla fuori da questo script

    input_path = os.path.join(outdir, "input")
    distorted_sparse_path = os.path.join(outdir, "distorted", "sparse", "0")
    colmap_sparse_path = os.path.join(outdir, "colmap", "sparse", "0")

    if not os.path.exists(input_path):
        images_path = os.path.join(outdir, "images")
        if os.path.isdir(images_path):
            # Symlink
            try:
                os.symlink(images_path, input_path)
                print(f"[INFO] created symlink {input_path} -> {images_path}")
            except OSError:
                shutil.copytree(images_path, input_path)
                print(f"[INFO] copied images/ to {input_path}")
        else:
            shutil.copytree(root_path, input_path)
            print(f"[INFO] copied images/ from {root_path} to {input_path}")

    if os.path.isdir(colmap_sparse_path) and not os.path.exists(distorted_sparse_path):
        os.makedirs(os.path.dirname(distorted_sparse_path), exist_ok=True)
        shutil.copytree(colmap_sparse_path, distorted_sparse_path)
        print(
            f"[INFO] copied COLMAP sparse model to {distorted_sparse_path} for GS compatibility"
        )
        # Look for colmap.db in outdir
        colmap_db_src = os.path.join(outdir, "colmap.db")
        # rename to database.db
        colmap_db_dst = os.path.join(outdir, "distorted", "database.db")
        if os.path.isfile(colmap_db_src):
            shutil.copy2(colmap_db_src, colmap_db_dst)
            print(
                f"[INFO] copied COLMAP database to {colmap_db_dst} for GS compatibility"
            )

    # gs_sparse_path = os.path.join(outdir, "sparse")
    # colmap_sparse_path = os.path.join(outdir, "colmap", "sparse")
    # if os.path.isdir(colmap_sparse_path) and not os.path.isdir(gs_sparse_path):
    #     shutil.copytree(colmap_sparse_path, gs_sparse_path)
    #     print(
    #         f"[INFO] copied COLMAP sparse model to {gs_sparse_path} for GS compatibility"
    #     )

    # images_path = os.path.join(outdir, "images")
    # if not os.path.isdir(images_path):
    #     print(f"[WARN] images/ folder not found at {images_path}")
    # else:
    #     print(f"[INFO] images/ folder exists with {len(os.listdir(images_path))} files")

    scene = GlomapRecon(colmap_world_to_cam, colmap_intrinsics, points3D, images)
    scene_state = GlomapReconState(scene, cache_dir, outfile_name)
    # outfile = get_3D_model_from_scene(silent, scene_state, transparent_cams, cam_size)
    return scene_state, outfile_name


def get_3D_model_from_scene(silent, scene_state, transparent_cams=False, cam_size=0.05):
    if scene_state is None:
        return None
    outfile = scene_state.outfile_name
    recon = scene_state.glomap_recon
    scene = trimesh.Scene()
    pts = np.stack([p[0] for p in recon.points3d], axis=0)
    col = np.stack([p[1] for p in recon.points3d], axis=0)
    pct = trimesh.PointCloud(pts, colors=col)
    scene.add_geometry(pct)

    cams2world = []
    for i, (id, pose_w2c_3x4) in enumerate(recon.world_to_cam.items()):
        intrinsics = recon.intrinsics[id]
        focal = (intrinsics[0, 0] + intrinsics[1, 1]) / 2.0
        camera_edge_color = CAM_COLORS[i % len(CAM_COLORS)]
        pose_w2c = np.eye(4)
        pose_w2c[:3, :] = pose_w2c_3x4
        pose_c2w = np.linalg.inv(pose_w2c)
        cams2world.append(pose_c2w)
        add_scene_cam(
            scene,
            pose_c2w,
            camera_edge_color,
            None if transparent_cams else recon.imgs[id],
            focal,
            imsize=recon.imgs[id].shape[1::-1],
            screen_width=cam_size,
        )

    rot = np.eye(4)
    rot[:3, :3] = Rotation.from_euler("y", np.deg2rad(180)).as_matrix()
    scene.apply_transform(np.linalg.inv(cams2world[0] @ OPENGL @ rot))
    if not silent:
        print("(exporting 3D scene to", outfile, ")")
    scene.export(file_obj=outfile)
    return outfile


# --- Main CLI Function ---
def main_cli():
    parser = get_args_parser()
    args = parser.parse_args()

    # Use the provided output_dir instead of a temporary directory.
    outdir = args.output_dir
    os.makedirs(outdir, exist_ok=True)

    # Load the model.
    if args.weights is not None:
        weights_path = args.weights
    else:
        weights_path = "naver/" + args.model_name

    from mast3r.model import AsymmetricMASt3R

    model = AsymmetricMASt3R.from_pretrained(weights_path).to(args.device)
    # The checkpoint tag is computed for consistency but is not used here for temporary caching.
    chkpt_tag = hash_md5(weights_path)

    print(f"Using model {args.model_name} with weights {weights_path}")
    print(f"Using device {args.device}")
    # Run the reconstruction pipeline.
    scene_state, outfile = get_reconstructed_scene(
        args.glomap_bin,
        outdir,
        model,
        args.retrieval_model,
        args.device,
        args.silent,
        args.image_size,
        current_scene_state=None,
        filelist=args.input_files,
        transparent_cams=args.transparent_cams,
        cam_size=args.cam_size,
        scenegraph_type=args.scenegraph_type,
        winsize=args.winsize,
        win_cyclic=args.win_cyclic,
        refid=args.refid,
        shared_intrinsics=args.shared_intrinsics,
    )


if __name__ == "__main__":
    main_cli()

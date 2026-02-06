import tomli
import os
import re
import json
import shutil
import struct
import cv2
from pathlib import Path
from typing import Dict, Optional, Any
from .context import PipelineContext
from .components.base import MethodRunner
from .post_processing import filter_ply_by_opacity
from .utils import RichLogger
import logging

_custom_logger = logging.getLogger("CustomRunLog")

class PipelineRunner:
    def __init__(self, pipeline_config_path: str, overrides: Optional[Dict[str, Any]] = None, verbose: bool = False):
        self.pipeline_path = Path(pipeline_config_path).resolve()
        self.base_path = self.pipeline_path.parent.parent 
        self.envs_base_dir = self.base_path / ".envs"
        self.logger = RichLogger(debug_enabled=verbose, verbose=verbose)
        self.verbose = verbose
        
        self.overrides = overrides or {}
        self.context = PipelineContext(self.base_path, overrides, verbose=verbose)

        with open(self.pipeline_path, "rb") as f:
            self.config = tomli.load(f)

    def run(self):
        title = self.config.get('title', 'Untitled')
        self.logger.info(f"=== Starting Pipeline: {title} ===")
        self.logger.info(f"Input File: {self.context.get('input_file', 'Not Set')}")
        self.logger.info(f"Output Dir: {self.context.get_output_dir()}")
        
        steps = self.config.get("steps", [])
        for i, step in enumerate(steps):
            self._run_step(step, i)

    def _run_step(self, step_config: Dict, index: int):
        step_name = step_config.get("name", f"Step_{index}")
        
        #Check Skip Logic
        completed_steps = self._load_completed_steps()
        if step_name in completed_steps:
            self.logger.warning(f"\nStep [{step_name}] previously completed. Skipping execution.")
            outputs = completed_steps[step_name]["outputs"]
        else:
            #Execution Logic
            method_rel_path = step_config.get("method")
            
            method_path = (self.base_path / method_rel_path).resolve()
            if not method_path.exists():
                 # Fallback
                 method_path = (self.base_path / "methods" / method_rel_path).resolve()

            self.logger.debug(f"\nOutput Step [{step_name}] ({method_path.stem})")

            with open(method_path, "rb") as f:
                method_config = tomli.load(f)

            env_path = self.envs_base_dir / method_path.stem
            
            manifest_path = env_path / "pixi.toml"
            shared_meta = env_path / "shared_env.json"
            if not manifest_path.exists() and not shared_meta.exists():
                 self.logger.error(f"Errore: Ambiente {method_path.stem} non installato.")
                 raise FileNotFoundError(f"Run 'python main.py methods install {method_path.stem}' first.")

            # Resolving inputs from TOML
            step_inputs = {}
            
            method_defaults = method_config.get("execution", {}).get("inputs", {})
            for key, val in method_defaults.items():
                step_inputs[key] = self.context.resolve(val)

            raw_inputs = step_config.get("inputs", {})
            for key, val in raw_inputs.items():
                # Resolve ex. "{{context.input_file}}"
                step_inputs[key] = self.context.resolve(val)
            
            self._adapt_input_structure(step_inputs)
                
            # Kwargs override
            raw_kwargs = step_config.get("kwargs", {})
            step_kwargs = {}
            
            for k, v in raw_kwargs.items():
                # Resolve TOML String variables (es. "{{context.iterations}}")
                step_kwargs[k] = self.context.resolve(v) if isinstance(v, str) else v
            
            # overrides for step (es. "Training.iterations")
            prefix = f"{step_name}."
            for ov_key, ov_val in self.overrides.items():
                if ov_key.startswith(prefix):
                    param_name = ov_key[len(prefix):]
                    step_kwargs[param_name] = ov_val
                    self.logger.debug(f"[Override] {step_name}.{param_name} = {ov_val}")
            
            # Setup Directory and Runner
            step_output_dir = self.context.get_output_dir() / step_name
            step_output_dir.mkdir(parents=True, exist_ok=True)
            
            runner = MethodRunner(method_config, env_path, self.base_path, verbose=self.verbose)
            
            with self.logger.spinner(f"Running Step [{step_name}]..."):
                outputs = runner.run(step_inputs, step_kwargs, step_output_dir)
            
            #Locate the final PLY file and put it in the root of the project
            search_dirs = {step_output_dir}
            for val in outputs.values():                    
                if isinstance(val, (str, Path)):
                    p = Path(val)
                    if p.exists() and p.is_dir():
                        search_dirs.add(p)
            target_ply = None
            highest_num = -1
            
            for sd in search_dirs:
                subdirs = [sd / "point_cloud", sd / "ply"]
                for subdir in subdirs:
                    if subdir.exists() and subdir.is_dir():
                        candidates = list(subdir.rglob("*.ply"))
                        for c in candidates:
                            #To avoid temp files
                            if "_filtered" in c.name:
                                continue
                            nums = re.findall(r"\d+", c.stem)
                            current_num = int(nums[-1]) if nums else 0
                            if target_ply is None or current_num > highest_num:
                                target_ply = c
                                highest_num = current_num
            
            #Global Post-Processing: Opacity Filter
            global_opts = self.config.get("global_options", {})
            opacity_threshold = global_opts.get("filter_opacity_threshold")

            if opacity_threshold is not None:                                    
                if target_ply:
                    self.logger.debug(f"[Auto-Filter] Selected PLY: '{target_ply.name}' (Iteration: {highest_num})")
                    filtered_path = target_ply.parent / f"{target_ply.stem}_filtered{target_ply.suffix}"
                    try:
                        filter_ply_by_opacity(str(target_ply), str(filtered_path), threshold=float(opacity_threshold), logger=self.logger)
                        
                        updated_existing = False
                        for key, val in outputs.items():
                            if isinstance(val, (str, Path)):
                                outputs[key] = filtered_path
                                updated_existing = True
                                
                        if not updated_existing:
                            outputs["filtered_ply"] = filtered_path
                            
                        if target_ply:
                            #Copy filtered_ply in output_dir
                            dest_path = self.context.get_output_dir() / "final_result" / "final_gaussian.ply"
                            dest_path.parent.mkdir(parents=True, exist_ok=True)
                            shutil.copy2(filtered_path, dest_path)
                            self.logger.info(f"[Output] Copied final PLY to '{dest_path.name}'")
                    except Exception as e:
                        self.logger.error(f"[Auto-Filter] Error filtering PLY: {e}")
                        if target_ply:
                            #Copy target_ply in output_dir
                            dest_path = self.context.get_output_dir() / "final_result" / target_ply.name
                            dest_path.parent.mkdir(parents=True, exist_ok=True)
                            shutil.copy2(target_ply, dest_path)
                            self.logger.info(f"[Output] Copied final PLY to '{dest_path.name}'")

            else:
                if target_ply:
                    #Copy target_ply in output_dir
                    dest_path = self.context.get_output_dir() / "final_result" / target_ply.name
                    dest_path.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(target_ply, dest_path)
                    self.logger.info(f"[Output] Copied final PLY to '{dest_path.name}'")

            # Save completion status
            self._save_step_completion(step_name, outputs)

        # Output Registration in Context
        # Format "StepName_OutputName" (es. Extraction_images_dir)
        for key, val in outputs.items():
            global_key = f"{step_name}_{key}"
            self.context.set(global_key, val)
        
        pipeline_mapping_key = step_config.get("output_key")
        primary_out_key = step_config.get("primary_output")
        
        if pipeline_mapping_key:
             val_to_save = None
             if primary_out_key and primary_out_key in outputs:
                 val_to_save = outputs[primary_out_key]
             elif outputs:
                 val_to_save = next(iter(outputs.values()))
             
             if val_to_save:
                 self.context.set(pipeline_mapping_key, val_to_save)
                 self.logger.debug(f"-> Context[{pipeline_mapping_key}] = {val_to_save}")

    def _adapt_input_structure(self, inputs: Dict[str, Any]):
        """
        Check for specific required folder structures from the TOML recipe
        """
        source_path_str = inputs.get("source_path")
        if not source_path_str:
            return
        
        source_path = Path(source_path_str)
        if not source_path.exists():
            return

        # Images Folder
        target_images_name = inputs.get("expected_input_images_folder")
        if target_images_name:
            target_img = source_path / target_images_name
            if not target_img.exists():
                # Cerca la cartella standard 'images'
                src_img = source_path / "images"
                if src_img.exists() and src_img.is_dir():
                    try:
                        if hasattr(os, "symlink"):
                            os.symlink(src_img, target_img)
                        else:
                            shutil.copytree(src_img, target_img)
                        self.logger.debug(f"[Auto-Adapt] Linked 'images' to '{target_images_name}'")
                    except Exception as e:
                        self.logger.error(f"[Auto-Adapt] Error linking images: {e}")

        # Sparse Model Folder
        target_colmap_rel = inputs.get("expected_colmap_folder")
        if target_colmap_rel:
            target_colmap = source_path / target_colmap_rel
            if not target_colmap.exists():
                src_colmap = source_path / "colmap" / "sparse" / "0"
                if src_colmap.exists():
                    try:
                        target_colmap.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copytree(src_colmap, target_colmap)
                        self.logger.debug(f"[Auto-Adapt] Copied sparse model to '{target_colmap_rel}'")
                    except Exception as e:
                        self.logger.error(f"[Auto-Adapt] Error copying sparse model: {e}")

        # COLMAP DB folder
        target_db_folder_rel = inputs.get("expected_db_folder")
        if target_db_folder_rel:
            target_db = source_path / target_db_folder_rel / "database.db"
            if not target_db.exists():
                src_db = source_path / "colmap.db"
                if src_db.exists():
                    try:
                        target_db.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(src_db, target_db)
                        self.logger.debug(f"[Auto-Adapt] Copied database to '{target_db_folder_rel}/database.db'")
                    except Exception as e:
                        self.logger.error(f"[Auto-Adapt] Error copying database: {e}")
        self._validate_and_fix_resolution(source_path, inputs)
        

    def _get_status_file(self) -> Path:
        return self.context.get_output_dir() / "pipeline_status.json"
    
    def _validate_and_fix_resolution(self, source_path: Path, inputs: Dict[str, Any]):
        img_folder_name = inputs.get("expected_input_images_folder")
        colmap_folder_rel = inputs.get("expected_colmap_folder")
        
        if not img_folder_name or not colmap_folder_rel:
            return
        
        img_dir = source_path / img_folder_name
        colmap_dir = source_path / colmap_folder_rel
        
        if not img_dir.exists() or not colmap_dir.exists():
            return

        target_w, target_h = self._get_colmap_dims(colmap_dir)
        if not target_w or not target_h:
            return
        
        extensions = {".jpg", ".png", ".jpeg", ".PNG", ".JPG", ".JPEG"}
        first_img_path = next((f for f in img_dir.iterdir() if f.is_file() and f.suffix in extensions), None)
        
        if not first_img_path:
            return
        
        img = cv2.imread(str(first_img_path))
        if img is None:
            return
        h, w = img.shape[:2]
        
        if w != target_w or h != target_h:
            self.logger.debug(f"[Auto-Fix] Resolution mismatch detected. Model: {target_w}x{target_h} Image: {w}x{h}")
            if img_dir.is_symlink():
                self.logger.debug(f"[Auto-Fix] Breaking symlink for {img_folder_name} to allow resizing...")
                link_target = os.readlink(img_dir)
                img_dir.unlink()
                if not os.path.isabs(link_target):
                    link_target = str((img_dir.parent / link_target).resolve())
                shutil.copytree(link_target, img_dir)
                
            self.logger.debug(f"[Auto-Fix] Resizing images to {target_w}x{target_h}...")
            for f in img_dir.iterdir():
                if f.is_file() and f.suffix in extensions:
                    img = cv2.imread(str(f))
                    if img is not None:
                        resized = cv2.resize(img, (target_w, target_h), interpolation=cv2.INTER_AREA)
                        cv2.imwrite(str(f), resized)
            self.logger.debug("[Auto-Fix] Resize Complete.")
            
    def _get_colmap_dims(self, model_path: Path):
        bin_path = model_path / "cameras.bin"
        if bin_path.exists():
            try:
                with open(bin_path, "rb") as f:
                    data = f.read(8)
                    if len(data) == 8 and struct.unpack("<Q", data)[0] > 0:
                        # Read first camera: id(4), model(4), w(8), h(8) = 24 bytes
                        data = f.read(24)
                        if len(data) == 24:
                            vals = struct.unpack("<iiQQ", data)
                            return int(vals[2]), int(vals[3])
            except Exception:
                pass
            
        txt_path = model_path / "cameras.txt"
        if txt_path.exists():
            try:
                with open(txt_path, "r") as f:
                    for line in f:
                        if line.startswith("#"): 
                            continue
                        parts = line.split()
                        if len(parts) >= 4:
                            return int(parts[2]), int(parts[3])
            except Exception:
                pass
        return None, None

    def _load_completed_steps(self) -> Dict[str, Any]:
        status_file = self._get_status_file()
        if status_file.exists():
            try:
                with open(status_file, "r") as f:
                    return json.load(f)
            except Exception as e:
                self.logger.error(f"[ERROR] Could not load status file: {e}")
        return {}

    def _save_step_completion(self, step_name: str, outputs: Dict[str, Any]):
        # Convert Path objects to strings for JSON serialization
        serializable_outputs = {}
        for k, v in outputs.items():
            if isinstance(v, Path):
                serializable_outputs[k] = str(v)
            else:
                serializable_outputs[k] = v
        
        status = self._load_completed_steps()
        status[step_name] = {"outputs": serializable_outputs}
        
        status_file = self._get_status_file()
        try:
            with open(status_file, "w") as f:
                json.dump(status, f, indent=4)
        except Exception as e:
            self.logger.error(f"[ERROR] Could not save status file: {e}")

    def print_help(self):
        """Print all the configurable parameter of the method"""
        self.logger.info(f"\n=== Pipeline: {self.config.get('title', 'Untitled')} ===")
        desc = self.config.get('description', '').strip()
        if desc:
            print(f"{desc}\n")
        
        self.logger.info("Context Variables (use --set VAR=VAL)")
        context_vars = set()
        
        def scan_val(v):
            if isinstance(v, str):
                matches = re.findall(r"\{\{context\.([\w_]+)\}\}", v)
                context_vars.update(matches)
        
        def scan_recursive(d):
            if isinstance(d, dict):
                for v in d.values():
                    scan_recursive(v)
            elif isinstance(d, list):
                for v in d:
                    scan_recursive(v)
            else:
                scan_val(d)

        steps = self.config.get("steps", [])
        for step in steps:
            scan_recursive(step.get("inputs", {}))
            scan_recursive(step.get("kwargs", {}))
            
        if context_vars:
            for var in sorted(context_vars):
                note = ""
                if var == "input_file": note = " (or use --input)"
                if var == "output_dir": note = " (or use --output)"
                self.logger.info(f"  • {var}{note}")
        else:
            self.logger.warning("(No explicit context variables detected)")

        self.logger.info("\nStep Parameters (use --set StepName.Param=VAL)")
        for i, step in enumerate(steps):
            step_name = step.get("name", f"Step_{i}")
            kwargs = step.get("kwargs", {})
            if kwargs:
                self.logger.info(f"  [{step_name}]")
                for k, v in kwargs.items():
                    val_str = f"'{v}'" if isinstance(v, str) else str(v)
                    self.logger.info(f"    • {k} = {val_str}")
        self.logger.info("\n")
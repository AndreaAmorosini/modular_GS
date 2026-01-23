import tomli
import os
import re
import json
import shutil
from pathlib import Path
from typing import Dict, Optional, Any
from .context import PipelineContext
from .components.base import MethodRunner
# from .installer import MethodInstaller # Opzionale se vuoi auto-installare

class PipelineRunner:
    def __init__(self, pipeline_config_path: str, overrides: Optional[Dict[str, Any]] = None):
        self.pipeline_path = Path(pipeline_config_path).resolve()
        # Assumiamo che la pipeline sia in project_root/pipelines/file.toml
        self.base_path = self.pipeline_path.parent.parent 
        self.envs_base_dir = self.base_path / ".envs"
        
        self.overrides = overrides or {}
        # Inizializza contesto PASSANDO gli overrides subito
        self.context = PipelineContext(self.base_path, overrides)

        with open(self.pipeline_path, "rb") as f:
            self.config = tomli.load(f)

    def run(self):
        title = self.config.get('title', 'Untitled')
        print(f"=== Starting Pipeline: {title} ===")
        print(f"Input File: {self.context.get('input_file', 'Not Set')}")
        print(f"Output Dir: {self.context.get_output_dir()}")
        
        steps = self.config.get("steps", [])
        for i, step in enumerate(steps):
            self._run_step(step, i)

    def _run_step(self, step_config: Dict, index: int):
        step_name = step_config.get("name", f"Step_{index}")
        
        # --- Check Skip Logic ---
        completed_steps = self._load_completed_steps()
        if step_name in completed_steps:
            print(f"\n--- Step [{step_name}] previously completed. Skipping execution. ---")
            outputs = completed_steps[step_name]["outputs"]
        else:
            # --- Execution Logic ---
            method_rel_path = step_config.get("method")
            
            method_path = (self.base_path / method_rel_path).resolve()
            if not method_path.exists():
                 # Fallback per path relativi a methods/
                 method_path = (self.base_path / "methods" / method_rel_path).resolve()

            print(f"\n--- Output Step [{step_name}] ({method_path.stem}) ---")

            with open(method_path, "rb") as f:
                method_config = tomli.load(f)

            env_path = self.envs_base_dir / method_path.stem

            # Check veloce esistenza env
            if not (env_path / "pixi.toml").exists():
                 print(f"Errore: Ambiente {method_path.stem} non installato.")
                 raise FileNotFoundError(f"Run 'python main.py methods install {method_path.stem}' first.")

            # 1. Risoluzione Inputs: pipeline toml -> valori reali
            step_inputs = {}
            
            # Carica default dal TOML del metodo (es. parametri di adattamento folder)
            method_defaults = method_config.get("execution", {}).get("inputs", {})
            for key, val in method_defaults.items():
                step_inputs[key] = self.context.resolve(val)

            raw_inputs = step_config.get("inputs", {})
            for key, val in raw_inputs.items():
                # Risolve es. "{{context.input_file}}"
                step_inputs[key] = self.context.resolve(val)
            
            # Adatta la struttura della cartella di input se richiesto dal metodo (es. Taming 3DGS)
            self._adapt_input_structure(step_inputs)
                
            # Gestione Kwargs con risoluzione e overrides
            raw_kwargs = step_config.get("kwargs", {})
            step_kwargs = {}
            
            for k, v in raw_kwargs.items():
                # Risolvi variabili nel TOML se sono stringhe (es. "{{context.iterations}}")
                step_kwargs[k] = self.context.resolve(v) if isinstance(v, str) else v
            
            # Applica overrides specifici per step (es. "Training.iterations")
            prefix = f"{step_name}."
            for ov_key, ov_val in self.overrides.items():
                if ov_key.startswith(prefix):
                    param_name = ov_key[len(prefix):]
                    step_kwargs[param_name] = ov_val
                    print(f"   [Override] {step_name}.{param_name} = {ov_val}")
            
            # 2. Setup Directory e Runner
            step_output_dir = self.context.get_output_dir() / step_name
            step_output_dir.mkdir(parents=True, exist_ok=True)
            
            runner = MethodRunner(method_config, env_path, self.base_path)
            
            # 3. Esecuzione (MethodRunner usa Inputs reali per comporre il comando)
            outputs = runner.run(step_inputs, step_kwargs, step_output_dir)
            
            # Save completion status
            self._save_step_completion(step_name, outputs)

        # 4. Registrazione Output nel Contesto
        # Li salviamo come "NomeStep_NomeOutput" (es. Extraction_images_dir)
        for key, val in outputs.items():
            global_key = f"{step_name}_{key}"
            self.context.set(global_key, val)
        
        # Supporto alias espliciti (output_key legacy o primary_output)
        pipeline_mapping_key = step_config.get("output_key")
        primary_out_key = step_config.get("primary_output")
        
        if pipeline_mapping_key:
             # Se la pipeline dice 'salva l'output principale in sfm_ready_path'
             # Cerchiamo di capire qual è l'output principale
             val_to_save = None
             if primary_out_key and primary_out_key in outputs:
                 val_to_save = outputs[primary_out_key]
             elif outputs:
                 val_to_save = next(iter(outputs.values()))
             
             if val_to_save:
                 self.context.set(pipeline_mapping_key, val_to_save)
                 print(f"   -> Context[{pipeline_mapping_key}] = {val_to_save}")

    def _adapt_input_structure(self, inputs: Dict[str, Any]):
        """
        Controlla se sono richiesti path specifici per l'input e riorganizza 
        la cartella source_path di conseguenza (es. creando symlink 'input' o copiando 'distorted').
        """
        source_path_str = inputs.get("source_path")
        if not source_path_str:
            return
        
        source_path = Path(source_path_str)
        if not source_path.exists():
            return

        # 1. Gestione Immagini (es. expected_input_images_folder="input")
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
                        print(f"   [Auto-Adapt] Linked 'images' to '{target_images_name}'")
                    except Exception as e:
                        print(f"   [Auto-Adapt] Error linking images: {e}")

        # 2. Gestione Sparse Model (es. expected_colmap_folder="distorted/sparse/0")
        target_colmap_rel = inputs.get("expected_colmap_folder")
        if target_colmap_rel:
            target_colmap = source_path / target_colmap_rel
            if not target_colmap.exists():
                src_colmap = source_path / "colmap" / "sparse" / "0"
                if src_colmap.exists():
                    try:
                        target_colmap.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copytree(src_colmap, target_colmap)
                        print(f"   [Auto-Adapt] Copied sparse model to '{target_colmap_rel}'")
                    except Exception as e:
                        print(f"   [Auto-Adapt] Error copying sparse model: {e}")

        # 3. Gestione Database (es. expected_db_folder="distorted")
        target_db_folder_rel = inputs.get("expected_db_folder")
        if target_db_folder_rel:
            target_db = source_path / target_db_folder_rel / "database.db"
            if not target_db.exists():
                src_db = source_path / "colmap.db"
                if src_db.exists():
                    try:
                        target_db.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(src_db, target_db)
                        print(f"   [Auto-Adapt] Copied database to '{target_db_folder_rel}/database.db'")
                    except Exception as e:
                        print(f"   [Auto-Adapt] Error copying database: {e}")

    def _get_status_file(self) -> Path:
        return self.context.get_output_dir() / "pipeline_status.json"

    def _load_completed_steps(self) -> Dict[str, Any]:
        status_file = self._get_status_file()
        if status_file.exists():
            try:
                with open(status_file, "r") as f:
                    return json.load(f)
            except Exception as e:
                print(f"[WARN] Could not load status file: {e}")
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
            print(f"[WARN] Could not save status file: {e}")

    def print_help(self):
        """Stampa i parametri configurabili della pipeline."""
        print(f"\n=== Pipeline: {self.config.get('title', 'Untitled')} ===")
        desc = self.config.get('description', '').strip()
        if desc:
            print(f"{desc}\n")
        
        print("--- 1. Context Variables (use --set VAR=VAL) ---")
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
                print(f"  • {var}{note}")
        else:
            print("  (No explicit context variables detected)")

        print("\n--- 2. Step Parameters (use --set StepName.Param=VAL) ---")
        for i, step in enumerate(steps):
            step_name = step.get("name", f"Step_{i}")
            kwargs = step.get("kwargs", {})
            if kwargs:
                print(f"  [{step_name}]")
                for k, v in kwargs.items():
                    val_str = f"'{v}'" if isinstance(v, str) else str(v)
                    print(f"    • {k} = {val_str}")
        print("\n")
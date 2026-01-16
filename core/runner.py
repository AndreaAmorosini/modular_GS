import tomli
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
        raw_inputs = step_config.get("inputs", {})
        for key, val in raw_inputs.items():
            # Risolve es. "{{context.input_file}}"
            step_inputs[key] = self.context.resolve(val)
            
        step_kwargs = step_config.get("kwargs", {})
        
        # 2. Setup Directory e Runner
        step_output_dir = self.context.get_output_dir() / step_name
        step_output_dir.mkdir(parents=True, exist_ok=True)
        
        runner = MethodRunner(method_config, env_path, self.base_path)
        
        # 3. Esecuzione (MethodRunner usa Inputs reali per comporre il comando)
        outputs = runner.run(step_inputs, step_kwargs, step_output_dir)

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
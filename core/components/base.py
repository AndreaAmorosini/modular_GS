import subprocess
import os
import jinja2
from pathlib import Path
from typing import Dict, Any, Optional
from core.utils import get_or_download_pixi
import json

class MethodRunner:
    def __init__(self, method_config: dict, env_path: Path, base_path: Path):
        self.config = method_config
        self.title = method_config.get("title", "Unknown Method")
        self.method_id = env_path.name
        self.env_path = env_path
        self.base_path = base_path
        self.project_root = base_path # Alias
        self.pixi_exe = get_or_download_pixi(base_path)
        
        # Vendor path: vendor/specified_path
        self.vendor_dir = base_path / "vendor"

    def run(self, inputs: Dict[str, Any], kwargs: Dict[str, Any], step_output_dir: Path) -> Dict[str, str]:
        """
        Esegue il comando del metodo.
        
        Args:
            inputs: Dizionario input risolti (es. {"video": "/path/to/vid.mp4"})
            kwargs: Parametri opzionali (es. {"threshold": 0.5})
            step_output_dir: Directory dove questo step dovrebbe scrivere i suoi file
            
        Returns:
            Dict[str, str]: Mappa degli output generati {"key": "/abs/path"}
        """
        print(f" Running Method: {self.title} ")
        
        exec_config = self.config.get("execution", {})
        raw_cmd = exec_config.get("command")
        
        if not raw_cmd:
             print("Warning: No execution command found. Skipping.")
             return {}

        # Prepara Variabili Template
        # Le variabili disponibili nel template Jinja del comando
        template_vars = {
            "inputs": inputs,
            "kwargs": kwargs,
            "step_output_dir": str(step_output_dir), # Fondamentale
            "project_root": str(self.project_root),
            "method_vendor_dir": str(self.vendor_dir),
            "outputs": {} 
        }

        # Risolvi Output Paths
        # Questo permette di usare {{outputs.images}} nel comando.
        output_defs = exec_config.get("outputs", {})
        resolved_outputs = {}
        
        for out_key, out_templ in output_defs.items():
            path_str = self._render_string(out_templ, template_vars)
            abs_path = Path(path_str).resolve()
            resolved_outputs[out_key] = str(abs_path)
            
            if not abs_path.suffix:
                 abs_path.mkdir(parents=True, exist_ok=True)
            else:
                 abs_path.parent.mkdir(parents=True, exist_ok=True)

        template_vars["outputs"] = resolved_outputs
        
        final_cmd = self._render_string(raw_cmd, template_vars)
        print(f"Payload comando:\n{final_cmd.strip()}")
        
        manifest_path = self.env_path / "pixi.toml"
        env_name = None
        
        if not manifest_path.exists():
            shared_meta = self.env_path / "shared_env.json"
            if shared_meta.exists():
                with open(shared_meta, "r") as f:
                    meta = json.load(f)
                manifest_path = Path(meta.get("manifest_path", ""))
                env_name = meta.get("env_name", None)
                
        if not manifest_path.exists():
            raise FileNotFoundError(f"Pixi environment not found at {manifest_path}. Run install first.")

        cmd_list = [
            str(self.pixi_exe),
            "run",
            "--manifest-path", str(manifest_path),
        ]
        
        if env_name:
            cmd_list += ["-e", env_name]
            
        cmd_list += ["bash", "-c", final_cmd]
        
        try:
            subprocess.check_call(
                cmd_list,
                cwd=self.project_root,
                env=os.environ
            )
        except subprocess.CalledProcessError as e:
            print(f"Execution failed with output: {e}")
            raise e
            
        return resolved_outputs

    def _render_string(self, template_str: str, context: dict) -> str:
        """Helper per renderizzare stringa Jinja2."""
        return jinja2.Template(template_str).render(**context)
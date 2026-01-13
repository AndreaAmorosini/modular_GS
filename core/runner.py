import tomli
import os
from pathlib import Path
from typing import List, Dict
from .components.base import MethodRunner  # <--- AGGIORNATO (era CommandRunnerStep)
from .context import PipelineContext
from .installer import MethodInstaller


class PipelineRunner:
    def __init__(self, pipeline_config_path: str):
        self.pipeline_path = Path(pipeline_config_path)
        self.base_path = self.pipeline_path.parent.parent
        self.context = PipelineContext(self.base_path)

        with open(self.pipeline_path, "rb") as f:
            self.config = tomli.load(f)

    def run(self):
        print(f"Starting pipeline: {self.config.get('title', 'Untitled')}")

        steps = self.config.get("steps", [])
        for step in steps:
            self._run_step(step)

    def _run_step(self, step_config: Dict):
        step_name = step_config.get("name")
        method_path = self.base_path / step_config.get("method")

        print(f"\n--- Step: {step_name} ---")

        if not method_path.exists():
            raise FileNotFoundError(f"Method file not found: {method_path}")

        with open(method_path, "rb") as f:
            method_config = tomli.load(f)

        # Configura output directory per lo step
        # Se lo step definisce output_dir nel TOML della pipeline, usalo
        # Altrimenti usa defaults
        if "output_dir" in step_config:
            self.context.set_output_dir(step_config["output_dir"])

        # 1. Installazione (Dichiarativa via Pixi)
        # Usa env_path basato sul nome del metodo per evitare duplicati
        method_name = method_config.get("title", "unknown").replace(" ", "_").lower()
        env_path = self.base_path / "envs" / method_name

        installer = MethodInstaller(method_config, self.base_path)
        if not installer.is_installed(env_path):
            installer.install(env_path)

        # 2. Esecuzione
        # Uniamo la config della pipeline con quella del metodo
        # Le variabili definite nello step della pipeline (es. output_dir) sovrascrivono i default
        runner = MethodRunner(method_config, env_path, self.base_path)

        # Passiamo i parametri specifici dello step al context/runner se necessario
        # (Qui potresti estendere context per accettare override temporanei)

        runner.run(self.context)

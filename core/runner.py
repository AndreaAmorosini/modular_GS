import toml
import logging
from pathlib import Path
from .context import PipelineContext
from .validation import Validator
from .components.base import CommandRunnerStep


class PipelineRunner:
    """Orchestra l'esecuzione della pipeline."""

    def __init__(self, config_path: Path, methods_dir: Path, override_args: dict = None):
        self.config = toml.load(config_path)
        self.context = PipelineContext(self.config.get("context", {}), override_args=override_args)
        self.validator = Validator(methods_dir)

        pipeline_config = self.config.get("pipeline", {})
        self.step_order = pipeline_config.get("steps", [])
        self.steps_config = self.config.get("step", {})
        self.logger = logging.getLogger("PipelineRunner")
        self.logger.info(f"Pipeline '{pipeline_config.get('name')}' caricata.")

    def execute(self):
        total_steps = len(self.step_order)
        for i, step_name in enumerate(self.step_order):
            step_config = self.steps_config.get(step_name)
            method_name = step_config.get("method")
            self.logger.info(
                f"\n--- [Step {i + 1}/{total_steps}] Esecuzione: {step_name} (Metodo: {method_name}) ---"
            )

            try:
                _, method_config = self.validator.find_method_manifest(method_name)
                step_instance = CommandRunnerStep(
                    self.context, step_config, method_config
                )
                step_instance.run()
            except Exception as e:
                self.logger.critical(
                    f"Step '{step_name}' (Metodo '{method_name}') fallito: {e}"
                )
                raise
        self.logger.info("--- Esecuzione pipeline completata. ---")

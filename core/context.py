import logging
import jinja2
from pathlib import Path
from typing import Dict, Any, Optional
from .utils import RichLogger

class PipelineContext:
    """
    Manage the state and data passing between steps of the pipeline.
    And resolve Jinja templates for variables.
    """

    def __init__(self, project_root: Path, override_args: Optional[Dict[str, Any]] = None, verbose: bool = False):
        self.logger = RichLogger(debug_enabled=verbose, verbose=verbose)
        self.data = {"project_root": str(project_root)}
        
        # Gestione sicura di override_args (evita NoneType error)
        args = override_args or {}

        if args.get("output_dir"):
            self.data["output_dir"] = str(args["output_dir"])
            self.output_dir = Path(args["output_dir"]).expanduser().resolve()
        
        if args.get("input_file"):
            self.data["input_file"] = str(args["input_file"])
            
        if args.get("restart"):
            self.data["restart"] = True
            
        self.step_dirs = {}
        
        # Se non specificato, usa default
        if "output_dir" not in self.data:
            self.output_dir = project_root / "outputs" / "default_run"
            self.data["output_dir"] = str(self.output_dir)

        self._setup_dirs()

    def _setup_dirs(self):
        """Setup of the outputs dirs"""
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.logger.debug(f"Pipeline output directory: {self.output_dir}")
        
        #Check on status file
        restart = self.data.get("restart", False)
        if (self.output_dir / "pipeline_status.json").exists() and not restart:
            self.logger.debug("Found pipeline_status.json.")
            return
        
        if any(self.output_dir.iterdir()):
            for item in self.output_dir.iterdir():
                if item.is_dir():
                    import shutil
                    shutil.rmtree(item)
                else:
                    item.unlink()
            self.logger.debug(f"Cleaned output directory: {self.output_dir}")

    def resolve(self, template_str: Any) -> Any:
        """
        Resolve a Jinja variable in a string.
        Es: "{{context.input_file}}" -> "/path/to/video.mp4"
        """
        if not isinstance(template_str, str) or "{{" not in template_str:
            return template_str
        
        # Expose 'context' as namespace to access the variables in the TOML
        render_ctx = {"context": self.data}
        try:
            return jinja2.Template(template_str).render(**render_ctx)
        except Exception as e:
            self.logger.warning(f"Error resolving template '{template_str}': {e}")
            return template_str
    
    def get_output_dir(self) -> Path:
        return self.output_dir

    def set(self, key: str, value: Any):
        """Save a value in the global context"""
        self.data[key] = value
        self.logger.debug(f"Context set: {key} = {value}")
        
    def get(self, key: str, default=None):
        return self.data.get(key, default)
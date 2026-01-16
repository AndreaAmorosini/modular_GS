import logging
import jinja2
from pathlib import Path
from typing import Dict, Any, Optional

class PipelineContext:
    """
    Gestisce lo stato e il passaggio di dati tra gli step della pipeline.
    Si occupa anche di risolvere i template Jinja delle variabili.
    """

    def __init__(self, project_root: Path, override_args: Optional[Dict[str, Any]] = None):
        self.logger = logging.getLogger("PipelineContext")
        self.data = {"project_root": str(project_root)}
        
        # Gestione sicura di override_args (evita NoneType error)
        args = override_args or {}

        if args.get("output_dir"):
            self.data["output_dir"] = str(args["output_dir"])
            self.output_dir = Path(args["output_dir"]).expanduser().resolve()
        
        if args.get("input_file"):
            self.data["input_file"] = str(args["input_file"])
            
        self.step_dirs = {}
        
        # Se non specificato, usa default
        if "output_dir" not in self.data:
            self.output_dir = project_root / "outputs" / "default_run"
            self.data["output_dir"] = str(self.output_dir)

        self._setup_dirs()

    def _setup_dirs(self):
        """Crea la directory fisica di output."""
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.logger.info(f"Pipeline output directory: {self.output_dir}")
        
        #Controlla se ci sono folder o file all'interno del percorso di output
        if any(self.output_dir.iterdir()):
            #Elimina tutti i file e le cartelle all'interno della directory di output
            for item in self.output_dir.iterdir():
                if item.is_dir():
                    import shutil
                    shutil.rmtree(item)
                else:
                    item.unlink()
            self.logger.info(f"Pulita la directory di output: {self.output_dir}")

    def resolve(self, template_str: Any) -> Any:
        """
        Risolve una stringa template Jinja2 usando i dati del contesto.
        Es: "{{context.input_file}}" -> "/path/to/video.mp4"
        """
        if not isinstance(template_str, str) or "{{" not in template_str:
            return template_str
        
        # Esponiamo 'context' come namespace per accedere alle variabili nei TOML
        render_ctx = {"context": self.data}
        try:
            return jinja2.Template(template_str).render(**render_ctx)
        except Exception as e:
            self.logger.warning(f"Errore risoluzione template '{template_str}': {e}")
            return template_str
    
    def get_output_dir(self) -> Path:
        return self.output_dir

    def set(self, key: str, value: Any):
        """Salva un valore nel contesto globale."""
        self.data[key] = value
        self.logger.debug(f"Context set: {key} = {value}")
        
    def get(self, key: str, default=None):
        return self.data.get(key, default)
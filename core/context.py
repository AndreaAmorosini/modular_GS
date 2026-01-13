import logging
from pathlib import Path


class PipelineContext:
    """
    Gestisce lo stato e il passaggio di dati tra gli step della pipeline.
    Si occupa anche di creare le directory di output in modo strutturato.
    """

    def __init__(self, initial_config: dict, override_args: dict = None):
        self.data = initial_config
        if override_args["output_dir"]:
            self.data["output_dir"] = override_args["output_dir"]
        if override_args["input_file"]:
            self.data["input_file"] = override_args["input_file"]
        self.output_dir = Path(self.data.get("output_dir", "outputs/default_run"))
        self.logger = logging.getLogger("PipelineContext")
        self.step_dirs = {}
        self._setup_dirs()

    # def _setup_dirs(self):
    #     """Crea la directory di output principale."""
    #     self.output_dir.mkdir(parents=True, exist_ok=True)
    #     self.logger.debug(
    #         f"Directory di output principale: {self.output_dir.resolve()}"
    #     )
    def _setup_dirs(self):
        """
        Imposta la directory di output principale.
        Dà priorità alla directory fornita dall'utente tramite CLI.
        Se non fornita, crea una directory di default nel progetto.
        """
        user_output_dir = self.data.get("output_dir")

        if user_output_dir:
            # Se l'utente ha specificato una directory, usa quella.
            # Espande il tilde (~) e la rende un percorso assoluto.
            self.output_dir = Path(user_output_dir).expanduser().resolve()
            self.logger.info(
                f"Utilizzo della directory di output specificata dall'utente: {self.output_dir}"
            )
        else:
            # Altrimenti, crea una directory di default.
            project_root = Path(self.data.get("project_root", "."))
            run_name = "default_run"  # Potremmo renderlo dinamico in futuro
            self.output_dir = project_root / "outputs" / run_name
            self.logger.info(
                f"Nessuna directory di output specificata. Utilizzo del default: {self.output_dir}"
            )

        # Crea la directory di output principale se non esiste.
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # Aggiorna il contesto con il percorso assoluto e finale,
        # così che sia disponibile per gli step successivi.
        self.set("output_dir", str(self.output_dir))

        self.logger.debug(
            f"Directory di output principale impostata su: {self.get('output_dir')}"
        )

    def get(self, key: str, default=None):
        """Ottiene un valore dal contesto."""
        return self.data.get(key, default)

    def set(self, key: str, value):
        """Imposta un valore nel contesto."""
        self.logger.debug(f"Contesto aggiornato: {key} = {value}")
        self.data[key] = value

    def get_output_dir(self) -> Path:
        """Ritorna la directory di output radice."""
        return self.output_dir
    
    def get_required(self, key: str):
        """
        Recupera un valore dal contesto.
        Solleva un'eccezione KeyError se la chiave non è presente.
        """
        if key not in self.data:
            self.logger.error(f"La chiave richiesta '{key}' non è stata trovata nel contesto.")
            raise KeyError(f"La chiave richiesta '{key}' non è stata trovata nel contesto. Contesto attuale: {self.data}")
        return self.data[key]

    def get_step_output_dir(self, step_name: str) -> Path:
        """
        Crea e ritorna una sub-directory dedicata per uno step (es. /output/sfm/).
        Questo mantiene l'output pulito e organizzato.
        """
        # Pulisce il nome per evitare problemi di percorso
        safe_step_name = step_name.replace(":", "_").replace("/", "_")

        if safe_step_name not in self.step_dirs:
            step_dir = self.output_dir / safe_step_name
            step_dir.mkdir(parents=True, exist_ok=True)
            self.step_dirs[safe_step_name] = step_dir
            self.logger.debug(
                f"Creata directory per lo step '{safe_step_name}': {step_dir}"
            )
        return self.step_dirs[safe_step_name]

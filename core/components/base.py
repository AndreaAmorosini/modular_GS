import logging
from pathlib import Path
import jinja2
from core.utils import run_command
from core.context import PipelineContext
from core.utils import get_or_download_pixi  # Importa il getter
import subprocess
import os


class MethodRunner:
    def __init__(self, config: dict, env_path: Path, base_path: Path):
        self.config = config
        self.env_path = env_path
        self.base_path = base_path
        self.pixi_exe = get_or_download_pixi(base_path)

    def run(self, context):
        """
        Esegue il comando del metodo dentro l'ambiente Pixi.
        """
        print(f"--- Running Method: {self.config.get('title')} ---")

        # 1. Prepara il comando usando Jinja (logica esistente nel tuo codice)
        # Assumiamo che self.config["execution"]["command"] sia es:
        # "ns-train splatfacto --data {data_dir}"
        raw_cmd = self.config["execution"]["command"]

        # (Qui inserisci la tua logica di risoluzione template Jinja/format)
        # Esempio semplificato:
        cmd_str = raw_cmd.format(
            data_dir=context.get_data_dir(),
            output_dir=context.get_output_dir(),
            # ... altri parametri
        )

        print(f"Command payload: {cmd_str}")

        # 2. Costruisci il comando Pixi
        # "pixi run" esegue il comando nel contesto dell'ambiente
        full_cmd = [
            str(self.pixi_exe),
            "run",
            # Possiamo passare comandi shell arbitrari
            "bash",
            "-c",
            cmd_str,
        ]

        # 3. Esegui
        try:
            subprocess.check_call(
                full_cmd,
                cwd=self.env_path,  # Importante: Pixi cerca pixi.toml qui
                env=os.environ,
            )
        except subprocess.CalledProcessError as e:
            print(f"Execution failed with error: {e}")
            raise e
        
    def _render_template(self, template_str: str, vars: dict) -> str:
        template = self.jinja_env.from_string(template_str)
        return template.render(vars)

    def _prepare_template_vars(self) -> dict:
        """Raccoglie tutte le variabili per Jinja2."""
        
        # method_vendor_dir = (self.project_root / "full_pipe_v2" / "vendor" / self.name).resolve()
        method_vendor_dir = (self.project_root / "vendor" / self.name).resolve()


        vars = {
            "context": self.context.data,
            "config": self.step_config,
            "method": self.method_config,
            "step_output_dir": str(self.context.get_step_output_dir(self.name)),
            "project_root": str(self.project_root.resolve()),
            "method_vendor_dir": str(method_vendor_dir),
        }

        # Calcola e aggiungi 'env_path'
        env_name = self.method_config.get("installation", {}).get("conda_env_name")
        if env_name:
            env_path = (
                self.project_root / ".envs" / env_name
            ).resolve()
            vars["env_path"] = str(env_path)

            if not env_path.exists():
                pass  # La logica di installazione gestirà questo

        # Risolvi gli input
        inputs = {}
        if "inputs" in self.step_config:
            for key, template_str in self.step_config["inputs"].items():
                # input_value = self.context.get_required(key)
                rendered_value = self._render_template(template_str, vars)
                if isinstance(rendered_value, str):
                    rendered_value = str(Path(rendered_value).expanduser().resolve())
                inputs[key] = rendered_value
        vars["inputs"] = inputs

        # Risolvi gli output
        outputs = {}
        if "outputs" in self.method_config["execution"]:
            for key, path_template in self.method_config["execution"][
                "outputs"
            ].items():
                rendered_path = self._render_template(path_template, vars)
                outputs[key] = rendered_path
        vars["outputs"] = outputs

        # Prepara i kwargs per il comando
        kwargs = {}
        if "template_vars" in self.method_config["execution"]:
            for key, template_str in self.method_config["execution"][
                "template_vars"
            ].items():
                rendered_value = self._render_template(template_str, vars)
                # Prova a convertire in tipi numerici o booleani
                if isinstance(rendered_value, str):
                    if rendered_value.lower() == "true":
                        kwargs[key] = True
                    elif rendered_value.lower() == "false":
                        kwargs[key] = False
                    elif rendered_value.isdigit():
                        kwargs[key] = int(rendered_value)
                    else:
                        try:
                            kwargs[key] = float(rendered_value)
                        except ValueError:
                            kwargs[key] = rendered_value
                else:
                    kwargs[key] = rendered_value
        vars["kwargs"] = kwargs

        return vars
    

    def _check_and_register_outputs(self, template_vars: dict):
        """Verifica e salva l'output primario nel context."""
        self.logger.info("Verifica degli output...")

        # 1. Prende la chiave con cui salvare l'output nel contesto (es. "colmap_model_dir").
        #    Questa è definita nel file della pipeline -> self.step_config.
        output_key_in_context = self.step_config.get("output_key")
        if not output_key_in_context:
            self.logger.debug(
                "Nessun 'output_key' definito per questo step nella pipeline. Salto la registrazione."
            )
            return

        # 2. Prende il nome dell'output primario definito nel metodo (es. "colmap_model_dir").
        #    Questo è definito nel file del metodo -> self.method_config.
        primary_output_name = self.step_config.get("primary_output") or self.method_config["execution"].get("primary_output")
        if not primary_output_name:
            self.logger.debug(
                "Nessun 'primary_output' definito nel metodo. Salto la registrazione."
            )
            return

        # 3. Recupera il percorso dell'output già renderizzato da _prepare_template_vars.
        output_path_str = template_vars["outputs"].get(primary_output_name)
        if not output_path_str:
            self.logger.error(
                f"La chiave 'primary_output' '{primary_output_name}' non ha un percorso corrispondente in [execution.outputs]."
            )
            raise ValueError(
                f"Impossibile trovare il percorso per l'output primario '{primary_output_name}'."
            )

        # 4. Verifica che il file o la directory di output esista effettivamente.
        output_path = Path(output_path_str)
        if not output_path.exists():
            raise FileNotFoundError(
                f"Output primario atteso '{primary_output_name}' non trovato nel percorso: {output_path}"
            )

        # 5. Salva il percorso nel contesto usando la chiave definita nella pipeline.
        self.context.set(output_key_in_context, str(output_path))
        self.logger.info(
            f"Output salvato nel contesto: context['{output_key_in_context}'] = '{output_path}'"
        )

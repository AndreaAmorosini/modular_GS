import toml
import logging
import subprocess
from pathlib import Path
from typing import Dict, Any, Tuple
import jinja2
import typer
import sys


class Validator:
    """Carica, elenca e valida i metodi dai manifest .toml."""

    def __init__(self, methods_dir: Path):
        self.methods_dir = methods_dir
        self.project_root = methods_dir.parent
        self.envs_dir = self.project_root / ".envs"
        self.registry = self._load_method_registry()
        self.jinja_env = jinja2.Environment(loader=jinja2.BaseLoader())

    def _load_method_registry(self) -> Dict[str, Any]:
        """Scansiona 'methods/' e carica tutti i .toml."""
        registry = {}
        if not self.methods_dir.is_dir():
            raise FileNotFoundError(f"Directory metodi non trovata: {self.methods_dir}")

        for toml_file in self.methods_dir.glob("**/*.toml"):
            try:
                config = toml.load(toml_file)
                name = config["name"]
                config["__path__"] = (
                    toml_file  # Salva il percorso per riferimenti futuri
                )
                registry[name] = config
            except Exception as e:
                logging.warning(f"Impossibile caricare {toml_file}: {e}")
        return registry

    def find_method_manifest(self, method_name: str) -> Tuple[Path, Dict[str, Any]]:
        """Trova il percorso e la config di un metodo dal suo nome."""
        if method_name not in self.registry:
            raise FileNotFoundError(f"Metodo '{method_name}' non trovato nel registro.")
        config = self.registry[method_name]
        return config["__path__"], config

    def list_methods(self):
        """Stampa un elenco di tutti i metodi trovati."""
        if not self.registry:
            typer.echo("Nessun metodo registrato.")
            return

        for name, config in self.registry.items():
            typer.secho(f"\n{name} (tipo: {config.get('step_type', 'N/A')})", bold=True)
            typer.echo(f"  Desc: {config.get('description', 'N/A')}")
            typer.echo(
                f"  Manifest: {config['__path__'].relative_to(self.project_root)}"
            )

    def validate_method(self, name: str, config: dict, verbose: bool) -> bool:
        """Esegue il 'validation_command' per un singolo metodo."""
        cmd_template = config.get("validation", {}).get("validation_command")
        if not cmd_template:
            logging.warning(f"Nessun 'validation_command' per {name}. Assunto valido.")
            return True

        try:
            # Prepara le variabili per il template (solo env_path)
            vars = {}
            env_name = config.get("installation", {}).get("conda_env_name")
            cmd_base = self.jinja_env.from_string(cmd_template).render(vars)

            if env_name:
                env_path = (self.project_root / ".envs" / env_name).resolve()
                if not env_path.exists():
                    logging.warning(
                        f"Ambiente locale non trovato in {env_path}. Validazione fallirà."
                    )
                    return False
                vars["env_path"] = str(env_path)
                cmd = f"conda run --prefix {env_path} {cmd_base}"
            else:
                cmd = f"conda run --no-capture-output {cmd_base}"
            
            logging.debug(f"Validazione {name} con: {cmd}")
            subprocess.run(
                cmd, shell=True, check=True, capture_output=not verbose, text=True
            )
            return True

        except Exception as e:
            logging.error(f"Validazione fallita per {name}: {e}")
            if not verbose and hasattr(e, "stderr"):
                logging.error(f"Errore: {e.stderr.strip()}")
            return False

    def validate_installed(self, verbose: bool):
        """
        Scansiona la directory .envs, trova i metodi installati, lancia la
        validazione solo per quelli e stampa un riepilogo colorato.
        """
        if not self.envs_dir.exists() or not any(self.envs_dir.iterdir()):
            typer.echo(
                typer.style(
                    "Nessun ambiente trovato nella directory .envs/. Nessun metodo da validare.",
                    fg=typer.colors.YELLOW,
                )
            )
            return

        typer.echo("Avvio validazione per i metodi installati...")
        installed_env_names = {d.name for d in self.envs_dir.iterdir() if d.is_dir()}

        # Filtra prima i metodi che hanno un ambiente corrispondente
        methods_to_validate = []
        for name, config in self.registry.items():
            env_name_from_config = config.get("installation", {}).get("conda_env_name")
            if env_name_from_config and env_name_from_config in installed_env_names:
                methods_to_validate.append((name, config))

        if not methods_to_validate:
            typer.echo(
                typer.style(
                    "Nessun metodo registrato corrisponde agli ambienti trovati in .envs/.",
                    fg=typer.colors.YELLOW,
                )
            )
            return

        # Esegui la validazione e tieni traccia dei successi
        success_count = 0
        total_to_validate = len(methods_to_validate)

        for name, config in methods_to_validate:
            typer.echo(f"  Validando [{name}]...", nl=False)
            success = self.validate_method(name, config, verbose)
            if success:
                typer.secho(" OK", fg=typer.colors.GREEN, bold=True)
                success_count += 1
            else:
                typer.secho(" FALLITO", fg=typer.colors.RED, bold=True)

        # Stampa il riepilogo finale
        success = True
        summary_color = typer.colors.GREEN
        if success_count < total_to_validate:
            summary_color = typer.colors.YELLOW
            success = False
        if success_count == 0 and total_to_validate > 0:
            summary_color = typer.colors.RED
            success = False

        typer.secho(
            f"\nRisultato finale: {success_count}/{total_to_validate} metodi validati con successo.",
            fg=summary_color,
            bold=True,
        )
        
        return success
    
    def validate_single(self, method_name: str, verbose: bool) -> bool:
        """Valida un singolo metodo specificato per nome."""
        typer.echo(f"Ricerca del metodo '{method_name}' per la validazione...")

        # Cerca il metodo nel registro
        if method_name not in self.registry:
            typer.secho(
                f"Errore: Metodo '{method_name}' non trovato.",
                fg=typer.colors.RED,
                err=True,
            )
            typer.echo("I metodi disponibili sono:")
            self.list_methods()
            return False

        config = self.registry[method_name]

        # Esegui la validazione
        typer.echo(f"  Validando [{method_name}]...", nl=False)
        success = self.validate_method(method_name, config, verbose)

        if success:
            typer.secho(" OK", fg=typer.colors.GREEN, bold=True)
            typer.secho(f"\nIl metodo '{method_name}' è stato validato con successo.", fg=typer.colors.GREEN)
        else:
            typer.secho(" FALLITO", fg=typer.colors.RED, bold=True)
            typer.secho(f"\nLa validazione per il metodo '{method_name}' è fallita.", fg=typer.colors.RED)

        return success
        
    def validate_all(self, verbose: bool) -> bool:
        """Valida tutti i metodi nel registro."""
        overall_success = True
        typer.echo("Validazione installazione tool (negli ambienti ./.envs/)...")

        if not self.registry:
            typer.echo("Nessun metodo da validare.")
            return True

        for name, config in self.registry.items():
            typer.echo(f"  Validando [{name}]...", nl=False)
            success = self.validate_method(name, config, verbose)
            if success:
                typer.secho(" OK", fg=typer.colors.GREEN, bold=True)
            else:
                typer.secho(" FALLITO", fg=typer.colors.RED, bold=True)
                overall_success = False

        return overall_success

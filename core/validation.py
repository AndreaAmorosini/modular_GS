import toml
import logging
import subprocess
import shlex
import typer
from pathlib import Path
from typing import Dict, Any, Tuple, Optional
from core.utils import get_or_download_pixi

class Validator:
    """Gestisce la validazione dei metodi installati tramite Pixi."""

    def __init__(self, methods_dir: Path):
        self.methods_dir = methods_dir
        self.project_root = methods_dir.parent
        self.envs_dir = self.project_root / ".envs"
        self.pixi_exe = get_or_download_pixi(self.project_root)
        self.registry = self._load_method_registry()

    def _load_method_registry(self) -> Dict[str, Any]:
        """
        Scansiona 'methods/' e carica tutti i .toml.
        Usa il nome del file (senza estensione) come ID univoco del metodo.
        """
        registry = {}
        if not self.methods_dir.is_dir():
            raise FileNotFoundError(f"Directory metodi non trovata: {self.methods_dir}")

        for toml_file in self.methods_dir.glob("**/*.toml"):
            try:
                config = toml.load(toml_file)
                # L'ID è il nome del file (es. 'nerfstudio' da 'nerfstudio.toml')
                # Questo deve corrispondere al nome della cartella in .envs/
                method_id = toml_file.stem
                config["__id__"] = method_id
                config["__path__"] = toml_file
                
                # Fallback per title se non esiste
                if "title" not in config:
                    config["title"] = method_id

                registry[method_id] = config
            except Exception as e:
                logging.warning(f"Impossibile caricare {toml_file}: {e}")
        return registry

    def find_method_config(self, method_id: str) -> Optional[Dict[str, Any]]:
        return self.registry.get(method_id)

    def validate_method(self, method_id: str, verbose: bool = False) -> bool:
        """
        Esegue il comando di validazione definito nel TOML usando 'pixi run'.
        """
        config = self.registry.get(method_id)
        if not config:
            typer.secho(f"Metodo '{method_id}' non trovato nel registro.", fg=typer.colors.RED)
            return False

        # 1. Recupera il comando dal TOML
        validation_section = config.get("validation", {})
        cmd_str = validation_section.get("validation_command")
        
        if not cmd_str:
            # Se non c'è una sezione validation, consideriamo OK se l'ambiente esiste
            env_path = self.envs_dir / method_id
            if (env_path / "pixi.toml").exists():
                if verbose:
                    typer.echo(f"  Nessun comando di validazione per {method_id}, ma l'ambiente esiste.")
                return True
            else:
                if verbose:
                    typer.echo(f"  Ambiente non trovato per {method_id} (atteso in: {env_path}).")
                return False

        # 2. Verifica l'esistenza dell'ambiente Pixi
        env_path = self.envs_dir / method_id
        manifest_path = env_path / "pixi.toml"
        
        if not manifest_path.exists():
            if verbose:
                typer.secho(f"  Manifest non trovato: {manifest_path}", fg=typer.colors.YELLOW)
            return False

        # 3. Costruisci il comando Pixi
        # pixi run --manifest-path <path> <cmd>
        pixi_cmd = [
            str(self.pixi_exe),
            "run",
            "--manifest-path",
            str(manifest_path),
        ] + shlex.split(cmd_str)

        try:
            if verbose:
                typer.echo(f"  Esecuzione: {' '.join(pixi_cmd)}")
            
            # Eseguiamo il comando dentro l'ambiente gestito da Pixi
            result = subprocess.run(
                pixi_cmd,
                check=True,
                cwd=self.project_root, # Eseguiamo dalla root per coerenza
                stdout=subprocess.PIPE if not verbose else None,
                stderr=subprocess.PIPE if not verbose else None,
                text=True
            )
            return True

        except subprocess.CalledProcessError as e:
            if verbose:
                typer.secho(f"  Errore durante la validazione di {method_id}!", fg=typer.colors.RED)
                if e.stderr:
                    typer.echo(f"  STDERR:\n{e.stderr}")
            return False
        except Exception as e:
            typer.secho(f"  Eccezione imprevista: {e}", fg=typer.colors.RED)
            return False

    def validate_installed(self, verbose: bool):
        """
        Valida tutti i metodi che hanno una cartella corrispondente in .envs/
        """
        if not self.envs_dir.exists():
            typer.secho("Directory .envs/ non trovata. Nessuna installazione rilevata.", fg=typer.colors.YELLOW)
            return

        installed_envs = [p.name for p in self.envs_dir.iterdir() if p.is_dir()]
        
        if not installed_envs:
            typer.secho("Nessun ambiente trovato in .envs/.", fg=typer.colors.YELLOW)
            return

        typer.secho(f"Avvio validazione per {len(installed_envs)} ambienti trovati...", bold=True)
        
        success_count = 0
        checked_count = 0

        for env_name in installed_envs:
            # Verifica se questo ambiente corrisponde a un metodo noto
            if env_name not in self.registry:
                if verbose:
                    typer.echo(f"Ignorato environment '{env_name}' (nessun metodo corrispondente in methods/).")
                continue

            checked_count += 1
            typer.echo(f"Validazione [{env_name}]... ", nl=False)
            
            is_valid = self.validate_method(env_name, verbose=verbose)
            
            if is_valid:
                typer.secho("PASSATO", fg=typer.colors.GREEN, bold=True)
                success_count += 1
            else:
                typer.secho("FALLITO", fg=typer.colors.RED, bold=True)

        if checked_count == 0:
            typer.echo("Nessuno degli ambienti trovati corrisponde a metodi registrati.")
            return

        color = typer.colors.GREEN if success_count == checked_count else typer.colors.RED
        typer.secho(f"\nRiepilogo: {success_count}/{checked_count} metodi operativi.", fg=color, bold=True)
        
        return success_count == checked_count
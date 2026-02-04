import toml
import logging
import subprocess
import shlex
import typer
from pathlib import Path
from typing import Dict, Any, Tuple, Optional
from core.utils import get_or_download_pixi
import json

_custom_logger = logging.getLogger("CustomValidationLog")

class Validator:
    """Gestisce la validazione dei metodi installati tramite Pixi."""

    def __init__(self, methods_dir: Path):
        self.methods_dir = methods_dir
        self.project_root = methods_dir.parent
        self.envs_dir = self.project_root / ".envs"
        self.pixi_exe = get_or_download_pixi(self.project_root)
        self.registry = self._load_method_registry()
        self.logger = _custom_logger

    def _load_method_registry(self) -> Dict[str, Any]:
        """
        Scans 'methods/' and load all of the .toml files.
        Uses the name of the file as the unique ID of the method.
        """
        registry = {}
        if not self.methods_dir.is_dir():
            raise FileNotFoundError(f"Methods Directory not found: {self.methods_dir}")

        for toml_file in self.methods_dir.glob("**/*.toml"):
            try:
                config = toml.load(toml_file)
                # the ID is the name of the TOML file (without extension)
                # This must match the name in .envs/
                method_id = toml_file.stem
                config["__id__"] = method_id
                config["__path__"] = toml_file
                
                # Fallback for title if not present
                if "title" not in config:
                    config["title"] = method_id

                registry[method_id] = config
            except Exception as e:
                logging.warning(f"Failed to load: {toml_file}: {e}")
        return registry

    def find_method_config(self, method_id: str) -> Optional[Dict[str, Any]]:
        return self.registry.get(method_id)

    def validate_method(self, method_id: str, verbose: bool = False) -> bool:
        """
        Execute the validation command specified in the TOML using 'pixi run'.
        """
        config = self.registry.get(method_id)
        if not config:
            self.logger.error(f"Method '{method_id}' not found.")
            return False

        # Take the command from the TOML
        validation_section = config.get("validation", {})
        cmd_str = validation_section.get("validation_command")
        
        if not cmd_str:
            # If no validation command is specified only check for env existence
            env_path = self.envs_dir / method_id
            if (env_path / "pixi.toml").exists():
                if verbose:
                    logging.info(f"No validation command found for {method_id}, but the env is present.")
                return True
            else:
                if verbose:
                    logging.info(f"Environment not found for {method_id} (checked in: {env_path}).")
                return False

        # Check on Pixi environment
        env_path = self.envs_dir / method_id
        manifest_path = env_path / "pixi.toml"
        env_name = None
        
        if not manifest_path.exists():
            share_meta = env_path / "shared_env.json"
            if share_meta.exists():
                with open(share_meta, "r") as f:
                    meta = json.load(f)
                manifest_path = Path(meta.get("manifest_path", ""))
                env_name = meta.get("env_name", None)
        
        if not manifest_path.exists():
            if verbose:
                logging.error(f"Manifest not found: {manifest_path}")
            return False

        # Build the Pixi command
        # pixi run --manifest-path <path> <cmd>
        pixi_cmd = [
            str(self.pixi_exe),
            "run",
            "--manifest-path",
            str(manifest_path),
        ]
        
        if env_name:
            pixi_cmd += ["-e", env_name]
            
        pixi_cmd += shlex.split(cmd_str)

        try:
            if verbose:
                logging.info(f"Executing: {' '.join(pixi_cmd)}")
            
            result = subprocess.run(
                pixi_cmd,
                check=True,
                cwd=self.project_root,
                stdout=subprocess.PIPE if not verbose else None,
                stderr=subprocess.PIPE if not verbose else None,
                text=True
            )
            self.logger.debug(f"Validation command for {method_id} completed successfully.")
            return True

        except subprocess.CalledProcessError as e:
            if verbose:
                logging.error(f"Error validating {method_id}!")
                if e.stderr:
                    logging.error(f"STDERR:\n{e.stderr}")
            return False
        except Exception as e:
            logging.error(f"Exception: {e}", fg=typer.colors.RED)
            return False

    def validate_installed(self, verbose: bool):
        """
        Validate all the methods that have a folder in .envs/
        """
        if not self.envs_dir.exists():
            self.logger.error("Directory .envs/ non found. No installation found.", fg=typer.colors.YELLOW)
            return

        installed_envs = [p.name for p in self.envs_dir.iterdir() if p.is_dir()]
        
        if not installed_envs:
            self.logger.error("No environments found in .envs/.", fg=typer.colors.YELLOW)
            return

        self.logger.info(f"Validating {len(installed_envs) - 1} environment found...")
        
        success_count = 0
        checked_count = 0

        for env_name in installed_envs:
            # Check env -> method
            if env_name not in self.registry:
                if verbose:
                    self.logger.warning(f"Skipping environment '{env_name}' (no corresponding method found in methods/).")
                continue

            checked_count += 1
            self.logger.info(f"Validating [{env_name}]... ")
            
            is_valid = self.validate_method(env_name, verbose=verbose)
            
            if is_valid:
                self.logger.info("OK")
                success_count += 1
            else:
                self.logger.error("FAILED")

        if checked_count == 0:
            self.logger.warning("No environments found corresponding to methods in registry.")
            return

        if success_count == checked_count:
            self.logger.info(f"\Summary: {success_count}/{checked_count} operational methods.")
        else:
            self.logger.warning(f"\Summary: {success_count}/{checked_count} operational methods.")
        
        return success_count == checked_count
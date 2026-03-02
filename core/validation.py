import toml
import logging
import subprocess
import shlex
import typer
from pathlib import Path
from typing import Dict, Any, Tuple, Optional
from core.utils import get_or_download_pixi, RichLogger
import json


class Validator:
    """Gestisce la validazione dei metodi installati tramite Pixi."""

    def __init__(self, methods_dir: Path, verbose: bool = False):
        self.logger = RichLogger(debug_enabled=verbose, verbose=verbose)
        self.methods_dir = methods_dir
        self.project_root = methods_dir.parent
        self.envs_dir = self.project_root / ".envs"
        self.pixi_exe = get_or_download_pixi(self.project_root)
        self.registry = self._load_method_registry()
        self.verbose = verbose

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
                method_id = toml_file.stem
                metadata = self._extract_metadata(toml_file)
                metadata.setdefault("title", method_id)
                registry[method_id] = {
                    "__id__": method_id,
                    "__path__": toml_file,
                    "__metadata__": metadata,
                    "__config__": None
                }
            except Exception as e:
                self.logger.error(f"Failed to load: {toml_file}: {e}")
        return registry
    
    def _extract_metadata(self, toml_file: Path) -> Dict[str, Any]:
        metadata: Dict[str, Any] = {}
        metadata_section = False
        keys_of_interest = {"title", "description", "url", "type"}
        
        try:
            with open(toml_file, "r", encoding="utf-8") as f:
                for raw_line in f:
                    line = raw_line.split("#", 1)[0].strip()
                    if not line:
                        continue
                    if line.startswith("["):
                        section = line.strip("[]").lower()
                        metadata_section = section == "metadata"
                        if not metadata_section and metadata:
                            break
                        continue
                    if "=" not in line:
                        continue
                    key, value = [part.strip() for part in line.split("=", 1)]
                    if metadata_section or key in keys_of_interest:
                        value = value.split("#", 1)[0].strip()
                        if not value:
                            continue
                        try:
                            parsed = toml.loads(value)
                        except Exception:
                            parsed = value.strip('"').strip("'")
                        metadata[key] = parsed
        except Exception as e:
            self.logger.error(f"Error extracting metadata from {toml_file}: {e}")
            pass
        return metadata
    
    def find_method_config(self, method_id: str) -> Optional[Dict[str, Any]]:
        entry = self.registry.get(method_id)
        if not entry:
            return None
        if entry["__config__"] is None:
            config = toml.load(entry["__path__"])
            config["__id__"] = method_id
            config["__path__"] = entry["__path__"]
            entry["__config__"] = config
            entry["__metadata__"].setdefault("title", config.get("title", method_id))
        return entry["__config__"]

    def validate_method(self, method_id: str, all: bool) -> bool:
        """
        Execute the validation command specified in the TOML using 'pixi run'.
        """
        config = self.find_method_config(method_id)
        if not config:
            self.logger.warning(f"Method '{method_id}' not found.")
            return False

        # Take the command from the TOML
        validation_section = config.get("validation", {})
        cmd_str = validation_section.get("validation_command")
        
        if not cmd_str:
            # If no validation command is specified only check for env existence
            env_path = self.envs_dir / method_id
            if (env_path / "pixi.toml").exists():
                self.logger.info(f"No validation command found for {method_id}, but the env is present.")
                return True
            else:
                self.logger.debug(f"Environment not found for {method_id} (checked in: {env_path}).")
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
            self.logger.error(f"Manifest not found: {manifest_path}")
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
            self.logger.debug(f"Executing: {' '.join(pixi_cmd)}")
            
            result = subprocess.run(
                pixi_cmd,
                check=True,
                cwd=self.project_root,
                stdout=subprocess.PIPE if self.verbose or all else None,
                stderr=subprocess.PIPE if self.verbose or all else None,
                text=True
            )
            self.logger.success(f"Validation command for {method_id} completed successfully.")
            return True

        except subprocess.CalledProcessError as e:
            self.logger.error(f"Error validating {method_id}!")
            if e.stderr:
                self.logger.error(f"STDERR:\n{e.stderr}")
            return False
        except Exception as e:
            self.logger.error(f"Exception: {e}")
            return False

    def validate_installed(self):
        """
        Validate all the methods that have a folder in .envs/
        """
        if not self.envs_dir.exists():
            self.logger.error("Directory .envs/ non found. No installation found.")
            return

        installed_envs = [p.name for p in self.envs_dir.iterdir() if p.is_dir()]
        
        if not installed_envs:
            self.logger.error("No environments found in .envs/.")
            return

        self.logger.info(f"Validating {len(installed_envs) - 1} environment found...")
        
        success_count = 0
        checked_count = 0

        for env_name in installed_envs:
            # Check env -> method
            if env_name not in self.registry:
                if env_name != "_shared":
                    self.logger.warning(f"Skipping environment '{env_name}' (no corresponding method found in methods/).")
                continue

            checked_count += 1
            self.logger.info(f"Validating [{env_name}]... ")
            
            with self.logger.spinner("Validating... "):
                is_valid = self.validate_method(env_name, all=True)
            
            if is_valid:
                self.logger.success(f"[{env_name}] OK")
                success_count += 1
            else:
                self.logger.error(f"[{env_name}] FAILED")

        if checked_count == 0:
            self.logger.warning("No environments found corresponding to methods in registry.")
            return

        if success_count == checked_count:
            self.logger.success(f"\nSummary: {success_count}/{checked_count} operational methods.")
        else:
            self.logger.warning(f"\nSummary: {success_count}/{checked_count} operational methods.")
        
        return success_count == checked_count
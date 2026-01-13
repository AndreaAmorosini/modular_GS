import os
import shutil
import subprocess
import tomli_w
from pathlib import Path
from typing import Dict
from core.utils import get_or_download_pixi


class MethodInstaller:
    def __init__(self, method_config: Dict, base_path: Path):
        self.config = method_config
        self.base_path = base_path
        self.pixi_exe = get_or_download_pixi(self.base_path)

    def install(self, env_path: Path):
        env_path.mkdir(parents=True, exist_ok=True)
        print(f"--- Configuring Environment in {env_path} ---")

        try:
            # 1. Genera pixi.toml
            pixi_data = self._generate_pixi_structure()

            toml_path = env_path / "pixi.toml"
            with open(toml_path, "wb") as f:
                tomli_w.dump(pixi_data, f)

            print(f"Configuration generated at {toml_path}")

            # 2. Pixi Install (Ambiente Base)
            print("--- Running Pixi Install ---")
            subprocess.check_call(
                [str(self.pixi_exe), "install"], cwd=env_path, env=os.environ
            )

            # 3. Esegui Task di Post-Installazione (se definiti)
            for task_name in pixi_data.get("tasks", {}):
                print(f"--- Running Task: {task_name} ---")
                subprocess.check_call(
                    [str(self.pixi_exe), "run", task_name],
                    cwd=env_path,
                    env=os.environ,
                )

            print("--- Installation Complete ---")

        except subprocess.CalledProcessError as e:
            print(f"!!! Installation Failed !!!")
            print(f"Error: {e}")
            self._cleanup_failed_env(env_path)
            raise

        except Exception as e:
            print(f"!!! Unexpected Error During Installation !!!")
            print(f"Error: {e}")
            self._cleanup_failed_env(env_path)
            raise

    def _cleanup_failed_env(self, env_path: Path):
        """Rimuove l'ambiente in caso di installazione fallita."""
        if env_path.exists():
            print(f"--- Cleaning up failed environment: {env_path} ---")
            try:
                shutil.rmtree(env_path)
                print("Cleanup complete.")
            except Exception as cleanup_error:
                print(f"Warning: Could not fully clean up: {cleanup_error}")
                print(f"You may need to manually delete: {env_path}")

    def _generate_pixi_structure(self) -> Dict:
        install_cfg = self.config.get("installation", {})
        env_cfg = self.config.get("environment", {})

        default_channels = ["pytorch", "nvidia", "conda-forge"]

        pixi = {
            "project": {
                "name": self.config.get("title", "module").replace(" ", "_").lower(),
                "version": "0.1.0",
                "channels": install_cfg.get("channels", default_channels),
                "platforms": ["linux-64"],
            },
            "dependencies": {
                "python": self._format_ver(env_cfg.get("python_version", "3.10")),
                "pip": "*",
            },
            "pypi-dependencies": {},
            "tasks": {},
            "system-requirements": {"linux": "5.4"},
        }

        # Dipendenze Conda - passthrough dal TOML
        for dep in install_cfg.get("dependencies", []):
            name, version = self._parse_dep(dep)
            pixi["dependencies"][name] = self._format_ver(version)

        # Dipendenze PyPI
        for dep in install_cfg.get("pip_dependencies", []):
            name, version = self._parse_pypi_dep(dep)
            pixi["pypi-dependencies"][name] = self._format_ver(version, is_pypi=True)

        # Build da sorgente (opzionale)
        build_cfg = install_cfg.get("build", {})
        if build_cfg:
            url = build_cfg.get("url")
            if url:
                flags = build_cfg.get("flags", "--no-build-isolation -v")
                pixi["tasks"]["install-extensions"] = f"pip install {url} {flags}"

        # Task custom dal TOML
        for task_name, task_cmd in install_cfg.get("tasks", {}).items():
            pixi["tasks"][task_name] = task_cmd

        return pixi

    def _parse_dep(self, s: str):
        """Parse: name=version, name<version, name>=version, name"""
        for sep in [">=", "<=", "!=", "<", ">", "="]:
            if sep in s:
                parts = s.split(sep, 1)
                name = parts[0].strip()
                ver = parts[1].strip()
                # Per '=' singolo, è una versione esatta
                if sep == "=":
                    return name, ver
                # Per altri operatori, mantieni l'operatore
                return name, sep + ver
        return s.strip(), "*"

    def _parse_pypi_dep(self, s: str):
        """Parse: name==version, name>=version, name"""
        for sep in ["==", ">=", "<=", "!=", "<", ">"]:
            if sep in s:
                parts = s.split(sep, 1)
                return parts[0].strip(), sep + parts[1].strip()
        return s.strip(), "*"

    def _format_ver(self, v: str, is_pypi: bool = False) -> str:
        """Formatta versione per pixi.toml."""
        if not v or v == "*":
            return "*"
        # Se ha già operatore, passa così com'è
        if any(op in v for op in [">=", "<=", "!=", "<", ">"]):
            return v
        # Versione esatta
        return f"=={v}" if is_pypi else f"{v}.*"

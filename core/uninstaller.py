import logging
import toml
import shutil
import platform
from pathlib import Path
from .utils import run_command


class MethodUninstaller:
    """Rimuove un metodo: il suo ambiente Conda locale e i suoi file vendor."""

    def __init__(self, method_config_path: Path):
        self.config_path = method_config_path.resolve()
        self.config = toml.load(method_config_path)
        self.name = self.config["name"]
        self.logger = logging.getLogger(f"Uninstaller.{self.name}")
        self.install_config = self.config.get("installation", {})

        # Path corretti e indipendenti dalla piattaforma
        self.pipe_root = self.config_path.parent.parent.parent
        self.envs_dir = self.pipe_root / ".envs"
        self.vendor_dir = self.pipe_root / "vendor"

    # def uninstall(self, verbose=False):
    #     self.logger.info(f"Inizio disinstallazione di '{self.name}'...")

    #     # 1. Rimuovi l'ambiente Conda, se esiste ed è dedicato
    #     env_name = self.install_config.get("conda_env_name")
    #     if env_name:
    #         env_path = (self.envs_dir / env_name).resolve()
    #         # Controlla se la directory esiste
    #         if env_path.exists():
    #             self.logger.info(f"Rimozione ambiente Conda dedicato: {env_path}")
    #             # Prova prima il metodo pulito di Conda
    #             cmd = f"conda env remove --prefix {env_path} -y"
    #             try:
    #                 run_command(cmd, self.logger.name, verbose, shell=True)
    #             except Exception as e:
    #                 # Se conda fallisce (es. 'Not a conda environment'), usa la rimozione forzata
    #                 self.logger.warning(
    #                     f"Comando 'conda env remove' fallito: {e}. Tento rimozione forzata della directory."
    #                 )
    #                 self._force_remove_dir(env_path)
    #         else:
    #             self.logger.info(
    #                 f"Nessun ambiente Conda dedicato '{env_name}' trovato. Salto."
    #             )
    #     else:
    #         self.logger.info(
    #             "Il metodo non usa un ambiente Conda dedicato. Salto rimozione ambiente."
    #         )

    #     # 2. Rimuovi la directory vendor del metodo
    #     method_vendor_path = self.vendor_dir / self.name
    #     if method_vendor_path.exists() and method_vendor_path.is_dir():
    #         self.logger.info(f"Rimozione directory vendor: {method_vendor_path}")
    #         self._force_remove_dir(method_vendor_path)
    #     else:
    #         self.logger.info(
    #             f"Nessuna directory vendor per '{self.name}' trovata. Salto."
    #         )

    #     self.logger.info(f"Disinstallazione di '{self.name}' completata.")

    def uninstall(self, verbose=False):
        self.logger.info(f"Inizio disinstallazione di '{self.name}'...")

        # 1. Rimuovi l'ambiente Conda (SEMPRE CON IL METODO VELOCE)
        env_name = self.install_config.get("conda_env_name")
        if env_name:
            env_path = (self.envs_dir / env_name).resolve()
            if env_path.exists():
                self.logger.info(f"Rimozione rapida ambiente Conda: {env_path}")
                self._force_remove_dir(env_path, verbose)  # Passiamo verbose
            else:
                self.logger.info(
                    f"Nessun ambiente Conda dedicato '{env_name}' trovato. Salto."
                )
        else:
            self.logger.info(
                "Il metodo non usa un ambiente Conda dedicato. Salto rimozione ambiente."
            )

        # 2. Rimuovi la directory vendor del metodo (SEMPRE CON IL METODO VELOCE)
        method_vendor_path = self.vendor_dir / self.name
        if method_vendor_path.exists() and method_vendor_path.is_dir():
            self.logger.info(f"Rimozione rapida directory vendor: {method_vendor_path}")
            self._force_remove_dir(method_vendor_path, verbose)  # Passiamo verbose
        else:
            self.logger.info(
                f"Nessuna directory vendor per '{self.name}' trovata. Salto."
            )

        self.logger.info(f"Disinstallazione di '{self.name}' completata.")

    def _force_remove_dir(self, dir_path: Path, verbose: bool = False):
        """
        Rimuove una directory in modo forzato e multipiattaforma.
        """
        self.logger.info(f"Avvio rimozione forzata per: {dir_path}")
        try:
            if platform.system() == "Windows":
                # 'rmdir /s /q' è più robusto di shutil.rmtree su Windows
                cmd = f'rmdir /s /q "{str(dir_path)}"'
                run_command(cmd, self.logger.name, verbose=verbose, shell=True)
            else:
                # 'rm -rf' è lo standard per Linux/macOS
                cmd = f'rm -rf "{str(dir_path)}"'
                run_command(cmd, self.logger.name, verbose=verbose, shell=True)
            self.logger.info(f"Rimozione forzata di '{dir_path}' completata.")
        except Exception as e:
            self.logger.error(f"Impossibile rimuovere forzatamente '{dir_path}': {e}")

from pathlib import Path
import sys
import logging
import subprocess
import time
from typing import List
import platform
import urllib.request
import tarfile
import zipfile
import stat
import os

try:
    import rerun as rr
except ImportError:
    rr = None


def get_or_download_pixi(base_dir: Path) -> Path:
    """
    Scarica pixi standalone in base_dir/bin/pixi se non esiste.
    """
    bin_dir = base_dir / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)

    exe_name = "pixi.exe" if platform.system() == "Windows" else "pixi"
    pixi_exe = bin_dir / exe_name

    if pixi_exe.exists():
        return pixi_exe.resolve()

    print(f"[SYSTEM] Pixi non trovato. Download in corso...")

    system = platform.system().lower()  # linux, darwin, windows
    machine = platform.machine().lower()  # x86_64, arm64

    # Mappatura URL rilasci ufficiali
    base_url = "https://github.com/prefix-dev/pixi/releases/latest/download"

    if system == "linux":
        file_name = "pixi-x86_64-unknown-linux-musl.tar.gz"
        if "aarch" in machine:
            file_name = "pixi-aarch64-unknown-linux-musl.tar.gz"
    elif system == "darwin":  # Mac
        file_name = "pixi-x86_64-apple-darwin.tar.gz"
        if "arm" in machine:
            file_name = "pixi-aarch64-apple-darwin.tar.gz"
    else:  # Windows
        file_name = "pixi-x86_64-pc-windows-msvc.zip"

    url = f"{base_url}/{file_name}"
    archive_path = bin_dir / file_name

    try:
        print(f"Downloading {url}...")
        urllib.request.urlretrieve(url, archive_path)

        if file_name.endswith(".zip"):
            with zipfile.ZipFile(archive_path, "r") as zip_ref:
                zip_ref.extractall(bin_dir)
        else:
            with tarfile.open(archive_path, "r:gz") as tar:
                tar.extractall(path=bin_dir)

        # Rendi eseguibile
        if system != "windows":
            st = os.stat(pixi_exe)
            os.chmod(pixi_exe, st.st_mode | stat.S_IEXEC)

        archive_path.unlink()  # Pulizia
        print(f"[SYSTEM] Pixi pronto: {pixi_exe}")

    except Exception as e:
        raise RuntimeError(f"Errore download Pixi: {e}")

    return pixi_exe.resolve()



def setup_logging(level=logging.INFO):
    """Configura il logger di radice."""
    logging.basicConfig(
        level=level,
        format="[%(asctime)s] [%(levelname)-7s] [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        stream=sys.stdout,
    )
    # Silenzia i log troppo verbosi di altre librerie
    logging.getLogger("PIL").setLevel(logging.WARNING)


def run_command(
    command: str | List[str],
    log_name: str,
    verbose: bool = False,
    shell: bool = False,
    retry_limit: int = 1,
    retry_cooldown: int = 30,
    cwd: str | Path | None = None,
    env=None,
):
    """
    Esegue un comando di subprocess, gestendo logging, verbosità e retry.
    """
    logger = logging.getLogger(log_name)
    cmd_str = command if isinstance(command, str) else " ".join(command)
    logger.info(f"Avvio comando: {command}")
    if verbose:
        logger.info(f"Comando completo: {cmd_str}")

    for attempt in range(1, retry_limit + 1):
        try:
            # Se verbose=True, stampa l'output in tempo reale
            if verbose:
                # Usiamo Popen per lo streaming live
                process = subprocess.Popen(
                    command,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    shell=shell,
                    encoding="utf-8",
                    errors="replace",
                    cwd = cwd,
                    env=env,
                    bufsize=1,
                )

                logger.info("--- Inizio output comando (verbose) ---")
                # Leggi e stampa l'output riga per riga
                for line in iter(process.stdout.readline, ""):
                    if line:
                        logger.debug(f"[CMD] {line.strip()}")

                process.stdout.close()
                returncode = process.wait()
                logger.info("--- Fine output comando ---")

            else:
                # Se verbose=False, cattura tutto alla fine
                result = subprocess.run(
                    command,
                    capture_output=True,
                    text=True,
                    shell=shell,
                    encoding="utf-8",
                    errors="replace",
                    cwd=cwd,
                    
                )
                returncode = result.returncode
                if returncode != 0:
                    # Stampa solo in caso di errore
                    logger.warning(f"Output (stdout): {result.stdout.strip()}")
                    logger.error(f"Errore (stderr): {result.stderr.strip()}")

            # Controllo finale
            if returncode == 0:
                logger.info("Comando completato con successo.")
                return  # Esce dal loop
            else:
                raise subprocess.CalledProcessError(returncode, cmd_str)

        except Exception as e:
            logger.error(f"Tentativo {attempt}/{retry_limit} fallito: {e}")
            if attempt < retry_limit:
                logger.info(f"Riprovo tra {retry_cooldown} secondi...")
                time.sleep(retry_cooldown)
            else:
                logger.critical(f"Comando fallito dopo {retry_limit} tentativi.")
                raise  # Solleva l'eccezione


class RerunVisualizer:
    """
    Singleton per gestire l'istanza di Rerun.
    (Implementa la richiesta "visualizzazione step intermedi")
    """

    _instance = None

    @staticmethod
    def get_instance():
        """Ottiene l'istanza singleton, creandola se necessario."""
        if RerunVisualizer._instance is None:
            if rr is None:
                logging.warning(
                    "Modulo 'rerun' non trovato. Visualizzazione disabilitata."
                )
                RerunVisualizer._instance = RerunVisualizer(enabled=False)
            else:
                RerunVisualizer._instance = RerunVisualizer(enabled=True)
        return RerunVisualizer._instance

    def __init__(self, enabled: bool):
        self.enabled = enabled
        if self.enabled:
            try:
                # "spawn()" avvia il visualizzatore Rerun in un processo separato
                rr.init("full_pipe_v2", spawn=True)
                logging.info("Visualizzatore Rerun avviato. Connettiti all'app.")
            except Exception as e:
                logging.error(f"Impossibile avviare Rerun: {e}")
                self.enabled = False

    def log_sfm_results(self, recon_path: Path):
        """Carica un modello sparse COLMAP e lo logga su Rerun."""
        if not self.enabled or not recon_path.exists():
            return

        logging.info(f"Invio risultati SfM a Rerun da {recon_path}...")
        try:
            # Per una visualizzazione reale, avresti bisogno di pycolmap
            # import pycolmap
            # recon = pycolmap.Reconstruction(recon_path)
            # points_data = ...
            # rr.log("sfm/points", rr.Points3D(positions=...))

            # Per ora, logghiamo un placeholder
            rr.log(
                "sfm/info",
                rr.TextDocument(f"Risultati SfM caricati da: {recon_path}"),
                timeless=True,
            )
            logging.info("Risultati SfM inviati (simulato).")

        except Exception as e:
            logging.warning(f"Visualizzazione Rerun (SfM) fallita: {e}")

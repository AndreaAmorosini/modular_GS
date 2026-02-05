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
from contextlib import contextmanager


try:
    import rerun as rr
    from rich.console import Console
    from rich.theme import Theme
    from rich.status import Status
    from rich.text import Text
except ImportError:
    rr = None
    Console = None
    Theme = None
    Status = None
    Text = None


def get_or_download_pixi(base_dir: Path) -> Path:
    """
    Check for pixi bin presence otherwise automatic download
    """
    bin_dir = base_dir / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)

    exe_name = "pixi.exe" if platform.system() == "Windows" else "pixi"
    pixi_exe = bin_dir / exe_name

    if pixi_exe.exists():
        return pixi_exe.resolve()

    logging.info(f"[SYSTEM] Pixi not found. Downloading...")

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
        logging.info(f"Downloading {url}...")
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
        logging.info(f"[SYSTEM] Pixi pronto: {pixi_exe}")

    except Exception as e:
        raise RuntimeError(f"Errore download Pixi: {e}")

    return pixi_exe.resolve()


#Formatter for logging
# class _ColorFormatter(logging.Formatter):
#     COLORS = {
#         logging.DEBUG: "\033[36m",  # ciano
#         logging.INFO: "\033[32m",  # verde
#         logging.WARNING: "\033[33m",  # giallo
#         logging.ERROR: "\033[31m",  # rosso
#         logging.CRITICAL: "\033[35m",  # magenta
#     }
#     RESET = "\033[0m"
    
#     def format(self, record: logging.LogRecord) -> str:
#         msg = super().format(record)
#         color = self.COLORS.get(record.levelno, self.RESET)
#         return f"{color}{msg}{self.RESET}" if color else msg
    
    
def setup_logging(
    level=logging.INFO,
    verbose: bool = False,
    allowList: list[str] | None = None,
):
    """Logger Setup"""
    
    allowlist = allowList or []
    effective_level = logging.DEBUG if verbose else level
    
    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(effective_level)
    
    logging.getLogger("PIL").setLevel(logging.WARNING)
    
    return RichLogger(
        verbose=verbose,
        color_enabled=True,
        debug_enabled=verbose,
        min_level=effective_level
    )
        
    
class RichLogger:
    ## Rich Logger for better console output
    def __init__(
        self, *,
        verbose: bool = False,
        color_enabled: bool = True,
        debug_enabled: bool = False,
        min_level: int = logging.INFO
    ):
        self.verbose = verbose
        self.color_enabled = color_enabled
        self.debug_enabled = debug_enabled
        self.min_level = min_level
        
        if Console is None:
            self._console = None
            return
        
        theme = Theme({
            #GRAY COLOR
            "log.info": "dim white",
            "log.success": "green",
            "log.warning": "yellow",
            "log.error": "bold red",
            "log.debug": "dim cyan",
        })
        self._console = Console(theme=theme, color_system="auto")
        
    def should_log(self, level: int, logger_name: str | None = None) -> bool:
        if self.verbose:
            return True
        return level >= self.min_level
        
    def _emit(self, level: str, message: str, color: str | None = None):
        if self._console is None:
            print(f"[{level.upper()}] {message}")
            return
        
        level_map = {
            "debug": logging.DEBUG,
            "info": logging.INFO,
            "success": logging.INFO,
            "warning": logging.WARNING,
            "error": logging.ERROR,
        }
        numeric_level = level_map.get(level, logging.INFO)
        
        if level == "debug" and not self.debug_enabled:
            return
        if not self.should_log(numeric_level):
            return
        
        style = f"log.{level}" if self.color_enabled else None
        if color:
            style = color
            
        text = Text(message, style=style)
        self._console.print(text)
        
    def info(self, message: str):
        self._emit("info", message)
        
    def success(self, message: str):
        self._emit("success", message)
        
    def warning(self, message: str):
        self._emit("warning", message)
    
    def error(self, message: str):
        self._emit("error", message)
        
    def debug(self, message: str):
        self._emit("debug", message)
        
    def custom(self, message: str, color: str):
        ## Custom color message
        self._emit("info", message, color=color)
        
    @contextmanager
    def spinner(self, message: str, spinner: str = "dots"):
        if self._console is None or Status is None:
            self.info(message + " ...")
            yield
            return
        
        with self._console.status(message, spinner=spinner):
            yield


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
    Execute subprocess commands.
    """
    logger = logging.getLogger(log_name)
    cmd_str = command if isinstance(command, str) else " ".join(command)
    logger.info(f"Executing Command: {command}")
    if verbose:
        logger.info(f"Full Command: {cmd_str}")

    for attempt in range(1, retry_limit + 1):
        try:
            # If verbose=True, print output in real time
            if verbose:
                # Popen for live streaming
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
                for line in iter(process.stdout.readline, ""):
                    if line:
                        logger.debug(f"[CMD] {line.strip()}")

                process.stdout.close()
                returncode = process.wait()
                logger.info("--- Fine output comando ---")

            else:
                # If verbose=False, take everything at the end of the process
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
                    # Only if in exception
                    logger.warning(f"Output (stdout): {result.stdout.strip()}")
                    logger.error(f"Errore (stderr): {result.stderr.strip()}")

            # Final check
            if returncode == 0:
                logger.info("Comando completato con successo.")
                return
            else:
                raise subprocess.CalledProcessError(returncode, cmd_str)

        except Exception as e:
            logger.error(f"Tentativo {attempt}/{retry_limit} fallito: {e}")
            if attempt < retry_limit:
                logger.info(f"Riprovo tra {retry_cooldown} secondi...")
                time.sleep(retry_cooldown)
            else:
                logger.critical(f"Comando fallito dopo {retry_limit} tentativi.")
                raise


class RerunVisualizer:
    """
    Singleton for managinfg Rerun instances.
    """

    _instance = None

    @staticmethod
    def get_instance():
        if RerunVisualizer._instance is None:
            if rr is None:
                logging.warning(
                    "Module 'rerun' not found."
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
                logging.info("Rerun visualizer OK. Connect to visualize.")
            except Exception as e:
                logging.error(f"Error while running Rerun: {e}")
                self.enabled = False

    def log_sfm_results(self, recon_path: Path):
        """Load a COLMAP model and log on Rerun."""
        if not self.enabled or not recon_path.exists():
            return

        logging.info(f"Sending SFM results to Rerun:{recon_path}...")
        try:
            # Per una visualizzazione reale, avresti bisogno di pycolmap
            # import pycolmap
            # recon = pycolmap.Reconstruction(recon_path)
            # points_data = ...
            # rr.log("sfm/points", rr.Points3D(positions=...))

            # Per ora, logghiamo un placeholder
            rr.log(
                "sfm/info",
                rr.TextDocument(f"SFM Results from: {recon_path}"),
                timeless=True,
            )
            logging.info("Risultati SfM inviati (simulato).")

        except Exception as e:
            logging.warning(f"Rerun visualization for SFM failed: {e}")

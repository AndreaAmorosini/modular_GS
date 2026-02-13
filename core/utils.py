from pathlib import Path
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
from ecdsa import SigningKey, VerifyingKey, NIST256p, BadSignatureError
import tomli
import typer
import struct
from rich.console import Console
from rich.theme import Theme
from rich.status import Status
from rich.text import Text
try:
    import numpy as np
except ImportError:
    np = None

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
        if self.verbose or self._console is None or Status is None:
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

class SignatureVerifier:
    """
    Manage the verification of the TOML files through the expected signature of the functions.
    """
    SIG_MARKER = "# MODULAR_GS_SIGNATURE: "
    PUBLIC_KEY_HEX = "a2fe3abc989e2b86601956703499dfbeb3b3f5b15b214d36c6d6264770132d84ac9e46ec0cede0fd05eaba3c1a2fd6882ac4bc7455fa4e85366dfba55f3c0142"
    
    def __init__(self):
        self.public_key = None
        self.private_key = None
        self.can_verify = False
        
        env_key = os.environ.get("MODULAR_GS_PRIVATE_KEY")
        if env_key:
            try:
                self.private_key = SigningKey.from_string(bytes.fromhex(env_key), curve=NIST256p)
                logging.info("[SECURITY] Private key loaded from environment variable.")
            except Exception as e:
                logging.error(f"[SECURITY] Failed to load private key from environment variable: {e}")
        
        if self.PUBLIC_KEY_HEX:
            try:
                self.public_key = VerifyingKey.from_string(bytes.fromhex(self.PUBLIC_KEY_HEX), curve=NIST256p)
                self.can_verify = True
                logging.info("[SECURITY] Public key loaded for signature verification.")
            except Exception as e:
                logging.error(f"[SECURITY] Failed to load public key: {e}")
        else:
            logging.warning("[SECURITY] No public key provided. Signature verification will be disabled.")
        
    def _get_clean_content_and_signature(self, file_path: Path) -> tuple[bytes, str | None]:
        """Check the file for the signature line and return the clean content and the signature separately."""
        if not file_path.exists():
            raise FileNotFoundError(f"File non trovato: {file_path}")
        
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
            
        lines = content.splitlines()
        signature = None
        
        # Cerca la firma partendo dal fondo
        for i in range(len(lines) - 1, -1, -1):
            line = lines[i].strip()
            if not line:
                continue
            if line.startswith(self.SIG_MARKER):
                signature = line.replace(self.SIG_MARKER, "").strip()
                lines = lines[:i] # Rimuove la riga della firma e tutto ciò che segue
                break
            else:
                break # Trovato contenuto non-firma alla fine
                
        # Normalizza il contenuto (strip trailing whitespace) per coerenza
        clean_text = "\n".join(lines).rstrip()
        return clean_text.encode("utf-8"), signature

    def sign(self, file_path: Path) -> None:
        """Create a signature for the file and embed it at the end of the file."""
        if not self.private_key:
            logging.error("[SECURITY] Private key not available. Cannot sign file.")
            return
        
        clean_bytes, _ = self._get_clean_content_and_signature(file_path)
        
        signature = self.private_key.sign(clean_bytes)
        sign_hex = signature.hex()
        
        with open(file_path, "wb") as f:
            f.write(clean_bytes)
            f.write(b"\n\n")
            f.write(f"{self.SIG_MARKER}{sign_hex}\n".encode("utf-8"))
            
        logging.info(f"[SECURITY] Firmato (embedded): {file_path.name}")

    def verify(self, file_path: Path) -> bool:
        """Check file integrity by comparing the current signature with the expected one."""
        if not self.can_verify:
            logging.warning("[SECURITY] Public key not available. Cannot verify signature.")
            return False
        
        clean_bytes, signature = self._get_clean_content_and_signature(file_path)
        
        if not signature:
            logging.warning(f"[SECURITY] No signature found in: {file_path.name}")
            return False
                
        try:
            sig_bytes = bytes.fromhex(signature)
            if self.public_key.verify(sig_bytes, clean_bytes):
                logging.info(f"[SECURITY] Signature valid for: {file_path.name}")
                return True
        except (BadSignatureError, ValueError):
            pass
        logging.error(f"[SECURITY] Signature verification failed for: {file_path.name}")
        return False
    
def verify_file_interactive(file_path: Path, verbose: bool = False) -> None:
    verifier = SignatureVerifier()
    if verifier.verify(file_path):
        print(f"File '{file_path.name}' is valid.")
        return
    
    title = file_path.stem
    url = ""
    
    try:
        with open(file_path, "rb") as f:
            data = tomli.load(f)
            title = data.get("title", title)
            url = data.get("url", "")
            if url == "":
                repos = data.get("installation", {}).get("git_repos", [])
                if repos:
                    url = repos[0].get("url", "")
    except Exception as e:
        pass

    typer.secho("\n" + "!" * 60, fg=typer.colors.RED)
    typer.secho(
        " [SECURITY WARNING] SIGNATURE VERIFICATION FAILED",
        fg=typer.colors.RED,
        bold=True,
    )
    typer.secho("!" * 60, fg=typer.colors.RED)
    typer.echo(f" File: {file_path}")
    typer.echo(f" Method: {title}")
    typer.echo(f" Origin: {url}")
    typer.echo(" This file may have been modified or comes from an untrusted source.")
    typer.secho("!" * 60 + "\n", fg=typer.colors.RED)

    if not typer.confirm("Do you want to proceed anyway?", default=False):
        logging.error("Operation aborted by user due to security check.")
        raise typer.Abort()

    logging.warning(f"User confirmed usage of unverified file: {file_path}")

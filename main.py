import typer
import logging
import tomli
import tomli_w
from pathlib import Path
from typing_extensions import Annotated
from typing import List, Optional
import subprocess
import os
import re
import shlex
import shutil
import sys
import json

from core.runner import PipelineRunner
from core.installer import MethodInstaller, remove_shared_entries

from core.validation import Validator
from core.utils import setup_logging, get_or_download_pixi, verify_file_interactive, get_dir_size

app = typer.Typer(help="Modular Pipeline for Gaussian SPlatting.")
methods_app = typer.Typer(help="Install, validate, remove and execute methods in various pipelines.")
app.add_typer(methods_app, name="methods")

# Definiamo i percorsi radice
PROJECT_ROOT = Path(__file__).parent.resolve()
METHODS_DIR = PROJECT_ROOT / "methods"
ENVS_DIR = PROJECT_ROOT / ".envs"  # Cartella dove Pixi crea gli ambienti
VENDOR_DIR = PROJECT_ROOT / "vendor"  # Cartella per i repository clonati

LOG_ALLOWLIST = [
    "CustomValidLog",
    "CustomInstallLog",
    "CustomRunLog",
    "CustomValidationLog",
]


def _find_manifest(method_name: str) -> Path:
    """Helper to find the .toml file."""
    candidates = [
        (METHODS_DIR / "preprocess" / (method_name + ".toml")),
        (METHODS_DIR / "sfm" / (method_name + ".toml")),
        (METHODS_DIR / "splat" / (method_name + ".toml")),
    ]
    for p in candidates:
        if p.exists():
            return p

    typer.secho(
        f"Metodo '{method_name}' non trovato in {METHODS_DIR}", fg=typer.colors.RED
    )
    raise typer.Abort()


@app.command()
def run(
    config_file: Annotated[
        Path, typer.Argument(help="Path to the .toml file for the pipeline.")
    ],
    input_file: Annotated[
        Path, typer.Option("--input", "-i", help="[Override] Input file path.")
    ] = None,
    output_dir: Annotated[
        Path, typer.Option("--output", "-o", help="[Override] Main Output Directory.")
    ] = None,
    verbose: Annotated[
        bool, typer.Option("--verbose", "-v", help="Enable Verbose logging.")
    ] = False,
    restart: Annotated[
        bool, typer.Option("--restart", "-r", help="Restart the pipeline from the start (delete everything in the output directory).")
    ] = False,
    set_params: Annotated[
        Optional[List[str]], 
        typer.Option("--set", "-s", help="Override params specified in the pipeline file (es. --set iterations=1000).")
    ] = None,
    show_info: Annotated[
        bool, typer.Option("--info", help="Show the pipeline overrideable parameters.")
    ] = False,
    isGui: Annotated[
        bool, typer.Option("--gui", help="Flag to indicate if running from the GUI (disables interactive file verification).")
    ] = False,
):
    """Execute the pipeline defined in the given TOML configuration file."""
    logger = setup_logging(
        level=logging.INFO,
        verbose=verbose,
        allowList=LOG_ALLOWLIST,
    )    
    
    overrides = {}
    if input_file:
        overrides["input_file"] = str(input_file.resolve())
    if output_dir:
        overrides["output_dir"] = str(output_dir.resolve())
    if restart:
        overrides["restart"] = True


    if set_params:
        for param in set_params:
            if "=" not in param:
                logger.warning(f"Malformed Parameter ignored '{param}'. Use KEY=VALUE.")
                continue
            key, val = param.split("=", 1)
            # Values end up interpolated into the shell commands of the method
            # TOMLs: refuse anything that could break out of them.
            if isinstance(val, str) and re.search(r"[;&|`<>\\\"\']|\$\(", val):
                logger.error(
                    f"Refusing unsafe parameter value for '{key}': "
                    f"shell metacharacters are not allowed in --set values."
                )
                continue
            if val.lower() == "true": val = True
            elif val.lower() == "false": val = False
            elif val.isdigit(): val = int(val)
            else:
                try:
                    val = float(val)
                except ValueError:
                    pass 
            overrides[key] = val
            
    if not isGui:
        verify_file_interactive(config_file, verbose=verbose)

    try:
        # Passiamo overrides direttamente nel costruttore
        runner = PipelineRunner(str(config_file), overrides=overrides, verbose=verbose)
        
        if show_info:
            runner.print_help()
            return

        runner.run()
        
        logger.success("Pipeline completed successfully")

    except Exception as e:
        logger.error(f"Critical Error during execution: {e}")
        logger.error("Pipeline Failed.")
        raise typer.Abort()
    
@app.command("web")
def start_web_interface(
    host: Annotated[str, typer.Option("--host", help="Bind address. Keep 127.0.0.1 unless you know what you are doing.")] = "127.0.0.1",
    port: Annotated[int, typer.Option("--port", help="Port for the web interface.")] = 8501,
):
    """Start the FastAPI web interface for managing pipelines and methods."""
    logger = setup_logging(level=logging.INFO, allowList=LOG_ALLOWLIST)
    try:
        import uvicorn
        from core.gui.server import app as web_app
    except ImportError as e:
        logger.error(f"Missing dependencies for the web interface: {e}. Run 'pip install fastapi uvicorn python-multipart'.")
        raise typer.Abort()

    try:
        logger.info(f"Starting Web Interface on http://{host}:{port} ...")
        uvicorn.run(web_app, host=host, port=port, log_level="warning")
    except Exception as e:
        logger.error(f"Failed to start web interface: {e}")
        raise typer.Abort()


@methods_app.command("install")
def install_method(
    method_name: Annotated[
        str,
        typer.Argument(
            help="Name of the method to install (es. 'colmap' o 'sfm/colmap')."
        ),
    ],
    verbose: Annotated[
        bool, typer.Option("--verbose", "-v", help="Enable verbose logging.")
    ] = False,
    force: Annotated[
        bool, typer.Option("--force", help="Skip signature verification warnings (use at your own risk).")
    ] = False,
):
    """Install a method"""
    logger = setup_logging(
        level=logging.INFO,
        verbose=verbose,
        allowList=LOG_ALLOWLIST,
    )
    
    method_path = _find_manifest(method_name)
    
    verify_file_interactive(method_path, verbose=verbose, assume_yes=force)

    try:
        logger.info(f"Loading configuration from {method_path}...")

        with open(method_path, "rb") as f:
            method_config = tomli.load(f)

        # Definiamo il percorso dell'ambiente
        # Usiamo il titolo del metodo o il nome del file per la cartella env
        safe_name = (
            method_config.get("title", method_path.stem).replace(" ", "_").replace("-", "_").lower()
        )
        env_path = ENVS_DIR / safe_name

        logger.info(f"Installing tool env in: {env_path}")

        #Inizializziamo il nuovo Installer Pixi
        #Passiamo il dict di config e la root del progetto
        installer = MethodInstaller(method_config, PROJECT_ROOT, verbose=verbose)

        installer.install(env_path)

        logger.success(f"'{method_name}' installation completed successfully!")
        
    except Exception as e:
        logger.error(f"Installation Failed: {e}")
        logger.error(f"'{method_name}' installation failed.")
        raise typer.Abort()


@methods_app.command("uninstall")
def uninstall_method(
    method_name: Annotated[
        str,
        typer.Argument(help="Name of the method to remove."),
    ] = None,
    all: Annotated[
        bool, typer.Option("--all", help="Uninstall all methods.")
    ] = False,
    yes: Annotated[
        bool, typer.Option("--yes", "-y", help="Skip confirmation prompt.")
    ] = False,
    verbose: Annotated[
        bool, typer.Option("--verbose", "-v", help="Enable verbose logging.")
    ] = False,
    subcall: Annotated[
        bool, typer.Option(hidden = True)
    ] = False,
    from_CLI: bool = True,
):
    """Delete a method, delete the env folder, any repository cloned, and shared entries."""
    logger = setup_logging(
        level=logging.INFO,
        verbose=verbose,
        allowList=LOG_ALLOWLIST,
    )
        
    if method_name is None and all:
        
        if from_CLI and not yes:
            if not typer.confirm(
                    "Are you sure you want to delete all methods?",
                    abort=True,
                ):
                    return

        installed_envs = [d for d in ENVS_DIR.iterdir() if d.is_dir() and (d / ".install_complete").exists()]
        for env_dir in installed_envs:
            method_id = env_dir.name
            logger.info(f"Uninstalling method '{method_id}'...")
            try:
                uninstall_method(method_name=method_id, verbose=verbose, subcall=True)
            except typer.Abort:
                logger.warning(f"Skipping '{method_id}': no matching manifest found.")
        return
    else:
        cfg = {}
        method_id = method_name
        vendor_dirs = []
        env_path = ENVS_DIR / method_name.replace(" ", "_").replace("-", "_").lower()
        try:
            method_path = _find_manifest(method_name)
        except typer.Abort:
            # No manifest: allow removing an orphan environment by name
            logger.warning(
                f"No manifest found for '{method_name}'. "
                f"Falling back to environment folder '{env_path.name}'."
            )
        else:
            try:
                with open(method_path, "rb") as f:
                    cfg = tomli.load(f)
                method_id = method_path.stem
                env_name = cfg.get("title", method_path.stem).replace(" ", "_").replace("-", "_").lower()
                env_path = ENVS_DIR / env_name

                for repo in cfg.get("installation", {}).get("git_repos", []):
                    dir = repo.get("path")
                    if dir:
                        vendor_dirs.append(VENDOR_DIR / dir)
            except (OSError, tomllib.TOMLDecodeError) as e:
                logger.warning(
                    f"Could not load manifest for '{method_name}' ({e}). "
                    f"Falling back to environment folder '{env_path.name}'."
                )

        if not env_path.exists():
            logger.warning(f"No environment found in {env_path}")
            return

        if not subcall:
            if from_CLI and not yes:
                if not typer.confirm(
                    f"Are you sure you want to delete '{method_id}'?",
                    abort=True,
                ):
                    return
        else:
            logger.info(f"Deleting '{method_id}'...")

        try:
            import shutil
            
            if cfg.get("installation", {}).get("shared_env", False):
                logger.info("Deleting shared entries from pixi.toml...")
                remove_shared_entries(PROJECT_ROOT, method_id, logger)

            logger.info(f"Rimozione cartella {env_path}...")
            shutil.rmtree(env_path)
            logger.success(
                f"'{method_name}' removal completed!"
            )
            
            logger.info("Removing vendor directories...")
            for vdir in vendor_dirs:
                if vdir.exists():
                    logger.info(f"Rimozione {vdir}...")
                    shutil.rmtree(vdir)

        except Exception as e:
            logger.error(f"Removal failed: {e}")
            logger.error(
                f"'{method_name}' removal failed."
            )
            raise typer.Abort()
    
@methods_app.command("validate")
def validate(
    method_name: Annotated[
        str, typer.Argument(help="Name of the method."),
    ] = None,
    all: Annotated[
        bool, typer.Option("--all", help="Validate all installed methods.")
    ] = False,
    verbose: Annotated[
        bool, typer.Option("--verbose", "-v", help="Enable verbose logging.")
    ] = False,
    force: Annotated[
        bool, typer.Option("--force", help="Skip signature verification warnings (use at your own risk).")
    ] = False,
):
    """Execute the specified validation command from the TOML to check if the method is correctly installed."""
    
    logger = setup_logging(
        level=logging.INFO,
        verbose=verbose,
        allowList=LOG_ALLOWLIST,
    )

    validator = Validator(METHODS_DIR, verbose)
    
    if not all and method_name is not None:
        method_path = _find_manifest(method_name)
        verify_file_interactive(method_path, verbose=verbose, assume_yes=force)
        target_id = Path(method_name).stem
        validator.validate_method(target_id, all=False)
    elif all:
        validator.validate_installed()
    else:
        logger.warning("Specify a method name or use --all to validate all installed methods.")


@methods_app.command("list")
def list_methods():
    """List all available methods specifing wich one are installed or not."""
    validator = Validator(METHODS_DIR)
    registry = validator.registry
    total_tools = len(registry)
    
    installed_count = 0
    total_bytes = 0
    
    if ENVS_DIR.exists():
        for child in ENVS_DIR.iterdir():
            if child.is_dir():
                if (child / ".install_complete").exists():
                    installed_count += 1
                total_bytes += get_dir_size(child)
                
    typer.secho(f"\nAvailable Methods: {total_tools} | Installed: {installed_count} | Total Size: {_readable(total_bytes)}", bold=True)

    
    typer.secho(f"\n{'METHOD':<25} {'STATE':<12} {'DESCRIPTION'}", bold=True, underline=True)

    for method_id, config in sorted(registry.items()):
        metadata = config.get("__metadata__", {})
        safe_name = metadata.get("title", method_id).replace(" ", "_").lower()
        env_path = ENVS_DIR / safe_name
        is_installed = (env_path / ".install_complete").exists()
        
        status_str = "INSTALLED" if is_installed else "NOT INSTALLED"
        status_color = typer.colors.GREEN if is_installed else typer.colors.RED
        
        desc = metadata.get("description", "N/A")
        if len(desc) > 60:
            desc = desc[:57] + "..."
            
        typer.secho(f"{method_id:<25} ", nl=False, bold=True)
        typer.secho(f"{status_str:<12} ", fg=status_color, nl=False)
        typer.echo(f"{desc}")
        
        meta_info = []
        if is_installed:
            meta_info.append(f"Path: ./.envs/{safe_name}")
        if "url" in config:
            meta_info.append(f"URL: {metadata['url']}")
            
        if meta_info:
            typer.secho(f"   └── {', '.join(meta_info)}", fg=typer.colors.BRIGHT_BLACK)
            

@methods_app.command("help")
def list_arguments(
    method_name: Annotated[
        str, typer.Argument(help="Name of the method.")
    ]
):
    """List the help command defined in the method TOML and execute it to show available parameters."""        
    try:
        logger = setup_logging(
            level=logging.INFO,
            allowList=LOG_ALLOWLIST,
        )    
        
        method_path = _find_manifest(method_name)
        with open(method_path, "rb") as f:
            cfg = tomli.load(f)
        env_name = cfg.get("title", method_path.stem).replace(" ", "_").replace("-", "_").lower()
        env_path = ENVS_DIR / env_name
        
        manifest_path = env_path / "pixi.toml"
        shared_env_name = None
        if not manifest_path.exists():
            shared_meta = env_path / "shared_env.json"
            if shared_meta.exists():
                with open(shared_meta, "r") as f:
                        meta = json.load(f)
                manifest_path = Path(meta.get("manifest_path", "")) if meta.get("manifest_path") else manifest_path
                shared_env_name = meta.get("env_name", None)
            else:
                logger.warning(f"No pixi.toml found for '{method_name}' in {env_path}")
                return
                
        help_section = cfg.get("execution", {}).get("help", {})
        help_command = help_section.get("help_command") if help_section else None
        
        if not help_command:
            logger.warning("No help_command found in the specified TOML")
            return
            
        vendor_str = str(VENDOR_DIR).replace("\\", "/")
        root_str = str(PROJECT_ROOT).replace("\\", "/")
        cmd_str = help_command.replace("{{method_vendor_dir}}", vendor_str)
        cmd_str = cmd_str.replace("{{project_root}}", root_str)
        
        pixi_exe = get_or_download_pixi(PROJECT_ROOT)
        args = shlex.split(cmd_str, posix=os.name != "nt")
        
        full_cmd = [str(pixi_exe), "run", "--manifest-path", str(manifest_path)]
        if shared_env_name:
            full_cmd += ["-e", shared_env_name]
        full_cmd += args
        
        logger.info(f"Executing: {cmd_str}\n")
        subprocess.check_call(full_cmd, cwd=PROJECT_ROOT)
            
    except Exception as e:
        logger.error(f"[ERROR] Error retrieving all methods: {e}")

def _readable(n: int) -> str:
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if n < 1024:
            return f"{n:.2f} {unit}"
        n /= 1024
    return f"{n:.2f} PB"

if __name__ == "__main__":
    app()

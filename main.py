import typer
import logging
import tomli
import tomli_w
from pathlib import Path
from typing_extensions import Annotated
from typing import List, Optional
import subprocess
import os
import shlex

from core.runner import PipelineRunner
from core.installer import MethodInstaller

from core.validation import Validator
from core.utils import setup_logging, get_or_download_pixi

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
    candidates = list(METHODS_DIR.rglob(f"{method_name}.toml"))
    if not candidates:
        possible_path = METHODS_DIR / f"{method_name}.toml"
        if possible_path.exists():
            candidates = [possible_path]

    if not candidates:
        typer.secho(
            f"Metodo '{method_name}' non trovato in {METHODS_DIR}", fg=typer.colors.RED
        )
        raise typer.Abort()

    return candidates[0]

# Helper method to remove shared entries from shared pixi.toml
def _remove_shared_entries(method_id: str):
    shared_manifest = ENVS_DIR / "_shared" / "pixi.toml"
    shared_envs_dir = ENVS_DIR / "_shared" / ".pixi" / "envs"
    if not shared_manifest.exists():
        return
    
    with open(shared_manifest, "rb") as f:
        pixi = tomli.load(f)
        
    tool_feature = f"tool-{method_id}"
    envs = pixi.get("environments", {}) or {}
    features = pixi.get("feature", {}) or {}
    
    envs_to_remove = [
        name for name, cfg in envs.items()
        if tool_feature in cfg.get("features", [] or [])
    ]
    for name in envs_to_remove:
        del envs[name]
        
    if tool_feature in features:
        del features[tool_feature]
        
    used_features = set()
    for cfg in envs.values():
        used_features.update(cfg.get("features", []) or [])
        
    base_features = [k for k in features.keys() if k.startswith("base-")]
    for bf in base_features:
        if bf not in used_features:
            del features[bf]
        
    pixi["environments"] = envs
    pixi["feature"] = features
    
    with open(shared_manifest, "wb") as f:
        tomli_w.dump(pixi, f)
        
    if shared_envs_dir.exists():
        for env_name in envs_to_remove:
            env_path = shared_envs_dir / env_name
            if env_path.exists():
                import shutil
                shutil.rmtree(env_path)
                
        for env_dir in shared_envs_dir.iterdir():
            if env_dir.is_dir() and env_dir.name not in envs:
                shutil.rmtree(env_dir)


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
            if val.lower() == "true": val = True
            elif val.lower() == "false": val = False
            elif val.isdigit(): val = int(val)
            else:
                try:
                    val = float(val)
                except ValueError:
                    pass 
            overrides[key] = val

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
):
    """Install a method"""
    logger = setup_logging(
        level=logging.INFO,
        verbose=verbose,
        allowList=LOG_ALLOWLIST,
    )
    
    method_path = _find_manifest(method_name)

    try:
        # typer.echo(f"Loading configuration from {method_path}...")
        logger.info(f"Loading configuration from {method_path}...")

        with open(method_path, "rb") as f:
            method_config = tomli.load(f)

        # Definiamo il percorso dell'ambiente
        # Usiamo il titolo del metodo o il nome del file per la cartella env
        safe_name = (
            method_config.get("title", method_path.stem).replace(" ", "_").lower()
        )
        env_path = ENVS_DIR / safe_name

        logger.info(f"Installing tool env in: {env_path}")

        #Inizializziamo il nuovo Installer Pixi
        # Nota: Passiamo il dict di config e la root del progetto
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
        
        if not from_CLI:
            if not typer.confirm(
                    "Are you sure you want to delete all methods?",
                    abort=True,
                ):
                    return

        installed_envs = [d for d in ENVS_DIR.iterdir() if d.is_dir() and (d / ".install_complete").exists()]
        for env_dir in installed_envs:
            method_id = env_dir.name
            logger.info(f"Uninstalling method '{method_id}'...")
            uninstall_method(method_name=method_id, verbose=verbose, subcall=True)
        return
    else:
        try:
            method_path = _find_manifest(method_name)
            with open(method_path, "rb") as f:
                cfg = tomli.load(f)
            method_id = method_path.stem
            env_name = cfg.get("title", method_path.stem).replace(" ", "_").lower()
            env_path = ENVS_DIR / env_name
            
            vendor_dirs = []
            for repo in cfg.get("installation", {}).get("git_repos", []):
                dir = repo.get("path")
                if dir:
                    vendor_dirs.append(VENDOR_DIR / dir)            
        except:
            # Fallback: prova a usare il method_name direttamente se il file non si trova
            env_path = ENVS_DIR / method_name.replace(" ", "_").lower()

        if not env_path.exists():
            logger.warning(f"No environment found in {env_path}")
            return

        if not subcall:
            if not from_CLI:
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
                _remove_shared_entries(method_id)

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
):
    """Execute the specified validation command from the TOML to check if the method is correctly installed."""
    
    logger = setup_logging(
        level=logging.INFO,
        verbose=verbose,
        allowList=LOG_ALLOWLIST,
    )

    validator = Validator(METHODS_DIR, verbose)
    
    if not all and method_name is not None:
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
    
    typer.secho(f"\n{'METHOD':<25} {'STATE':<12} {'DESCRIPTION'}", bold=True, underline=True)

    for method_id, config in sorted(registry.items()):
        safe_name = config.get("title", method_id).replace(" ", "_").lower()
        env_path = ENVS_DIR / safe_name
        is_installed = (env_path / ".install_complete").exists()
        
        status_str = "INSTALLED" if is_installed else "NOT INSTALLED"
        status_color = typer.colors.GREEN if is_installed else typer.colors.RED
        
        desc = config.get("description", "N/A")
        if len(desc) > 60:
            desc = desc[:57] + "..."
            
        typer.secho(f"{method_id:<25} ", nl=False, bold=True)
        typer.secho(f"{status_str:<12} ", fg=status_color, nl=False)
        typer.echo(f"{desc}")
        
        meta_info = []
        if is_installed:
            meta_info.append(f"Path: ./.envs/{safe_name}")
        if "url" in config:
            meta_info.append(f"URL: {config['url']}")
            
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
        env_name = cfg.get("title", method_path.stem).replace(" ", "_").lower()
        env_path = ENVS_DIR / env_name
        
        if not(env_path / "pixi.toml").exists():
            logger.warning(f"Environment '{env_name}' not found. First esecute the install command")
            return
        
        help_section = cfg.get("execution", {}).get("help", {})
        help_command = help_section.get("help_command") if help_section else None
        
        if not help_command:
            logger.waring("No help_command found in the specified TOML")
            
        vendor_str = str(VENDOR_DIR).replace("\\", "/")
        root_str = str(PROJECT_ROOT).replace("\\", "/")
        cmd_str = help_command.replace("{{method_vendor_dir}}", vendor_str)
        cmd_str = cmd_str.replace("{{project_root}}", root_str)
        
        pixi_exe = get_or_download_pixi(PROJECT_ROOT)
        args = shlex.split(cmd_str, posix=os.name != "nt")
        full_cmd = [str(pixi_exe), "run", "--manifest-path", str(env_path / "pixi.toml")] + args
        
        logger.info(f"Executing: {cmd_str}\n")
        subprocess.check_call(full_cmd, cwd=PROJECT_ROOT)
            
    except Exception as e:
        logger.error(f"[ERROR] Cannota invoke --help parameter on specified script: {e}")



if __name__ == "__main__":
    app()

import typer
import logging
from pathlib import Path
from typing_extensions import Annotated

from core.runner import PipelineRunner
from core.installer import MethodInstaller
from core.uninstaller import MethodUninstaller  # NUOVO IMPORT
from core.validation import Validator
from core.utils import setup_logging

# --- Setup App ---
app = typer.Typer(help="Pipeline 3D modulare con ambienti locali isolati.")
methods_app = typer.Typer(help="Installa, disinstalla e valida i metodi (tool).")
app.add_typer(methods_app, name="methods")

# Definiamo i percorsi radice
PROJECT_ROOT = Path(__file__).parent.resolve()
METHODS_DIR = PROJECT_ROOT / "methods"
PIPELINES_DIR = PROJECT_ROOT / "pipelines"


# Funzione helper per trovare un manifest
def _find_manifest(method_name: str) -> Path:
    validator = Validator(METHODS_DIR)
    try:
        method_path, _ = validator.find_method_manifest(method_name)
        if not method_path:
            raise FileNotFoundError
        return method_path
    except (FileNotFoundError, KeyError):
        typer.secho(
            f"File manifest per '{method_name}' non trovato in {METHODS_DIR}/*/",
            fg=typer.colors.RED,
        )
        raise typer.Abort()


@app.command()
def run(
    config_file: Annotated[
        Path, typer.Argument(help="Percorso al file .toml della pipeline.")
    ],
    input_file: Annotated[
        Path, typer.Option("--input", "-i", help="[Override] File di input.")
    ] = None,
    output_dir: Annotated[
        Path, typer.Option("--output", "-o", help="[Override] Directory di output.")
    ] = None,
    verbose: Annotated[
        bool, typer.Option("--verbose", "-v", help="Log di DEBUG dettagliati.")
    ] = False,
    visualize: Annotated[bool, typer.Option("--rerun", help="Abilita Rerun.")] = False,
):
    """Esegue una pipeline definita da un file di configurazione."""
    setup_logging(level=logging.DEBUG if verbose else logging.INFO)

    try:
        override_args = {}
        if input_file:
            override_args["input_file"] = str(input_file)
        if output_dir:
            override_args["output_dir"] = str(output_dir)
        if verbose:
            override_args["verbose"] = True
        if visualize:
            override_args["visualize_rerun"] = True
        
        runner = PipelineRunner(config_file, METHODS_DIR, override_args=override_args)

        # Inietta la root del progetto nel context per trovare ./.envs
        runner.context.set("project_root", str(PROJECT_ROOT))

        runner.execute()
        typer.secho(f"Pipeline completata con successo!", fg=typer.colors.GREEN)

    except Exception as e:
        logging.error(f"Errore critico: {e}", exc_info=verbose)
        typer.secho(f"Pipeline fallita.", fg=typer.colors.RED)
        raise typer.Abort()


@methods_app.command("install")
def install_method(
    method_name: Annotated[
        str, typer.Argument(help="Nome del metodo da installare (es. 'mast3r_glomap').")
    ],
    verbose: Annotated[
        bool, typer.Option("--verbose", "-v", help="Mostra output dettagliato.")
    ] = False,
):
    """Installa un metodo creando un ambiente Conda locale in ./.envs/"""
    setup_logging(level=logging.DEBUG if verbose else logging.INFO)
    method_path = _find_manifest(method_name)

    try:
        typer.echo(f"Avvio installazione per '{method_name}' da {method_path}...")
        installer = MethodInstaller(method_path)
        installer.install(verbose=verbose)
        typer.secho(
            f"Installazione di '{method_name}' completata!", fg=typer.colors.GREEN
        )

    except Exception as e:
        logging.error(f"Installazione fallita: {e}", exc_info=verbose)
        typer.secho(f"Installazione di '{method_name}' fallita.", fg=typer.colors.RED)
        raise typer.Abort()


# --- (NUOVO) Comando UNINSTALL ---
@methods_app.command("uninstall")
def uninstall_method(
    method_name: Annotated[
        str,
        typer.Argument(help="Nome del metodo da disinstallare (es. 'mast3r_glomap')."),
    ],
    verbose: Annotated[
        bool, typer.Option("--verbose", "-v", help="Mostra output dettagliato.")
    ] = False,
):
    """Rimuove un metodo: elimina il suo ambiente Conda locale e i file (es. submodules)."""
    setup_logging(level=logging.DEBUG if verbose else logging.INFO)
    method_path = _find_manifest(method_name)

    if not typer.confirm(
        f"Sei sicuro di voler disinstallare '{method_name}'? Questo rimuoverà ./.envs/{method_name} e i suoi sottomoduli.",
        abort=True,
    ):
        return

    try:
        typer.echo(f"Avvio disinstallazione per '{method_name}'...")
        uninstaller = MethodUninstaller(method_path)
        uninstaller.uninstall(verbose=verbose)
        typer.secho(
            f"Disinstallazione di '{method_name}' completata!", fg=typer.colors.GREEN
        )

    except Exception as e:
        logging.error(f"Disinstallazione fallita: {e}", exc_info=verbose)
        typer.secho(
            f"Disinstallazione di '{method_name}' fallita.", fg=typer.colors.RED
        )
        raise typer.Abort()


@methods_app.command("list")
def list_methods():
    """Elenca tutti i metodi disponibili dai manifest."""
    Validator(METHODS_DIR).list_methods()


@methods_app.command("validate")
def validate_methods(
    method_name: str = typer.Argument(
        None,
        help="Il nome del singolo metodo da validare. Se non specificato, valida tutti i metodi installati.",
    ),
    verbose: bool = typer.Option(
        False, "--verbose", "-v", help="Mostra output dettagliato dei comandi."
    ),
):
    """Valida l'installazione di uno o tutti i metodi registrati."""
    setup_logging(level=logging.DEBUG if verbose else logging.INFO)
    validator = Validator(METHODS_DIR)
    if method_name:
        success = validator.validate_single(method_name, verbose=verbose)
    else:
        success = validator.validate_installed(verbose=verbose)

    if success:
        typer.secho("Tutti i metodi sono validi!", fg=typer.colors.GREEN)
    else:
        typer.secho("Alcuni metodi non sono validi.", fg=typer.colors.RED)
        raise typer.Exit(code=1)


if __name__ == "__main__":
    app()

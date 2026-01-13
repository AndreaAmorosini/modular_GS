import typer
import logging
import tomli
from pathlib import Path
from typing_extensions import Annotated

# Importiamo le nuove classi aggiornate per Pixi
from core.runner import PipelineRunner
from core.installer import MethodInstaller

# Nota: MethodUninstaller per Pixi è banale (rimozione cartella),
# possiamo gestirlo direttamente qui o aggiornare la classe se esiste.
# Per semplicità lo gestiamo qui o assumiamo una classe compatibile.
from core.validation import Validator
from core.utils import setup_logging

# --- Setup App ---
app = typer.Typer(help="Pipeline 3D modulare con ambienti locali Pixi.")
methods_app = typer.Typer(help="Installa, disinstalla e valida i metodi (tool).")
app.add_typer(methods_app, name="methods")

# Definiamo i percorsi radice
PROJECT_ROOT = Path(__file__).parent.resolve()
METHODS_DIR = PROJECT_ROOT / "methods"
ENVS_DIR = PROJECT_ROOT / ".envs"  # Cartella dove Pixi crea gli ambienti


def _find_manifest(method_name: str) -> Path:
    """Helper per trovare il file .toml di un metodo."""
    # Cerchiamo ricorsivamente o direttamente in methods/
    # Logica semplificata rispetto al validatore completo
    candidates = list(METHODS_DIR.rglob(f"{method_name}.toml"))
    # Cerca anche se method_name è un path parziale (es. splat/nerfstudio)
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
):
    """Esegue una pipeline definita da un file di configurazione."""
    setup_logging(level=logging.DEBUG if verbose else logging.INFO)

    try:
        # PipelineRunner ora si aspetta solo il path della config
        # Le logiche di override andrebbero gestite dentro o passando un context modificato
        # Per ora manteniamo la compatibilità base
        runner = PipelineRunner(str(config_file))

        # Gestione base degli override iniettando nel context se supportato
        if output_dir:
            runner.context.output_dir = output_dir
        if input_file:
            runner.context.input_file = input_file

        runner.run()
        typer.secho(f"Pipeline completata con successo!", fg=typer.colors.GREEN)

    except Exception as e:
        logging.error(f"Errore critico: {e}", exc_info=verbose)
        typer.secho(f"Pipeline fallita.", fg=typer.colors.RED)
        raise typer.Abort()


@methods_app.command("install")
def install_method(
    method_name: Annotated[
        str,
        typer.Argument(
            help="Nome del metodo da installare (es. 'colmap' o 'sfm/colmap')."
        ),
    ],
    verbose: Annotated[
        bool, typer.Option("--verbose", "-v", help="Mostra output dettagliato.")
    ] = False,
):
    """Installa un metodo creando un ambiente Pixi locale in ./envs/"""
    setup_logging(level=logging.DEBUG if verbose else logging.INFO)

    method_path = _find_manifest(method_name)

    try:
        typer.echo(f"Caricamento configurazione da {method_path}...")

        # 1. Carichiamo la configurazione TOML (necessario per il nuovo Installer)
        with open(method_path, "rb") as f:
            method_config = tomli.load(f)

        # 2. Definiamo il percorso dell'ambiente
        # Usiamo il titolo del metodo o il nome del file per la cartella env
        safe_name = (
            method_config.get("title", method_path.stem).replace(" ", "_").lower()
        )
        env_path = ENVS_DIR / safe_name

        typer.echo(f"Installazione ambiente Pixi in: {env_path}")

        # 3. Inizializziamo il nuovo Installer Pixi
        # Nota: Passiamo il dict di config e la root del progetto
        installer = MethodInstaller(method_config, PROJECT_ROOT)

        # 4. Eseguiamo l'installazione
        installer.install(env_path)

        typer.secho(
            f"Installazione di '{method_name}' completata con successo!",
            fg=typer.colors.GREEN,
        )

    except Exception as e:
        logging.error(f"Installazione fallita: {e}", exc_info=verbose)
        typer.secho(f"Installazione di '{method_name}' fallita.", fg=typer.colors.RED)
        raise typer.Abort()


@methods_app.command("uninstall")
def uninstall_method(
    method_name: Annotated[
        str,
        typer.Argument(help="Nome del metodo da disinstallare."),
    ],
    verbose: Annotated[
        bool, typer.Option("--verbose", "-v", help="Mostra output dettagliato.")
    ] = False,
):
    """Rimuove un metodo: elimina la cartella dell'ambiente in ./envs/"""
    setup_logging(level=logging.DEBUG if verbose else logging.INFO)

    # Cerchiamo di dedurre il nome della cartella envs
    # Questo è un po' tricky senza ricaricare il toml, proviamo euristica o caricamento
    try:
        method_path = _find_manifest(method_name)
        with open(method_path, "rb") as f:
            cfg = tomli.load(f)
        env_name = cfg.get("title", method_path.stem).replace(" ", "_").lower()
        env_path = ENVS_DIR / env_name
    except:
        # Fallback: prova a usare il method_name direttamente se il file non si trova
        env_path = ENVS_DIR / method_name.replace(" ", "_").lower()

    if not env_path.exists():
        typer.secho(f"Nessun ambiente trovato in {env_path}", fg=typer.colors.YELLOW)
        return

    if not typer.confirm(
        f"Sei sicuro di voler eliminare l'ambiente Pixi in '{env_path}'?",
        abort=True,
    ):
        return

    try:
        import shutil

        typer.echo(f"Rimozione cartella {env_path}...")
        shutil.rmtree(env_path)
        typer.secho(
            f"Disinstallazione di '{method_name}' completata!", fg=typer.colors.GREEN
        )

    except Exception as e:
        logging.error(f"Disinstallazione fallita: {e}", exc_info=verbose)
        typer.secho(
            f"Disinstallazione di '{method_name}' fallita.", fg=typer.colors.RED
        )
        raise typer.Abort()


# Validator e List possono rimanere se core/validation.py è compatibile,
# altrimenti andrebbero adattati. Per ora li lasciamo.
@methods_app.command("list")
def list_methods():
    """Elenca tutti i metodi disponibili."""
    try:
        Validator(METHODS_DIR).list_methods()
    except Exception:
        # Fallback semplice se Validator non è aggiornato
        typer.echo("Metodi disponibili:")
        for p in METHODS_DIR.rglob("*.toml"):
            typer.echo(f" - {p.stem} ({p.relative_to(METHODS_DIR)})")


if __name__ == "__main__":
    app()

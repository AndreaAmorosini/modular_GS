import toml
import logging
import jinja2
import os
import platform
import tempfile
import shutil
import shlex
from pathlib import Path
from .utils import run_command
# L'import viene fatto localmente per evitare dipendenze circolari
# from .uninstaller import MethodUninstaller


class MethodInstaller:
    """Installa metodi creando ambienti Conda locali in ./.envs/"""

    def __init__(self, method_config_path: Path):
        self.config_path = method_config_path.resolve()
        self.config = toml.load(method_config_path)
        self.name = self.config["name"]
        self.logger = logging.getLogger(f"Installer.{self.name}")
        self.install_config = self.config.get("installation", {})

        # La root del progetto è la directory genitore di 'full_pipe_v2'
        self.project_root = self.config_path.parent.parent.parent.parent
        self.pipe_root = self.project_root / "full_pipe_v2"
        self.envs_dir = self.pipe_root / ".envs"
        self.envs_dir.mkdir(exist_ok=True)
        self.jinja_env = jinja2.Environment(loader=jinja2.BaseLoader())

    def _get_env_path(self) -> Path | None:
        """Restituisce il percorso assoluto dell'ambiente locale."""
        env_name = self.install_config.get("conda_env_name")
        if env_name:
            return (self.envs_dir / env_name).resolve()
        return None

    def _render_template(self, template_str: str, vars: dict) -> str:
        template = self.jinja_env.from_string(template_str)
        return template.render(vars)

    def _cleanup(self):
        """
        Esegue la pulizia completa del metodo in caso di installazione fallita.
        Riutilizza la logica di MethodUninstaller.
        """
        self.logger.warning(
            f"Installazione di '{self.name}' fallita o interrotta. Avvio pulizia..."
        )
        try:
            # Import locale per evitare dipendenze circolari
            from .uninstaller import MethodUninstaller

            uninstaller = MethodUninstaller(self.config_path)
            uninstaller.uninstall()
            self.logger.info(f"Pulizia per '{self.name}' completata.")
        except Exception as e:
            self.logger.error(f"Pulizia per '{self.name}' fallita: {e}")

    # --- FUNZIONE MODIFICATA ---
    def _run_docker_build(
        self, builder_config: dict, template_vars: dict, verbose: bool
    ) -> Path:
        """
        Esegue la compilazione in un container Docker isolato
        e ritorna il percorso alla directory con i wheel.
        """
        self.logger.info("Avvio build isolata con Docker...")

        # 1. Crea una directory di output temporanea sull'host
        host_output_dir = Path(tempfile.mkdtemp(prefix=f"docker_build_{self.name}_"))

        # 2. Prepara i volumi
        method_vendor_dir = Path(template_vars["method_vendor_dir"])
        volume_maps = (
            f'-v "{method_vendor_dir.resolve()}":/src:ro '
            f'-v "{host_output_dir.resolve()}":/output'
        )

        # 3. Prepara i comandi di setup (es. installare torch)
        setup_cmds = " && ".join(builder_config.get("setup_commands", []))
        if setup_cmds:
            setup_cmds = f"{setup_cmds} && "

        # 4. (MODIFICA) Prepara i comandi di build
        build_cmds = []
        build_dir_counter = 0
        for pkg_template in builder_config.get("build_pip_packages", []):
            
            # --- INIZIO LOGICA CONDIZIONALE ---
            if pkg_template.startswith("git+"):
                # CASO 1: È un URL Git.
                # Pip lo clonerà in una sua area /tmp scrivibile,
                # quindi non abbiamo problemi di read-only.
                self.logger.info(f"Docker Builder: Trovato URL Git: {pkg_template}")
                build_cmds.append(
                    f"pip wheel '{pkg_template}' -w /output --no-deps"
                )
            
            else:
                # CASO 2: È un percorso locale (es. {{method_vendor_dir}}).
                # Dobbiamo usare la logica di copia per evitare l'errore read-only.
                self.logger.info(f"Docker Builder: Trovato percorso locale: {pkg_template}")
                pkg_path_host = self._render_template(pkg_template, template_vars)
                src_path_in_container = pkg_path_host.replace(
                    str(method_vendor_dir), "/src"
                )

                # Definisci una directory di build temporanea e scrivibile DENTRO il container
                tmp_build_dir = f"/tmp/build_src_{build_dir_counter}"

                # 1. Copia i sorgenti read-only in un'area scrivibile
                build_cmds.append(f"cp -R '{src_path_in_container}' '{tmp_build_dir}'")
                # 2. Esegui pip wheel sulla *copia* scrivibile
                build_cmds.append(f"pip wheel '{tmp_build_dir}' -w /output --no-deps")

                build_dir_counter += 1
            # --- FINE LOGICA CONDIZIONALE ---

        full_build_cmd = " && ".join(build_cmds)
        if not full_build_cmd:
            raise ValueError("docker_builder non ha 'build_pip_packages' da compilare.")

        # 5. Prepara la correzione dei permessi
        host_user_id = os.getuid()
        host_group_id = os.getgid()
        chown_cmd = f"chown -R {host_user_id}:{host_group_id} /output"

        # 6. Costruisci il comando 'docker run' finale
        image = builder_config["image"]
        docker_command = (
            f"docker run --rm --gpus all {volume_maps} "
            f'{image} /bin/bash -c "set -e && {setup_cmds}{full_build_cmd} && {chown_cmd}"'
        )

        try:
            # Esegui il comando di build
            self.logger.info(f"Esecuzione build Docker: {docker_command}")
            run_command(docker_command, self.logger.name, verbose=verbose, shell=True)
            self.logger.info(
                f"Build Docker completata. Wheel salvati in {host_output_dir}"
            )
            return host_output_dir
        except Exception as e:
            self.logger.error(f"Build Docker fallita: {e}")
            shutil.rmtree(host_output_dir)  # Pulisci
            raise
    # --- FINE MODIFICA ---

    def _run_isolated_pip_install(
        self, env_path: Path, pkg_full_string: str, verbose: bool
    ):
        """
        Esegue un comando 'pip install' usando l'eseguibile python
        dell'ambiente e azzerando PYTHONPATH per un isolamento completo.
        """
        self.logger.info(f"Installazione pip isolata: {pkg_full_string}")
        python_executable = env_path / "bin" / "python"

        if not python_executable.exists():
            self.logger.error(f"Eseguibile Python non trovato in: {python_executable}")
            raise FileNotFoundError(f"Python non trovato in {python_executable}")

        # Prepara le variabili d'ambiente per l'isolamento
        env_vars = os.environ.copy()
        env_vars["PATH"] = f"{env_path / 'bin'}{os.pathsep}{env_vars.get('PATH', '')}"
        env_vars["PYTHONPATH"] = ""  # Isolamento CHIAVE

        # Logica di parsing robusta per flag e pacchetti
        parts = shlex.split(pkg_full_string)
        packages_to_install = []
        pip_flags = []

        i = 0
        while i < len(parts):
            part = parts[i]
            if part.startswith("--"):
                pip_flags.append(part)
                # Gestisce flag con argomento (es. --index-url <url>)
                if i + 1 < len(parts) and not parts[i + 1].startswith("-"):
                    pip_flags.append(parts[i + 1])
                    i += 1  # Salta l'argomento
            else:
                packages_to_install.append(shlex.quote(part))
            i += 1

        # Costruisce il comando
        cmd_list = [
            str(python_executable),
            "-s",  # Non aggiungere il site-packages dell'utente
            "-u",  # Unbuffered output
            "-m",
            "pip",
            "install",
            "-v",
        ]
        cmd_list.extend(packages_to_install)
        cmd_list.extend(pip_flags)

        # Riassembla come stringa per shell=True
        # Aggiungiamo --no-deps per i wheel locali per forzare l'uso
        # delle dipendenze già installate (torch).
        if any(pkg.endswith(".whl") for pkg in packages_to_install):
            cmd_list.append("--no-deps")
            self.logger.info("Aggiunto flag --no-deps per l'installazione del wheel.")

        cmd = " ".join(f'"{part}"' if " " in part else part for part in cmd_list)

        run_command(cmd, self.logger.name, verbose, shell=True, env=env_vars)

    def install(self, verbose=False):
        self.logger.info(f"Inizio installazione di '{self.name}'...")
        env_path = self._get_env_path()
        method_vendor_dir = self.pipe_root / "vendor" / self.name
        built_wheels_dir = None  # Per la pulizia finale

        # Controlla se l'ambiente esiste già.
        if env_path and env_path.exists():
            self.logger.info(
                f"Ambiente Conda '{env_path.name}' esiste già. Considero il metodo installato."
            )
            return

        try:
            template_vars = {
                "env_path": str(env_path) if env_path else "",
                "method_vendor_dir": str(method_vendor_dir),
            }

            # 1. Git Repos (SEMPRE PRIMA)
            for repo in self.install_config.get("git_repos", []):
                method_vendor_dir.mkdir(parents=True, exist_ok=True)
                path = method_vendor_dir / repo["path"]
                if not path.exists():
                    self.logger.info(f"Clonazione repository da {repo['url']}...")
                    recursive_flag = (
                        "--recursive" if repo.get("recursive", False) else ""
                    )
                    branch_flag = (
                        f"--branch {repo['branch']}" if repo.get("branch") else ""
                    )
                    cmd = (
                        f"git clone {branch_flag} {recursive_flag} {repo['url']} {path}"
                    )
                    run_command(cmd, self.logger.name, verbose, shell=True)

            if env_path:
                # --- CASO 1: AMBIENTE DEDICATO (.envs/...) ---

                # 1.A Creazione Ambiente Conda
                self.logger.info(f"Creazione ambiente Conda da .toml: {env_path.name}")
                channels = " ".join(
                    [f"-c {c}" for c in self.install_config.get("conda_channels", [])]
                )
                packages_list = self.install_config.get("conda_packages", [])
                if platform.system() == "Linux":
                    self.logger.info(
                        "Aggiunta dei compilatori nativi (c-compiler, cxx-compiler)."
                    )
                    packages_list.extend(["c-compiler", "cxx-compiler"])
                    if "conda-forge" not in channels:
                        channels = f"-c conda-forge {channels}"

                packages = " ".join(f'"{p}"' for p in packages_list)

                if packages:
                    cmd = f"conda create --prefix {env_path} {channels} {packages} -y"
                    run_command(cmd, self.logger.name, verbose, shell=True)

                # 1.B Esecuzione Docker Builder (se richiesto)
                # Questo produce solo i file .whl, non li installa
                docker_builder_config = self.install_config.get("docker_builder")

                if docker_builder_config and docker_builder_config.get("enabled"):
                    self.logger.info("Avvio fase di build Docker...")
                    built_wheels_dir = self._run_docker_build(
                        docker_builder_config, template_vars, verbose
                    )

                # 1.C Installazione Pacchetti Pip (Dipendenze come torch)
                self.logger.info("Installazione dipendenze pip (es. torch)...")
                for pkg_template in self.install_config.get("pip_packages", []):
                    pkg_full_string = self._render_template(pkg_template, template_vars)
                    self._run_isolated_pip_install(env_path, pkg_full_string, verbose)

                # 1.D Installazione Wheel compilati (se presenti)
                # Ora che torch è installato, possiamo installare i wheel
                if built_wheels_dir:
                    self.logger.info("Installazione wheel compilati da Docker...")
                    for wheel_file in built_wheels_dir.glob("*.whl"):
                        self._run_isolated_pip_install(
                            env_path, str(wheel_file.resolve()), verbose
                        )
                        
                #COMANDI POST-INSTALL
                post_install_cmds = self.install_config.get("post_install_commands", [])
                if post_install_cmds:
                    self.logger.info("FASE 3: Esecuzione comandi post-installazione...")
                    
                    for cmd_template in post_install_cmds:
                        if not cmd_template: continue
                        rendered_cmd = self._render_template(cmd_template, template_vars)
                        self.logger.info(f"Esecuzione comando: {rendered_cmd}")
                        
                        final_cmd = f'conda run --prefix {str(env_path)} --no-capture-output bash -c "{rendered_cmd}"'
                        
                        run_command(final_cmd, self.logger.name, verbose, shell=True)
                else:
                    self.logger.info("Nessun comando post-installazione da eseguire.")

            else:
                # --- CASO 2: AMBIENTE ATTIVO (BASE) ---
                self.logger.warning(
                    f"Nessun 'conda_env_name' specificato. Installazione di '{self.name}' nell'ambiente Conda attivo..."
                )
                self.logger.warning(
                    "La build Docker isolata non è supportata in questa modalità."
                )

                conda_packages = self.install_config.get("conda_packages", [])
                if conda_packages:
                    self.logger.info(f"Installazione pacchetti Conda: {conda_packages}")
                    packages_str = " ".join(f'"{p}"' for p in conda_packages)
                    cmd = f"conda install {packages_str} -y"
                    run_command(cmd, self.logger.name, verbose, shell=True)

                pip_packages = self.install_config.get("pip_packages", [])
                for pkg_template in pip_packages:
                    pkg = self._render_template(pkg_template, {})
                    self.logger.info(f"Installazione pacchetto Pip: {pkg}")
                    cmd = f'python -s -u -m pip install "{pkg}"'
                    run_command(cmd, self.logger.name, verbose, shell=True)

            # 4. Esegui comandi di build finali
            for cmd_template in self.install_config.get("build_commands", []):
                cmd = self._render_template(cmd_template, template_vars)
                self.logger.info(f"Esecuzione comando di build: {cmd}")
                if env_path:
                    run_cmd = f"conda run --prefix {env_path} {cmd}"
                    run_command(
                        run_cmd,
                        self.logger.name,
                        verbose,
                        shell=True,
                        cwd=self.pipe_root,
                    )
                else:
                    run_command(
                        cmd, self.logger.name, verbose, shell=True, cwd=self.pipe_root
                    )

            self.logger.info(f"Installazione di '{self.name}' completata con successo.")

        except (Exception, KeyboardInterrupt) as e:
            self.logger.error(f"Errore durante l'installazione di '{self.name}': {e}")
            self._cleanup()
            raise

        finally:
            # Pulizia finale dei wheel temporanei
            if built_wheels_dir:
                self.logger.debug(f"Pulizia directory build Docker: {built_wheels_dir}")
                try:
                    shutil.rmtree(built_wheels_dir)
                except Exception as e:
                    self.logger.warning(
                        f"Impossibile pulire la directory tmp {built_wheels_dir}: {e}"
                    )

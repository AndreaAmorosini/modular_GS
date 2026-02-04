import os
import subprocess
import tomli_w
import shlex
import shutil
from pathlib import Path
from typing import Dict, List, Optional
from core.utils import get_or_download_pixi
import urllib.request
import re
import json
import tomli
import logging

_custom_logger = logging.getLogger("CustomInstallLog")

class MethodInstaller:
    def __init__(self, method_config: Dict, base_path: Path, verbose: bool = False):
        self.config = method_config
        self.base_path = base_path
        self.verbose = verbose
        self.pixi_exe = get_or_download_pixi(self.base_path)
        self.logger = _custom_logger

        self.vendor_dir = self.base_path / "vendor"
        self.project_root = self.base_path

    def install(self, env_path: Path):
        self.logger.info(f"Starting installation for method: {self.config.get('title', 'unknown')}")
        env_path.mkdir(parents=True, exist_ok=True)

        sentinel_file = env_path / ".install_complete"
        if sentinel_file.exists():
            logging.info(
                f"Environment in {env_path.name} is already installed. Skipping setup."
            )
            return

        logging.info(f"Configuring Environment in {env_path}")

        try:
            vendor_cloned = False

            use_shared = self.config.get("installation", {}).get("shared_env", False)
            if use_shared:
                manifest_path, env_name = self._install_shared_env(env_path)
            else:
                pixi_data = self._generate_pixi_structure()
                toml_path = env_path / "pixi.toml"
                with open(toml_path, "wb") as f:
                    tomli_w.dump(pixi_data, f)
                logging.info(f"Configuration generated at {toml_path}")

                self.logger.info(" Running Pixi Install ")
                subprocess.check_call(
                    [str(self.pixi_exe), "install"], cwd=env_path, env=os.environ, stdout=None if self.verbose else subprocess.DEVNULL, stderr=None if self.verbose else subprocess.DEVNULL
                )

            cloned_path = self._clone_repositories()
            vendor_cloned = True
            
            env_cfg = self.config.get("environment", {})
            torch_ver = env_cfg.get("torch_version", None)
            torchvision_ver = env_cfg.get("torchvision_version", None)
            cuda_ver = env_cfg.get("cuda", "11.8").replace(".", "")
            
            torch_install_cmd = None
            if torch_ver and torchvision_ver and cuda_ver:
                torch_install_cmd = (
                    f"pip install torch=={torch_ver} torchvision=={torchvision_ver} "
                    f"--index-url https://download.pytorch.org/whl/cu{cuda_ver}"
                )
                
            if use_shared and torch_install_cmd and manifest_path and env_name:
                shared_prefix = Path(manifest_path).parent / ".pixi" / "envs" / env_name
                marker = shared_prefix / ".torch_installed"
                if not marker.exists():
                    logging.info("Installing PyTorch in Shared Environment")
                    self._run_env_commands(
                        [torch_install_cmd], env_path, manifest_path, env_name
                    )
                    marker.touch()
                logging.info(
                    "PyTorch already installed in Shared Environment. Skipping."
                )
                torch_install_cmd = None  # Avoid reinstalling in build commands
                
            build_cmds = self.config.get("installation", {}).get("build_commands", [])
            if torch_install_cmd:
                build_cmds = [torch_install_cmd] + build_cmds
            if build_cmds:
                self.logger.info("Running Build Commands")
                if use_shared:
                    self._run_env_commands(
                        build_cmds, env_path, manifest_path, env_name
                    )
                else:
                    self._run_env_commands(build_cmds, env_path)

            post_cmds = self.config.get("installation", {}).get(
                "post_install_commands", []
            )
            if post_cmds:
                self.logger.info("Running Post-Install Commands")
                if use_shared:
                    self._run_env_commands(post_cmds, env_path, manifest_path, env_name)
                else:
                    self._run_env_commands(post_cmds, env_path)

            sentinel_file.touch()
            self.logger.info("Installation completed successfully.")
        except Exception as e:
            logging.error(f"Installation Failed: {e}")
            logging.error("Cleaning up...")
            shutil.rmtree(env_path)
            if vendor_cloned:
                shutil.rmtree(cloned_path)
            raise

    def _install_shared_env(self, env_path: Path) -> tuple[Path, str]:
        method_id = self.config.get("__id__", env_path.name)
        env_cfg = self.config.get("environment", {})
        cuda_ver = env_cfg.get("cuda", "11.8").replace(".", "")
        torch_ver = env_cfg.get("torch_version", "2.7.1")
        shared_dir = self.base_path / ".envs" / "_shared"
        shared_dir.mkdir(parents=True, exist_ok=True)
        manifest_path = shared_dir / "pixi.toml"

        pixi = self._load_or_init_shared_manifest(manifest_path)
        
        base_feature = self._upsert_shared_base_feature(pixi)
        tool_feature = f"tool-{method_id}"
        self._upsert_tool_feature(pixi, tool_feature)
        
        safe_method_string = re.sub(r"[^a-z0-9-]+", "-", method_id.lower())
        safe_torch_string = torch_ver.replace(".", "-")
        env_name = f"{safe_method_string}-cu{cuda_ver}-torch{safe_torch_string}"
                
        pixi.setdefault("environments", {})[env_name] = {
            "features": [base_feature, tool_feature]
        }

        with open(manifest_path, "wb") as f:
            tomli_w.dump(pixi, f)

        subprocess.check_call(
            [
                str(self.pixi_exe),
                "install",
                "-e",
                env_name,
                "--manifest-path",
                str(manifest_path),
            ],
            cwd=self.base_path,
            env=os.environ,
            stdout=None if self.verbose else subprocess.DEVNULL,
            stderr=None if self.verbose else subprocess.DEVNULL
        )

        meta = {"manifest_path": str(manifest_path), "env_name": env_name}
        with open(env_path / "shared_env.json", "w") as f:
            json.dump(meta, f)

        return manifest_path, env_name

    def _load_or_init_shared_manifest(self, manifest_path: Path) -> Dict:
        if manifest_path.exists():
            with open(manifest_path, "rb") as f:
                return tomli.load(f)

        return {
            "project": {
                "name": "gs_shared",
                "version": "0.1.0",
                "channels": self.config.get("installation", {}).get(
                    "channels", ["pytorch", "nvidia", "conda-forge"]
                ),
                "platforms": ["linux-64"],
            },
            "dependencies": {"python": "3.10.*", "pip": "*"},
            "pypi-dependencies": {},
            "feature": {},
            "environments": {},
            "system-requirements": {"linux": "5.4"},
        }

    def _upsert_shared_base_feature(self, pixi: Dict):
        env_cfg = self.config.get("environment", {})
        cuda_ver_raw = env_cfg.get("cuda", "11.8")
        cuda_ver = cuda_ver_raw.replace(".", "")
        torch_ver = env_cfg.get("torch_version", None)
        torchvision_ver = env_cfg.get("torchvision_version", None)
        
        base_feature = f"base-cu{cuda_ver}"
        if torch_ver:
            base_feature += f"-torch{torch_ver.replace('.', '-')}"

        base_deps = {
            "gxx_linux-64": "11.*",
            "gcc_linux-64": "11.*",
            "make": "*",
            "cmake": "*",
            "cuda-toolkit": f"{cuda_ver_raw}",
            "cuda-command-line-tools": f"{cuda_ver_raw}.*",
            "cuda-libraries": f"{cuda_ver_raw}.*",
            "cuda-cudart": f"{cuda_ver_raw}.*",
            "cuda-nvcc": f"{cuda_ver_raw}.*",
            "cuda-cudart-dev": f"{cuda_ver_raw}.*",
            "cuda-driver-dev": f"{cuda_ver_raw}.*",
            "cuda-cccl": f"{cuda_ver_raw}.*",
            "colmap": "*",
            "ninja": "*",
        }
        base_pypi = {}

        pixi.setdefault("feature", {})
        pixi["feature"][base_feature] = {
            "dependencies": base_deps,
            # "pypi-dependencies": base_pypi,
        }
        return base_feature

    def _upsert_tool_feature(self, pixi: Dict, feature_name: str):
        install_cfg = self.config.get("installation", {})
        deps = {}
        for dep in install_cfg.get("dependencies", []):
            n, v = self._parse_dep(dep)
            # evita duplicati con base
            if n in ("gxx_linux-64", "gcc_linux-64", "make", "cmake"):
                continue
            deps[n] = self._format_ver(v)

        pypi = {}
        for dep in install_cfg.get("pip_dependencies", []):
            n, v = self._parse_pypi_dep(dep)
            # evita torch/vision in tool
            if n in ("torch", "torchvision"):
                continue
            pypi[n] = self._format_ver(v, True)

        pixi.setdefault("feature", {})
        pixi["feature"][feature_name] = {
            "dependencies": deps,
            "pypi-dependencies": pypi,
        }

    def _generate_pixi_structure(self) -> Dict:
        type = self.config.get("type", "")
        if type == "":
            print("[ERROR] No Type specified in the TOML specify one of the following (preprocess, sfm, gaussian_splatting, post_processing)")
            raise ValueError("No Type specified")
                
        install_cfg = self.config.get("installation", {})
        env_cfg = self.config.get("environment", {})

        # Setup Versioni
        cuda_ver_raw = env_cfg.get("cuda", "11.8")
        cuda_clean = cuda_ver_raw.replace(".", "")
        cuda_folder = f"cu{cuda_clean}"
        
        C_COMPILER_VERSION = None
        if int(cuda_clean) < 120:
            C_COMPILER_VERSION = "11"
        elif int(cuda_clean) >=  120:
            C_COMPILER_VERSION = "12"


        py_ver_raw = env_cfg.get("python_version", "3.10")
        py_tag = "cp" + py_ver_raw.replace(".", "")
        platform_tag = "linux_x86_64"

        # Struttura Base Pixi
        pixi = {
            "project": {
                "name": self.config.get("title", "module").replace(" ", "_").lower(),
                "version": "0.1.0",
                "channels": install_cfg.get(
                    "channels", ["pytorch", "nvidia", "conda-forge"]
                ),
                "platforms": ["linux-64"],
            },
            "dependencies": {"python": self._format_ver(py_ver_raw), "pip": "*"},
            "pypi-dependencies": {},
            "system-requirements": {"linux": "5.4"},
        }

        # Dipendenze Conda
        has_pytorch_cuda = False
        has_cuda_toolkit = False
        
        #Check on type to inject necessaries libraries for building or other
        #Check if build command is not empty
        # Check for pip commands with paths
        # Inject --no-build-isolation
        
        for dep in install_cfg.get("dependencies", []):
            n, v = self._parse_dep(dep)
            pixi["dependencies"][n] = self._format_ver(v)
                
        if type == "gaussian_splatting":
            pixi["dependencies"].update(
                {
                    "gxx_linux-64": f"{C_COMPILER_VERSION}.*",
                    "gcc_linux-64": f"{C_COMPILER_VERSION}.*",
                    "colmap": "*",
                    "make": "*",
                    "cmake": "*",
                }
            )

        pixi["dependencies"].update(
            {
                "cuda-toolkit": f"{cuda_ver_raw}",
                "cuda-command-line-tools": f"{cuda_ver_raw}.*",
                "cuda-libraries": f"{cuda_ver_raw}.*",
                "cuda-cudart": f"{cuda_ver_raw}.*",
                "cuda-nvcc": f"{cuda_ver_raw}.*",
                "cuda-cudart-dev": f"{cuda_ver_raw}.*",
                "cuda-driver-dev": f"{cuda_ver_raw}.*",
                "cuda-cccl": f"{cuda_ver_raw}.*",

            }
        )
        
        # Dipendenze PIP e Wheels Remoti
        base_wheel_url = install_cfg.get("wheels_base_url")
        available_wheels = []

        if base_wheel_url:
            logging.info(f"Checking wheels in {base_wheel_url}/{cuda_folder}...")
            available_wheels = self._fetch_remote_file_list(
                base_wheel_url, subdir=cuda_folder
            )

        for dep in install_cfg.get("pip_dependencies", []):
            if dep.startswith("@wheel:"):
                pkg_name = dep.replace("@wheel:", "").strip()
                if not base_wheel_url:
                    raise ValueError(
                        f"Dependency {dep} needs 'wheels_base_url' in TOML."
                    )

                safe_pkg = pkg_name.replace("-", "_")
                found_wheel = self._find_best_match(
                    safe_pkg, available_wheels, py_tag, platform_tag
                )

                if found_wheel:
                    logging.info(f"-> Found wheel: {found_wheel}")
                    wheel_filename = found_wheel
                else:
                    logging.info(
                        f"-> ! Warning: Wheel not found for {pkg_name}, guessing name."
                    )
                    wheel_filename = (
                        f"{safe_pkg}-0.0.0-{py_tag}-{py_tag}-{platform_tag}.whl"
                    )

                pixi["pypi-dependencies"][pkg_name] = {
                    "url": f"{base_wheel_url}/{cuda_folder}/{wheel_filename}"
                }
            else:
                n, v = self._parse_pypi_dep(dep)
                pixi["pypi-dependencies"][n] = self._format_ver(v, True)

        return pixi

    def _clone_repositories(self):
        """Clona i repository definiti nel TOML dentro vendor/"""
        repos = self.config.get("installation", {}).get("git_repos", [])
        if not repos:
            return

        self.logger.info("Cloning required repositories...")
        self.vendor_dir.mkdir(parents=True, exist_ok=True)

        for repo in repos:
            url = repo.get("url")
            branch = repo.get("branch", "main")
            path_name = repo.get("path", url.split("/")[-1].replace(".git", ""))
            recursive = repo.get("recursive", False)

            target_path = self.vendor_dir / path_name

            if target_path.exists():
                print(f"Repo {path_name} exists. Skipping clone.")
                continue

            logging.info(f"Cloning {url} ({branch}) -> {path_name}...")
            cmd = ["git", "clone", "-b", branch, url, str(target_path)]
            if recursive:
                cmd.append("--recursive")

            subprocess.check_call(
                cmd,
                stdout=None if self.verbose else subprocess.DEVNULL,
                stderr=None if self.verbose else subprocess.DEVNULL,
            )
            # return target_path

    def _run_env_commands(self, commands: List[str], env_path: Path, manifest_path: Path | None = None, env_name: str | None = None):
        """Esegue comandi shell all'interno dell'ambiente Pixi."""
        
        env_cfg = self.config.get("environment", {})
        custom_env = os.environ.copy()
                
        if manifest_path and env_name:
            pixi_env_prefix = Path(manifest_path).parent / ".pixi" / "envs" / env_name
        else:
            pixi_env_prefix = env_path / ".pixi" / "envs" / "default"
        
        if pixi_env_prefix.exists():
            custom_env["CUDA_HOME"] = str(pixi_env_prefix.resolve())
            
            # Setup Compilatori (GCC/G++) forniti da Pixi/Conda
            bin_dir = pixi_env_prefix / "bin"
            lib_dir = pixi_env_prefix / "lib"
            include_dir = pixi_env_prefix / "include"
            
            cc_path = bin_dir / "x86_64-conda-linux-gnu-gcc"
            cxx_path = bin_dir / "x86_64-conda-linux-gnu-g++"
            
            if cc_path.exists():
                custom_env["CC"] = str(cc_path)
                custom_env["CXX"] = str(cxx_path)
                custom_env["CMAKE_C_COMPILER"] = str(cc_path)
                custom_env["CMAKE_CXX_COMPILER"] = str(cxx_path)
            
            custom_env["CPATH"] = f"{include_dir}:{custom_env.get('CPATH', '')}"
            custom_env["C_INCLUDE_PATH"] = f"{include_dir}:{custom_env.get('C_INCLUDE_PATH', '')}"
            custom_env["CPLUS_INCLUDE_PATH"] = f"{include_dir}:{custom_env.get('CPLUS_INCLUDE_PATH', '')}"
            
            custom_env["NVCC_PREPEND_FLAGS"] = "-allow-unsupported-compiler"
            
            custom_env["LD_LIBRARY_PATH"] = f"{lib_dir}:{custom_env.get('LD_LIBRARY_PATH', '')}"
            custom_env["PATH"] = f"{bin_dir}:{custom_env.get('PATH', '')}"            
        else:
            # Fallback
            custom_env["CUDA_HOME"] = str(env_path.resolve())
            
                    
        for key, value in env_cfg.items():
            if key not in ("python_version", "cuda"):
                custom_env[key] = str(value)

        for cmd_template in commands:
            cmd_str = self._resolve_template(cmd_template)
            logging.info(f"Running: {cmd_str}")
            args = shlex.split(cmd_str, posix=os.name != "nt")

            if manifest_path and env_name:
                full_cmd = [
                    str(self.pixi_exe),
                    "run",
                    "-e",
                    env_name,
                    "--manifest-path",
                    str(manifest_path),
                ] + args
            else:
                full_cmd = [
                    str(self.pixi_exe),
                    "run",
                    "--manifest-path",
                    str(env_path / "pixi.toml"),
                ] + args
            try:
                subprocess.check_call(
                    full_cmd,
                    cwd=self.base_path,
                    env=custom_env,
                    stdout=None if self.verbose else subprocess.DEVNULL,
                    stderr=None if self.verbose else subprocess.DEVNULL,
                )
            except subprocess.CalledProcessError as e:
                logging.error(f"Command failed: {cmd_str}")
                raise e
            
    #TODO: Da rivedere
    def _cleanup_build_dep(self, env_path: Path, pixi_data: Dict):
        """
        Perform a cleanup inside the newly created env to remove all packages necessary only for compiling.
        """
        
        #Packages removable
        build_pkgs = [
            "gxx_linux-64",
            "gcc_linux-64",
            "make",
            "cmake",
            "cuda-nvcc",
            # "cuda-toolkit",
            # "cuda-command-line-tools",
            "cuda-cudart-dev",
            "cuda-driver-dev",
            "cuda-cccl",
        ]

        modified = False
        deps = pixi_data.get("dependencies", {})
        for pkg in build_pkgs:
            if pkg in deps:
                del deps[pkg]
                modified = True
                
        if modified:
            print("Cleaning up Build Dependencies...")
            with open(env_path / "pixi.toml", "wb") as f:
                tomli_w.dump(pixi_data, f)
                
            subprocess.check_call(
                [str(self.pixi_exe), "install"],
                cwd=env_path,
                env=os.environ,
                stdout=None if self.verbose else subprocess.DEVNULL,
                stderr=None if self.verbose else subprocess.DEVNULL,
            )


    def _resolve_template(self, text: str) -> str:
        """Sostituisce placeholder {{...}} con path assoluti (slash normalizzati)."""
        vendor_str = str(self.vendor_dir).replace("\\", "/")
        root_str = str(self.project_root).replace("\\", "/")

        text = text.replace("{{method_vendor_dir}}", vendor_str)
        text = text.replace("{{project_root}}", root_str)
        return text

    #Utilities per ricerca file remoti
    def _fetch_remote_file_list(self, base_url: str, subdir: str) -> List[str]:
        if "huggingface.co" in base_url:
            return self._fetch_hf_api_list(base_url, subdir)
        try:
            url_to_check = base_url.rstrip("/") + f"/{subdir}"
            with urllib.request.urlopen(url_to_check, timeout=10) as response:
                html = response.read().decode("utf-8")
                files = re.findall(r'href=["\']([^"\']+\.whl)["\']', html)
                return [os.path.basename(f) for f in files]
        except Exception:
            return []

    def _fetch_hf_api_list(self, base_url: str, subdir: str) -> List[str]:
        try:
            match = re.search(r"datasets/([^/]+/[^/]+)", base_url)
            if not match:
                return []
            repo_id = match.group(1)

            rev = "main"
            rev_match = re.search(r"/resolve/([^/]+)", base_url)
            if rev_match:
                rev = rev_match.group(1)

            api_url = (
                f"https://huggingface.co/api/datasets/{repo_id}/tree/{rev}/{subdir}"
            )
            with urllib.request.urlopen(api_url, timeout=10) as response:
                data = json.loads(response.read().decode("utf-8"))

            files = [
                item["path"]
                for item in data
                if isinstance(item, dict) and "path" in item
            ]
            return [os.path.basename(f) for f in files if f.endswith(".whl")]
        except Exception:
            return []

    def _find_best_match(
        self, pkg_name: str, available_wheels: List[str], py_tag: str, platform_tag: str
    ) -> Optional[str]:
        candidates = [
            f
            for f in available_wheels
            if f.startswith(pkg_name)
            and f.endswith(".whl")
            and py_tag in f
            and platform_tag in f
        ]
        if not candidates:
            return None
        candidates.sort()
        return candidates[-1]

    def _parse_dep(self, s):
        match = re.match(r"^([a-zA-Z0-9_\-\.\[\]]+)\s*([<>=!~]+.*)$", s)
        if match:
            name = match.group(1)
            raw_ver = match.group(2)
            if raw_ver.startswith("=="):
                return name, raw_ver[2:]
            if raw_ver.startswith("=") and not raw_ver.startswith("<") and not raw_ver.startswith(">"):
                return name, raw_ver[1:]
            
            return name, raw_ver
        return s, "*"

    def _parse_pypi_dep(self, s):
        match = re.match(r"^([a-zA-Z0-9_\-\.\[\]]+)\s*([<>=!~]+.*)$", s)
        if match:
            name = match.group(1)
            raw_ver = match.group(2)
            if raw_ver.startswith("=="):
                return name, raw_ver[2:]
            if raw_ver.startswith("=") and not raw_ver.startswith("<") and not raw_ver.startswith(">"):
                return name, raw_ver[1:]
            
            return name, raw_ver
        return s, "*"

    def _format_ver(self, v, p=False):
        if v and any(op in v for op in ["<", ">", "~", "!", "*"]):
            return v    
        return (f"=={v}" if p else f"{v}.*") if v and v != "*" and "<" not in v else v
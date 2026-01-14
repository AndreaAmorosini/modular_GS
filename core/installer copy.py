import os
import subprocess
import tomli_w
from pathlib import Path
from typing import Dict, List, Optional
from core.utils import get_or_download_pixi
import urllib.request
import re
import json

class MethodInstaller:
    def __init__(self, method_config: Dict, base_path: Path):
        self.config = method_config
        self.base_path = base_path
        self.pixi_exe = get_or_download_pixi(self.base_path)

    def install(self, env_path: Path):
        env_path.mkdir(parents=True, exist_ok=True)
        print(f"--- Configuring Environment in {env_path} ---")

        # 1. Genera pixi.toml con i link ai Wheel remoti
        pixi_data = self._generate_pixi_structure()

        toml_path = env_path / "pixi.toml"
        with open(toml_path, "wb") as f:
            tomli_w.dump(pixi_data, f)

        print(f"Configuration generated at {toml_path}")

        # 2. Pixi Install (Velocissimo: scarica solo binari)
        print("--- Running Pixi Install ---")
        try:
            # env=os.environ serve per driver GPU e setup di base
            subprocess.check_call(
                [str(self.pixi_exe), "install"], cwd=env_path, env=os.environ
            )
        except subprocess.CalledProcessError:
            print("!!! Installation Failed !!!")
            print("Tip: Check if 'wheels_base_url' in TOML is correct and reachable.")
            raise

        print("--- Installation Complete ---")

    def _generate_pixi_structure(self) -> Dict:
        install_cfg = self.config.get("installation", {})
        env_cfg = self.config.get("environment", {})

        # 1. Parametri Ambiente (Fondamentali per scegliere il wheel giusto)
        cuda_ver_raw = env_cfg.get("cuda", "11.8")
        cuda_clean = cuda_ver_raw.replace(".", "")  # "11.8" -> "118"
        cuda_folder = f"cu{cuda_clean}"

        py_ver_raw = env_cfg.get("python_version", "3.10")
        py_tag = "cp" + py_ver_raw.replace(".", "")  # "3.10" -> "cp310"
        
        platform_tag = "linux_x86_64"  # Per ora solo Linux x86_64 supportato

        # 2. Configurazione Base Pixi
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

        # 3. Dipendenze Conda (Environment Runtime)
        # Anche se scarichiamo i wheel, l'ambiente deve avere CUDA e PyTorch installati per farli girare!
        for dep in install_cfg.get("dependencies", []):
            n, v = self._parse_dep(dep)
            pixi["dependencies"][n] = self._format_ver(v)

        # Iniezione dipendenze GPU critiche (Runtime)
        pixi["dependencies"].update(
            {
                "cuda-toolkit": f"{cuda_ver_raw}.*",
                "pytorch-cuda": f"{cuda_ver_raw}.*",
            }
        )

        # 4. Gestione Dipendenze PIP e WHEELS
        base_wheel_url = install_cfg.get("wheels_base_url")
        
        available_wheels = []
        if base_wheel_url:
            print(f"Checking available wheels at {base_wheel_url}...")
            available_wheels = self._fetch_remote_file_list(base_wheel_url, subdir=cuda_folder)

        for dep in install_cfg.get("pip_dependencies", []):
            if dep.startswith("@wheel:"):
                # È un pacchetto che richiede il wheel pre-compilato
                pkg_name = dep.replace("@wheel:", "").strip()

                if not base_wheel_url:
                    raise ValueError(
                        f"Found dependency {dep} but 'wheels_base_url' is missing in TOML."
                    )

                # Costruzione Nome File (Deve matchare quello generato dalla GitHub Action!)
                # Esempio: diff_gaussian_rasterization-0.0.0-cp310-cp310-linux_x86_64+cu118.whl
                safe_pkg = pkg_name.replace("-", "_")

                found_wheel = self._find_best_match(
                    safe_pkg, available_wheels, py_tag, platform_tag
                )
                
                if found_wheel:
                    wheel_filename = found_wheel
                    print(f"Found wheel for {pkg_name}: {wheel_filename}")
                else:
                    # Fallback alla vecchia logica deterministica se non riusciamo a leggere la lista
                    # o se non troviamo corrispondenza esatta
                    print(
                        f"  -> ! Warning: exact match not found for {pkg_name}, guessing filename."
                    )
                    wheel_filename = f"{safe_pkg}-0.0.0-{py_tag}-{py_tag}-{platform_tag}.whl"
                
                full_url = f"{base_wheel_url}/{cuda_folder}/{wheel_filename}"

                # Pixi scaricherà e installerà direttamente questo file
                pixi["pypi-dependencies"][pkg_name] = {"url": full_url}
            else:
                # Dipendenza pip normale (es. tqdm, plyfile)
                n, v = self._parse_pypi_dep(dep)
                pixi["pypi-dependencies"][n] = self._format_ver(v, True)

        return pixi
    
    def _fetch_remote_file_list(self, base_url: str, subdir: str) -> List[str]:
        """
        Tentativo di recuperare la lista dei file disponibili in un URL pubblico.
        Funziona solo se il server supporta l'elenco dei file (es. GitHub, HuggingFace).
        """
        
        if "huggingface.co" in base_url:
            return self._fetch_hf_api_list(base_url, subdir)
        
        try:
            url_to_check = base_url.rstrip("/") + f"/{subdir}"
            with urllib.request.urlopen(url_to_check, timeout=10) as response:
                html = response.read().decode("utf-8")
                # Estrazione dei nomi dei file usando regex
                files = re.findall(r'href=["\']([^"\']+\.whl)["\']', html)
                clean_links = [os.path.basename(link) for link in files]
                return clean_links
        except Exception as e:
            print(f"Warning: Could not fetch file list from {base_url}: {e}")
            return []
        
    def _fetch_hf_api_list(self, base_url: str, subdir: str) -> List[str]:
        try:
            match = re.search(r"datasets/([^/]+/[^/]+)", base_url)
            if not match:
                print(f"Warning: Could not parse HuggingFace dataset from URL {base_url}")
                return []
            repo_id = match.group(1)
            
            rev = "main"
            rev_match = re.search(r"/resolve/([^/]+)", base_url)
            if rev_match:
                rev = rev_match.group(1)
                
            api_url = f"https://huggingface.co/api/datasets/{repo_id}/tree/{rev}/{subdir}"
            
            with urllib.request.urlopen(api_url, timeout=10) as response:
                data = json.loads(response.read().decode("utf-8"))
                
            files = [item["path"] for item in data if isinstance(item, dict) and "path" in item]
            return [os.path.basename(f) for f in files if f.endswith(".whl")]
        except Exception as e:
            print(f"Warning: Could not fetch HuggingFace file list from {base_url}: {e}")
            return []
        

        
    def _find_best_match(self, pkg_name: str, available_wheels: List[str], py_tag: str, platform_tag: str) -> Optional[str]:
        candidates = []
        for f in available_wheels:
            if not f.startswith(pkg_name) or not f.endswith(".whl"):
                continue
            
            if py_tag in f and platform_tag in f:
                candidates.append(f)
                
        if not candidates:
            return None
        
        return candidates[0]  # Per ora ritorna il primo match trovato

    def _parse_dep(self, s):
        return s.split("=", 1) if "=" in s else (s, "*")

    def _parse_pypi_dep(self, s):
        return s.split("==", 1) if "==" in s else (s, "*")

    def _format_ver(self, v, p=False):
        return (f"=={v}" if p else f"{v}.*") if v and v != "*" and "<" not in v else v

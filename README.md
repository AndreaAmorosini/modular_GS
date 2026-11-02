# ModularGS

[![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)

## Project Overview
**ModularGS** is a modular pipeline designed for Gaussian Splatting. It provides a flexible framework for training, rendering, and extending Gaussian Splatting methods. The architecture allows researchers and developers to easily plug in new methods, visualize results via a Web GUI, and manage experiments efficiently.

## Compatibility

> **⚠️ Important Note on Operating Systems**
>
> *   **Linux**: Fully supported and recommended.
> *   **Windows**: Supported **ONLY via WSL2** (Windows Subsystem for Linux). Native Windows execution is not supported.


## Setup

The project environment is managed with [Pixi](https://pixi.prefix.dev/latest/) — the same tool used for the per-method environments — and defined in [`pixi.toml`](pixi.toml). Conda is **not** required.

1. Install Pixi (or use the bundled one at `bin/pixi` if present):
   ```sh
   curl -fsSL https://pixi.sh/install.sh | bash
   ```

2. Install the main environment (creates `.pixi/` and `pixi.lock`):
   ```sh
   pixi install
   ```

3. Run any command inside the environment with `pixi run` (no activation needed):
   ```sh
   pixi run python main.py --help
   ```

A locked `pixi.lock` is committed to the repository for reproducible installs. A `dev` environment with test-only extras (HTTP test client) is available via `pixi run -e dev python ...`.

## Main CLI Commands

Prefix every command with `pixi run` (or activate the environment with `pixi shell`):

- `pixi run python main.py run <pipeline>` — runs a pipeline; overrides and context handling are orchestrated in [`main.run`](main.py) and [`core/runner.py`](core/runner.py).
- `pixi run python main.py methods install <method>` — installs a tool via [`MethodInstaller.install`](core/installer.py).
- `pixi run python main.py methods validate [--all] <method>` — validates installed tools through [`core.validation.Validator.validate_method`](core/validation.py).
- `pixi run python main.py methods uninstall <method|--all>` — removes environments; logic lives in [`main.uninstall_method`](main.py).
- `pixi run python main.py methods list` — lists available methods from [`core.validation.Validator.registry`](core/validation.py) along with installation state.
- `pixi run python main.py methods help <method>` — prints help/overridable args by running the method's validation command (see [`main.list_arguments`](main.py)).


## Web GUI

Launch the web interface with `pixi run python main.py web` (or `pixi run web`; default `http://127.0.0.1:8501`, configurable via `--host` and `--port`). It is a FastAPI backend ([`core/gui/server.py`](core/gui/server.py)) serving a vanilla JS frontend ([`core/gui/static/`](core/gui/static/)) — no build step required.

Pages: Run Pipeline, Manage Methods, Pipeline Manager, Inputs, and Outputs. Long-running operations (pipeline runs, installs, validations) are executed as background jobs by [`core/jobs.py`](core/jobs.py) and stream their logs live to the browser over WebSocket, surviving page reloads and browser disconnects.

The Outputs page includes two integrated viewers (all dependencies vendored under [`core/gui/static/vendor/`](core/gui/static/vendor/), no CDN or build step): a **splat viewer** based on [gsplat.js](https://github.com/dylanebert/gsplat.js) that renders the gaussian splat PLYs of a run in the browser, with a toggle between final/filtered/original variants when available, and a **sparse SfM viewer** that renders the COLMAP `points3D.ply` point cloud. For editing, runs can still be opened in the external [Supersplat editor](https://superspl.at/editor).

Each page hooks into the same validator/installer stack as the CLI and reuses [`core/utils.SignatureVerifier`](core/utils.py) for security. The server binds to `127.0.0.1` by default; do not expose it on an untrusted network.


## Creating a New Method

1. Copy the starter manifest from the [`templates/`](templates/) directory.
2. Populate `installation`, `execution`, and `validation` sections with repository-specific paths (see how other TOMLs are managed in [`tools/`](tools/)).
3. Add any needed git repos under `installation.git_repos` so `MethodInstaller` clones them into [`vendor/`](vendor/).
4. Ensure `execution.command` uses `{{context.*}}` placeholders that are resolved in [`core/context.py`](core/context.py).
5. Run `python main.py methods install <your-method>` to test, then `python main.py methods validate <your-method>`.

## Contributing New Methods

1. Fork, add your method manifest under `methods/`, and commit supporting code.
2. Methods must pass [`core/utils.SignatureVerifier`](core/utils.py) verification before install/validation commands are allowed from the GUI or CLI.
3. Submit a pull request—once merged, maintainers will apply the canonical signature to the new TOML so future installs/installers can verify authenticity via the same verifier.

By keeping signatures in sync, every accepted method is trusted before tooling like [`main.py`](main.py) or the Streamlit GUI runs it.

## Acknowledgments

We would like to thank the authors and creators of the following tools and libraries that made this project possible:
- [FastAPI](https://fastapi.tiangolo.com/) and [Uvicorn](https://www.uvicorn.org/) for the web UI backend.
- [Pixi](https://pixi.prefix.dev/latest/) for environment creation and execution orchestration.
- [PyColmap](https://colmap.github.io/pycolmap/index.html) for reconstruction and matching helpers.
- [Jinja2](https://jinja.palletsprojects.com/en/stable/) for command templating.
- [3D Gaussian Splatting](https://github.com/graphdeco-inria/gaussian-splatting) (Original Paper & Code)
- [Nerfstudio](https://docs.nerf.studio/) (for inspiration on modularity)

## License

This project is licensed under the terms described in [`LICENSE`](LICENSE).


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

1. Install dependencies via Conda:
   ```sh
   conda env create -f environment.yml
   ```

2. Activate the environment:
    ```sh
    conda activate modular_GS
    ```

## Main CLI Commands

- `python main.py run <pipeline>` — runs a pipeline; overrides and context handling are orchestrated in [`main.run`](main.py) and [`core/runner.py`](core/runner.py).
- `python main.py methods install <method>` — installs a tool via [`MethodInstaller.install`](core/installer.py).
- `python main.py methods validate [--all] <method>` — validates installed tools through [`core.validation.Validator.validate_method`](core/validation.py).
- `python main.py methods uninstall <method|--all>` — removes environments; logic lives in [`main.uninstall_method`](main.py).
- `python main.py methods list` — lists available methods from [`core.validation.Validator.registry`](core/validation.py) along with installation state.
- `python main.py methods help <method>` — prints help/overridable args by running the method’s validation command (see [`main.list_arguments`](main.py)).


## Web GUI

Launch the Streamlit GUI with `python main.py web`. It boots [`core/gui/web_ui.py`](core/gui/web_ui.py), renders the sidebar, and exposes the Manage Methods, Pipeline Manager, Inputs, and Outputs pages. Each page (e.g., [`core/gui/pages/1_manage_tools.py`](core/gui/pages/1_manage_tools.py)) hooks into the same validator/installer stack and reuses [`core/utils.SignatureVerifier`](core/utils.py) for security.


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
- [Streamlit](https://streamlit.io/) for the web UI.
- [Pixi](https://pixi.prefix.dev/latest/) for environment creation and execution orchestration.
- [PyColmap](https://colmap.github.io/pycolmap/index.html) for reconstruction and matching helpers.
- [Jinja2](https://jinja.palletsprojects.com/en/stable/) for command templating.
- [3D Gaussian Splatting](https://github.com/graphdeco-inria/gaussian-splatting) (Original Paper & Code)
- [Nerfstudio](https://docs.nerf.studio/) (for inspiration on modularity)

## License

This project is licensed under the terms described in [`LICENSE`](LICENSE).


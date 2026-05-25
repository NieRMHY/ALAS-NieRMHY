# Deploy

This directory holds the Alas installer.

Install Alas by running `python -m deploy.installer` in Alas root folder.

This entry point bootstraps the project-local `.venv` with `uv` and syncs
dependencies from `pyproject.toml` and `uv.lock` before continuing. It does not
install packages into the system Python environment.


# Launcher

Launcher `Alas.exe` is a `.bat` file converted to `.exe` file by [Bat To Exe Converter](https://f2ko.de/programme/bat-to-exe-converter/).

If you have warnings from your anti-virus software, replace `alas.exe` with `deploy/launcher/Alas.bat`. They should do the same thing.


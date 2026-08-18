"""Configuration, read from `config/settings.py`.

Python rather than a static format, because configuration here wants to be
computed as often as declared — reading a repository list off disk, varying the
tool profile by machine, deriving sprint capacity from team size. A declarative
format needs a mechanism for each of those; Python needs none.

The config file defines either a module-level `settings`, or a `build()`
returning one:

    from planify.application.settings import Settings, BackendSettings

    settings = Settings(backend=BackendSettings(name="azure-boards", ...))

Planning runs on your Claude Code subscription, so there is no model
credential to configure here. Backend credentials — an Azure DevOps PAT, say —
belong in the environment and are referenced from `.mcp.json`, never written
into this file.

**This executes the file.** That is how Python configuration always works —
Django's `settings.py`, pytest's `conftest.py` — and it is worth being explicit
about rather than discovering later: whatever is in that file runs with your
privileges when the tool starts. It is your own file in your own repository, and
it is also not a place to paste something a stranger sent you.

The module is loaded from its path without being added to `sys.modules`, so it
cannot shadow a real package and is re-read on each load rather than cached
across a long-running process.
"""

from __future__ import annotations

import importlib.util
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from planify.adapters.driven.config.validation import validate
from planify.application.ports.settings_provider import SettingsError
from planify.application.settings import Settings

DEFAULT_PATH = Path("config/settings.py")

#: What the config module may expose, in the order we look for it.
_SETTINGS_ATTRIBUTE = "settings"
_FACTORY_ATTRIBUTE = "build"


@dataclass(frozen=True, slots=True)
class PySettingsProvider:
    path: Path = DEFAULT_PATH

    def load(self) -> Settings:
        if not self.path.is_file():
            raise SettingsError(
                f"no configuration at {self.path}. Copy "
                "config/settings.example.py to config/settings.py and fill in "
                "your project details."
            )
        return validate(_extract(_execute(self.path), self.path), self.path)


def _execute(path: Path) -> Any:
    spec = importlib.util.spec_from_file_location("planify_user_settings", path)
    if spec is None or spec.loader is None:
        raise SettingsError(f"{path} could not be loaded as a Python module")

    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except SettingsError:
        # The config file is allowed to reject itself — a hostname it does not
        # recognise, a credential helper that failed. Let that through as-is.
        raise
    except Exception as exc:
        raise SettingsError(f"{path} failed while being loaded: {exc!r}") from exc
    return module


def _extract(module: Any, path: Path) -> Settings:
    if (factory := getattr(module, _FACTORY_ATTRIBUTE, None)) is not None:
        if not callable(factory):
            raise SettingsError(f"{path} defines '{_FACTORY_ATTRIBUTE}' but it is not callable")
        try:
            candidate = factory()
        except SettingsError:
            raise
        except Exception as exc:
            raise SettingsError(f"{path}: {_FACTORY_ATTRIBUTE}() raised {exc!r}") from exc
    else:
        candidate = getattr(module, _SETTINGS_ATTRIBUTE, None)

    if candidate is None:
        raise SettingsError(
            f"{path} defines neither '{_SETTINGS_ATTRIBUTE}' nor "
            f"'{_FACTORY_ATTRIBUTE}()'. One of them must produce a Settings object."
        )
    if not isinstance(candidate, Settings):
        raise SettingsError(
            f"{path} produced {type(candidate).__name__}, not a Settings object. "
            "Import it with: from planify.application.settings import Settings"
        )
    return candidate

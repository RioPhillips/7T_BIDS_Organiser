"""
Searches for code/bids7t.yaml starting from the current working directory
and traversing upward.
"""

import yaml
from pathlib import Path
from typing import Optional, Dict, Any

MAX_SEARCH_DEPTH = 5
_CONFIG_FILENAME = "bids7t.yaml"


def find_config_from_cwd(max_depth: int = MAX_SEARCH_DEPTH) -> Optional[Path]:
    # searches for code/bids7t.yaml from CWD upward
    current = Path.cwd().resolve()
    for _ in range(max_depth):
        config_path = current / "code" / _CONFIG_FILENAME
        if config_path.exists():
            return config_path
        parent = current.parent
        if parent == current:
            break
        current = parent
    return None


def find_studydir_from_cwd(max_depth: int = MAX_SEARCH_DEPTH) -> Optional[Path]:
    # find study directory (parent of code/) from CWD upward
    config_path = find_config_from_cwd(max_depth)
    if config_path:
        return config_path.parent.parent
    return None


def load_study_config(config_path: Optional[Path] = None) -> Dict[str, Any]:
    # loads the study config from a bids7t.yaml file
    if config_path is None:
        config_path = find_config_from_cwd()
    if config_path is None:
        raise FileNotFoundError(
            f"Could not find code/{_CONFIG_FILENAME} in current directory or any parent.\n"
            "Make sure you're running from within the study directory tree,\n"
            "or use '--studydir /path/to/study' with your command."
        )
    config_path = Path(config_path)
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")
    try:
        with open(config_path) as f:
            return yaml.safe_load(f) or {}
    except yaml.YAMLError as e:
        raise ValueError(f"Invalid YAML in {config_path}: {e}")


def get_studydir(config_path: Optional[Path] = None) -> Path:
    # get the studydir from config or by searching from CWD
    if config_path is None:
        config_path = find_config_from_cwd()
    if config_path is None:
        raise FileNotFoundError(
            f"Could not find code/{_CONFIG_FILENAME} in current directory or any parent."
        )
    config_path = Path(config_path)
    config = load_study_config(config_path)
    if "studydir" in config:
        studydir = Path(config["studydir"])
    else:
        studydir = config_path.parent.parent
    studydir = studydir.resolve()
    if not studydir.exists():
        raise FileNotFoundError(f"Study directory does not exist: {studydir}")
    return studydir


def resolve_studydir(explicit_studydir: Optional[Path] = None) -> Path:
    # resolves studydir from explicit flag or CWD search
    import click
    if explicit_studydir is not None:
        path = Path(explicit_studydir)
        if not path.exists():
            raise click.UsageError(f"Studydir does not exist: {path}")
        return path
    try:
        return get_studydir()
    except FileNotFoundError as e:
        raise click.UsageError(
            f"{e}\n\nEither:\n"
            "  1. Run the command from within your study directory tree\n"
            "  2. Use '--studydir /path/to/study' with your command"
        )
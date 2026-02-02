"""
Global settings management for dcm2bids.

Handles the package-wide settings stored in ~/.dcm2bids/settings.json
which stores the path to the active study's config.json.
"""

import json
from pathlib import Path
from typing import Optional, Dict, Any


# Global settings directory
SETTINGS_DIR = Path.home() / ".dcm2bids"
SETTINGS_FILE = SETTINGS_DIR / "settings.json"


def _ensure_settings_dir() -> Path:
    """Get the settings directory, creating it if needed."""
    SETTINGS_DIR.mkdir(parents=True, exist_ok=True)
    return SETTINGS_DIR


def load_global_settings() -> Dict[str, Any]:
    """
    Load global settings from ~/.dcm2bids/settings.json.
    
    Returns
    -------
    dict
        Settings dictionary, empty if file doesn't exist
    """
    if not SETTINGS_FILE.exists():
        return {}
    
    try:
        with open(SETTINGS_FILE) as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return {}


def save_global_settings(settings: Dict[str, Any]) -> None:
    """
    Save global settings to ~/.dcm2bids/settings.json.
    
    Parameters
    ----------
    settings : dict
        Settings to save
    """
    _ensure_settings_dir()
    with open(SETTINGS_FILE, 'w') as f:
        json.dump(settings, f, indent=4)


def set_active_config(config_path: Path) -> None:
    """
    Set the active config.json path in global settings.
    
    Parameters
    ----------
    config_path : Path
        Path to the study's config.json file
    """
    settings = load_global_settings()
    settings["config_path"] = str(Path(config_path).resolve())
    save_global_settings(settings)


def get_active_config_path() -> Optional[Path]:
    """
    Get the active config.json path from global settings.
    
    Returns
    -------
    Path or None
        Path to active config.json, or None if not set
    """
    settings = load_global_settings()
    config_path = settings.get("config_path")
    
    if config_path:
        path = Path(config_path)
        if path.exists():
            return path
    
    return None


def load_study_config(config_path: Optional[Path] = None) -> Dict[str, Any]:
    """
    Load the study config from a config.json file.
    
    Parameters
    ----------
    config_path : Path, optional
        Path to config.json. If None, uses the active config from global settings.
        
    Returns
    -------
    dict
        Study configuration
        
    Raises
    ------
    FileNotFoundError
        If no config path provided and no active config set
    """
    if config_path is None:
        config_path = get_active_config_path()
    
    if config_path is None:
        raise FileNotFoundError(
            "No config.json path provided and no active config set.\n"
            "Run 'dcm2bids init' or 'dcm2bids init --config /path/to/config.json' first."
        )
    
    config_path = Path(config_path)
    
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")
    
    try:
        with open(config_path) as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON in {config_path}: {e}")


def get_studydir(config_path: Optional[Path] = None) -> Path:
    """
    Get the studydir from the study config.
    
    Parameters
    ----------
    config_path : Path, optional
        Path to config.json. If None, uses the active config.
        
    Returns
    -------
    Path
        Path to the study directory
        
    Raises
    ------
    KeyError
        If 'studydir' is not defined in the config
    """
    config = load_study_config(config_path)
    
    if "studydir" not in config:
        raise KeyError(
            "'studydir' not found in config.json.\n"
            "Please add: \"studydir\": \"/path/to/your/study\""
        )
    
    studydir = Path(config["studydir"])
    
    if not studydir.exists():
        raise FileNotFoundError(f"Study directory does not exist: {studydir}")
    
    return studydir


def resolve_studydir(explicit_studydir: Optional[Path] = None) -> Path:
    """
    Resolve the studydir to use, with fallback logic.
    
    Priority:
    1. Explicitly provided studydir (from --studydir flag)
    2. studydir from active config.json
    
    Parameters
    ----------
    explicit_studydir : Path, optional
        Explicitly provided studydir from command line
        
    Returns
    -------
    Path
        Resolved studydir path
        
    Raises
    ------
    click.UsageError
        If no valid studydir can be determined
    """
    import click
    
    # 1. Explicit studydir takes priority
    if explicit_studydir is not None:
        path = Path(explicit_studydir)
        if not path.exists():
            raise click.UsageError(f"Studydir does not exist: {path}")
        return path
    
    # 2. Try to get from active config
    try:
        return get_studydir()
    except (FileNotFoundError, KeyError) as e:
        raise click.UsageError(
            f"{e}\n\n"
            "Either:\n"
            "  1. Run 'dcm2bids init' from your study directory (with code/config.json)\n"
            "  2. Run 'dcm2bids init --config /path/to/config.json'\n"
            "  3. Use '--studydir /path/to/study' with your command"
        )
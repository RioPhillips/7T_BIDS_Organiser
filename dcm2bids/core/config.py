"""
Searches for code/config.json starting from the current working directory
and traversing upward. This allows running commands from anywhere within
or below the study directory.
"""

import json
from pathlib import Path
from typing import Optional, Dict, Any


# should be theoretical highest, ex: CWD/rawdata/sub/ses/anat/
MAX_SEARCH_DEPTH = 4


def find_config_from_cwd(max_depth: int = MAX_SEARCH_DEPTH) -> Optional[Path]:
    """
    Search for code/config.json starting from CWD and going upward.
    
    Parameters
    ----------
    max_depth : int
        Maximum number of parent directories to search
        
    Returns
    -------
    Path or None
        Path to config.json if found, None otherwise
    """
    current = Path.cwd().resolve()
    
    for _ in range(max_depth):
        config_path = current / "code" / "config.json"
        if config_path.exists():
            return config_path
        
        # stop at root
        parent = current.parent
        if parent == current:
            break
        current = parent
    
    return None


def find_studydir_from_cwd(max_depth: int = MAX_SEARCH_DEPTH) -> Optional[Path]:
    """
    Search for a study directory (containing code/config.json) from CWD upward.
    
    Parameters
    ----------
    max_depth : int
        Maximum number of parent directories to search
        
    Returns
    -------
    Path or None
        Path to study directory if found, None otherwise
    """
    config_path = find_config_from_cwd(max_depth)
    if config_path:
        # studydir is parent of code/
        return config_path.parent.parent
    return None


def load_study_config(config_path: Optional[Path] = None) -> Dict[str, Any]:
    """
    Load the study config from a config.json file.
    
    Parameters
    ----------
    config_path : Path, optional
        Path to config.json. If None, searches from CWD upward.
        
    Returns
    -------
    dict
        Study configuration
        
    Raises
    ------
    FileNotFoundError
        If config.json cannot be found
    """
    if config_path is None:
        config_path = find_config_from_cwd()
    
    if config_path is None:
        raise FileNotFoundError(
            "Could not find code/config.json in current directory or any parent.\n"
            "Make sure you're running from within the study directory tree,\n"
            "or use '--studydir /path/to/study' with your command."
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
    Get the studydir from the study config or by searching from CWD.
    
    Priority:
    1. If config_path provided, use studydir from that config
    2. Search from CWD upward for code/config.json
    3. Use studydir from found config, or infer from config location
    
    Parameters
    ----------
    config_path : Path, optional
        Path to config.json. If None, searches from CWD upward.
        
    Returns
    -------
    Path
        Path to the study directory
        
    Raises
    ------
    FileNotFoundError
        If config cannot be found or studydir doesn't exist
    """
    # find
    if config_path is None:
        config_path = find_config_from_cwd()
    
    if config_path is None:
        raise FileNotFoundError(
            "Could not find code/config.json in current directory or any parent.\n"
            "Make sure you're running from within the study directory tree."
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
    """
    Resolve the studydir to use, with fallback logic.
    
    Priority:
    1. Explicitly provided studydir (from --studydir flag)
    2. Search from CWD upward for code/config.json
    
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
    
    # 1. flagged studydir takes priority
    if explicit_studydir is not None:
        path = Path(explicit_studydir)
        if not path.exists():
            raise click.UsageError(f"Studydir does not exist: {path}")
        return path
    
    # 2. else search from CWD upward
    try:
        return get_studydir()
    except FileNotFoundError as e:
        raise click.UsageError(
            f"{e}\n\n"
            "Either:\n"
            "  1. Run the command from within your study directory tree\n"
            "  2. Use '--studydir /path/to/study' with your command"
        )
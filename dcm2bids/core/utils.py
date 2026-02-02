"""
Shared utility functions for dcm2bids commands.
"""

import logging
import subprocess
from pathlib import Path
from typing import Optional, List, Tuple
import sys


def setup_logging(
    name: str,
    log_file: Optional[Path] = None,
    verbose: bool = False
) -> logging.Logger:
    """
    Set up logging for a command.
    
    Parameters
    ----------
    name : str
        Logger name
    log_file : Path, optional
        Path to log file
    verbose : bool
        If True, set DEBUG level; otherwise INFO
        
    Returns
    -------
    logging.Logger
        Configured logger
    """
    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG if verbose else logging.INFO)
    
    # Clear existing handlers
    logger.handlers.clear()
    
    # Console handler
    console = logging.StreamHandler(sys.stdout)
    console.setLevel(logging.DEBUG if verbose else logging.INFO)
    console_fmt = logging.Formatter('%(levelname)s - %(message)s')
    console.setFormatter(console_fmt)
    logger.addHandler(console)
    
    # File handler (if specified)
    if log_file:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_file)
        file_handler.setLevel(logging.DEBUG)
        file_fmt = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
        file_handler.setFormatter(file_fmt)
        logger.addHandler(file_handler)
    
    return logger


def run_command(
    cmd: List[str],
    logger: logging.Logger,
    log_file: Optional[Path] = None,
    capture_output: bool = False,
    check: bool = True
) -> subprocess.CompletedProcess:
    """
    Run a shell command with logging.
    
    Parameters
    ----------
    cmd : list
        Command and arguments
    logger : logging.Logger
        Logger instance
    log_file : Path, optional
        File to write stdout/stderr to
    capture_output : bool
        If True, capture and return output
    check : bool
        If True, raise on non-zero exit
        
    Returns
    -------
    subprocess.CompletedProcess
        Completed process result
    """
    logger.debug(f"Running: {' '.join(cmd)}")
    
    if log_file:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        with open(log_file, "w") as lf:
            result = subprocess.run(
                cmd,
                stdout=lf,
                stderr=subprocess.STDOUT,
                text=True
            )
    elif capture_output:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True
        )
    else:
        result = subprocess.run(cmd, text=True)
    
    if check and result.returncode != 0:
        logger.error(f"Command failed with code {result.returncode}")
        if log_file:
            logger.error(f"See log: {log_file}")
        elif capture_output and result.stderr:
            logger.error(f"stderr: {result.stderr}")
        raise RuntimeError(f"Command failed: {' '.join(cmd)}")
    
    return result


def check_outputs_exist(
    output_files: List[Path],
    logger: logging.Logger,
    force: bool = False
) -> Tuple[bool, List[Path]]:
    """
    Check if output files already exist.
    
    Parameters
    ----------
    output_files : list
        List of output file paths to check
    logger : logging.Logger
        Logger instance
    force : bool
        If True, always return should_run=True
        
    Returns
    -------
    tuple
        (should_run: bool, existing_files: list)
    """
    existing = [f for f in output_files if f.exists()]
    
    if existing and not force:
        logger.info(f"{len(existing)} output file(s) already exist:")
        for f in existing[:5]:  # Show first 5
            logger.info(f"  - {f.name}")
        if len(existing) > 5:
            logger.info(f"  ... and {len(existing) - 5} more")
        logger.info("Run with --force to overwrite")
        return False, existing
    
    if existing and force:
        logger.info(f"Force flag set, will overwrite {len(existing)} existing files")
    
    return True, existing


def find_files(
    directory: Path,
    pattern: str,
    recursive: bool = False
) -> List[Path]:
    """
    Find files matching a pattern.
    
    Parameters
    ----------
    directory : Path
        Directory to search
    pattern : str
        Glob pattern
    recursive : bool
        If True, search recursively
        
    Returns
    -------
    list
        List of matching paths
    """
    if not directory.exists():
        return []
    
    if recursive:
        return sorted(directory.rglob(pattern))
    return sorted(directory.glob(pattern))


def get_docker_user_args() -> List[str]:
    """Get docker --user arguments for current user."""
    import os
    uid = os.getuid()
    gid = os.getgid()
    return ["--user", f"{uid}:{gid}"]

"""Shared utility functions for bids7t commands."""

import logging
import subprocess
from pathlib import Path
from typing import Optional, List, Tuple
import sys


def setup_logging(name: str, log_file: Optional[Path] = None, verbose: bool = False) -> logging.Logger:
    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG if verbose else logging.INFO)
    logger.handlers.clear()
    
    console = logging.StreamHandler(sys.stdout)
    console.setLevel(logging.DEBUG if verbose else logging.INFO)
    console.setFormatter(logging.Formatter('%(levelname)s - %(message)s'))
    logger.addHandler(console)
    
    if log_file:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        fh = logging.FileHandler(log_file)
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
        logger.addHandler(fh)
    return logger


def run_command(cmd: List[str], logger, log_file: Optional[Path] = None,
                capture_output: bool = False, check: bool = True):
    logger.debug(f"Running: {' '.join(cmd)}")
    if log_file:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        with open(log_file, "w") as lf:
            result = subprocess.run(cmd, stdout=lf, stderr=subprocess.STDOUT, text=True)
    elif capture_output:
        result = subprocess.run(cmd, capture_output=True, text=True)
    else:
        result = subprocess.run(cmd, text=True)
    if check and result.returncode != 0:
        logger.error(f"Command failed with code {result.returncode}")
        if log_file:
            logger.error(f"See log: {log_file}")
        raise RuntimeError(f"Command failed: {' '.join(cmd)}")
    return result


def check_outputs_exist(output_files: List[Path], logger, force: bool = False) -> Tuple[bool, List[Path]]:
    existing = [f for f in output_files if f.exists()]
    if existing and not force:
        logger.info(f"{len(existing)} output file(s) already exist. Run with --force to overwrite")
        return False, existing
    if existing and force:
        logger.info(f"Force flag set, will overwrite {len(existing)} existing files")
    return True, existing


def find_files(directory: Path, pattern: str, recursive: bool = False) -> List[Path]:
    if not directory.exists():
        return []
    if recursive:
        return sorted(directory.rglob(pattern))
    return sorted(directory.glob(pattern))


def get_docker_user_args() -> List[str]:
    import os
    return ["--user", f"{os.getuid()}:{os.getgid()}"]
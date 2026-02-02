"""
populate-templates command - Create top-level BIDS files after batch processing.

This command runs heudiconv's populate-templates to create top-level
BIDS files (dataset_description.json, README, CHANGES, .bidsignore)
after batch processing with --notop.

Note: participants.tsv must be created/updated manually.
"""

import subprocess
from pathlib import Path
from typing import Optional

from dcm2bids.core import (
    setup_logging, 
    run_command,
    load_config,
    get_heuristic_path,
    get_docker_user_args
)


def run_populate_templates(
    studydir: Path,
    heuristic: Optional[Path] = None,
    use_docker: bool = False,
    verbose: bool = False
) -> None:
    """
    Create top-level BIDS files after batch processing.
    
    Parameters
    ----------
    studydir : Path
        Path to BIDS study directory
    heuristic : Path, optional
        Path to heuristic file (defaults to config.json setting)
    use_docker : bool
        Run heudiconv via Docker
    verbose : bool
        Enable verbose output
    """
    studydir = Path(studydir)
    log_dir = studydir / "derivatives" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "populate_templates.log"
    
    logger = setup_logging("populate-templates", log_file, verbose)
    
    logger.info(f"Populating BIDS templates for {studydir}")
    
    # find heuristic
    if heuristic is None:
        config = load_config(studydir)
        heuristic = get_heuristic_path(studydir, config)
    
    if heuristic is None or not heuristic.exists():
        raise FileNotFoundError(
            f"Heuristic file not found. Please specify via --heuristic or in code/config.json"
        )
    
    logger.info(f"Using heuristic: {heuristic}")
    
    rawdata_root = studydir / "rawdata"
    
    if not rawdata_root.exists():
        raise FileNotFoundError(f"rawdata directory not found: {rawdata_root}")
    
    # check if there are any subject directories
    subject_dirs = list(rawdata_root.glob("sub-*"))
    if not subject_dirs:
        raise FileNotFoundError(
            f"No subject directories found in {rawdata_root}. "
            f"Run src2rawdata first."
        )
    
    if use_docker:
        logger.info("Running heudiconv populate-templates via Docker")
        user_args = get_docker_user_args()
        
        cmd = [
            "docker", "run", "--rm",
            *user_args,
            "--volume", f"{studydir}:/base",
            "--volume", f"{rawdata_root}:/rawdata",
            "nipy/heudiconv:latest",
            "--files", "/rawdata",
            "-f", f"/base/code/{heuristic.name}",
            "--command", "populate-templates"
        ]
    else:
        logger.info("Running heudiconv populate-templates locally")
        
        cmd = [
            "heudiconv",
            "--files", str(rawdata_root),
            "-f", str(heuristic),
            "--command", "populate-templates"
        ]
    
    logger.debug(f"Command: {' '.join(cmd)}")
    run_command(cmd, logger, log_file)
    
    logger.info("Successfully created top-level BIDS files")
    
    # tracking created files
    created_files = []
    for fname in ["dataset_description.json", "README", "CHANGES", ".bidsignore"]:
        fpath = rawdata_root / fname
        if fpath.exists():
            created_files.append(fname)
            logger.info(f"  ✓ {fname}")
    
    # just check
    participants_tsv = rawdata_root / "participants.tsv"
    if not participants_tsv.exists():
        logger.warning("")
        logger.warning("Note: participants.tsv was NOT created.")
        logger.warning("You must create this file manually with columns:")
        logger.warning("  participant_id\\tage\\tsex")
    else:
        logger.info("  ✓ participants.tsv (already exists)")
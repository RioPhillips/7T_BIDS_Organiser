"""
validate command - Run BIDS validator on the dataset.

Uses the bids-validator Docker container to check BIDS compliance.
"""

import subprocess
from pathlib import Path

from dcm2bids.core import Session, setup_logging, get_docker_user_args


def run_validate(
    studydir: Path,
    subject: str,
    session: str,
    force: bool = False,
    verbose: bool = False
) -> bool:
    """
    Run BIDS validator on the dataset.
    
    Parameters
    ----------
    studydir : Path
        Path to BIDS study directory
    subject : str
        Subject ID (without sub- prefix)
    session : str
        Session ID (without ses- prefix)
    force : bool
        Force re-run validation
    verbose : bool
        Enable verbose output
        
    Returns
    -------
    bool
        True if validation passed, False otherwise
    """
    sess = Session(studydir, subject, session)
    log_file = sess.paths["logs"] / "validate.log"
    

    if log_file.exists() and not force:

        logger = setup_logging("validate", log_file=None, verbose=verbose)
        
        logger.info(f"Previous validation log exists: {log_file}")
        logger.info("Run with --force to re-validate")
        

        with open(log_file) as f:
            content = f.read()
            if "This dataset appears to be BIDS compatible" in content:
                logger.info("Previous validation: PASSED")
                return True
            else:
                logger.info("Previous validation: FAILED (see log for details)")
                return False
    
    logger = setup_logging("validate", log_file, verbose)
    
    rawdata_root = sess.studydir / "rawdata"
    
    if not rawdata_root.exists():
        logger.error(f"rawdata directory not found: {rawdata_root}")
        return False
    
    logger.info(f"Running BIDS Validator on {rawdata_root}")
    

    user_args = get_docker_user_args()
    
    cmd = [
        "docker", "run", "--rm",
        *user_args,
        "--volume", f"{rawdata_root}:/data:ro",
        "bids/validator",
        "/data"
    ]
    
    logger.debug(f"Command: {' '.join(cmd)}")
    

    sess.paths["logs"].mkdir(parents=True, exist_ok=True)
    
    with open(log_file, "w") as logf:
        result = subprocess.run(cmd, stdout=logf, stderr=subprocess.STDOUT)
    

    if result.returncode == 0:
        logger.info("✓ BIDS Validation PASSED")
        return True
    else:
        logger.warning(f"✗ BIDS Validation FAILED (exit code {result.returncode})")
        logger.info(f"See detailed log: {log_file}")
        
        _print_validation_summary(log_file, logger)
        
        return False


def _print_validation_summary(log_file: Path, logger) -> None:
    """Print a summary of validation errors/warnings."""
    try:
        with open(log_file) as f:
            lines = f.readlines()
        
        errors = [l for l in lines if "[ERR]" in l or "Error" in l]
        warnings = [l for l in lines if "[WARN]" in l or "Warning" in l]
        
        if errors:
            logger.warning(f"Errors: {len(errors)}")
            for err in errors[:5]:  # show first 5
                logger.warning(f"  {err.strip()}")
            if len(errors) > 5:
                logger.warning(f"  ... and {len(errors) - 5} more errors")
        
        if warnings:
            logger.info(f"Warnings: {len(warnings)}")
    
    except Exception:
        pass
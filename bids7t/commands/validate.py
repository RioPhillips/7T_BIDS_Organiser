"""validate - Run BIDS validator."""

import subprocess
from pathlib import Path
from typing import Optional
from bids7t.core import Session, setup_logging, get_docker_user_args


def run_validate(studydir: Path, subject: str, session: Optional[str] = None,
                 force: bool = False, verbose: bool = False) -> bool:
    sess = Session(studydir, subject, session)
    log_file = sess.paths["logs"] / "validate.log"
    if log_file.exists() and not force:
        logger = setup_logging("validate", log_file=None, verbose=verbose)
        with open(log_file) as f:
            content = f.read()
        passed = "BIDS compatible" in content
        logger.info(f"Previous validation: {'PASSED' if passed else 'FAILED'}")
        return passed
    logger = setup_logging("validate", log_file, verbose)
    rawdata_root = sess.studydir / "rawdata"
    if not rawdata_root.exists():
        logger.error("rawdata not found"); return False
    logger.info(f"Running BIDS Validator on {rawdata_root}")
    user_args = get_docker_user_args()
    cmd = ["docker", "run", "--rm", *user_args,
           "--volume", f"{rawdata_root}:/data:ro", "bids/validator", "/data"]
    sess.paths["logs"].mkdir(parents=True, exist_ok=True)
    with open(log_file, "w") as logf:
        result = subprocess.run(cmd, stdout=logf, stderr=subprocess.STDOUT)
    if result.returncode == 0:
        logger.info("BIDS Validation PASSED"); return True
    logger.warning(f"BIDS Validation FAILED (code {result.returncode})"); return False
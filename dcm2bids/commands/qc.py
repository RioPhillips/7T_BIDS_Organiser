"""
qc command - Run MRIQC quality control.

Uses the MRIQC Docker container to generate quality control reports
for the participant's imaging data.
"""

import subprocess
from pathlib import Path

from dcm2bids.core import Session, setup_logging, get_docker_user_args


def run_qc(
    studydir: Path,
    subject: str,
    session: str,
    mem_gb: int = 6,
    force: bool = False,
    verbose: bool = False
) -> bool:
    """
    Run MRIQC quality control.
    
    Parameters
    ----------
    studydir : Path
        Path to BIDS study directory
    subject : str
        Subject ID (without sub- prefix)
    session : str
        Session ID (without ses- prefix)
    mem_gb : int
        Memory limit in GB (default: 6)
    force : bool
        Force re-run QC
    verbose : bool
        Enable verbose output
        
    Returns
    -------
    bool
        True if QC completed successfully
    """
    sess = Session(studydir, subject, session)
    log_file = sess.paths["logs"] / "mriqc.log"
    logger = setup_logging("qc", log_file, verbose)
    
    rawdata_root = sess.studydir / "rawdata"
    mriqc_out = sess.studydir / "derivatives" / "mriqc"
    
    if not rawdata_root.exists():
        logger.error(f"rawdata directory not found: {rawdata_root}")
        return False
    
    logger.info(f"Running MRIQC for sub-{subject}_ses-{session}")
    
    # check existing output
    subj_html = mriqc_out / f"sub-{subject}" / f"ses-{session}"
    if subj_html.exists() and any(subj_html.glob("*.html")) and not force:
        logger.info(f"MRIQC reports already exist: {subj_html}")
        logger.info("Run with --force to regenerate")
        return True
    
    # output directory
    mriqc_out.mkdir(parents=True, exist_ok=True)
    
    # docker command
    user_args = get_docker_user_args()
    
    cmd = [
        "docker", "run", "--rm",
        "--read-only",
        "--tmpfs", "/tmp",
        "--tmpfs", "/run",
        *user_args,
        "--volume", f"{rawdata_root}:/data:ro",
        "--volume", f"{mriqc_out}:/out",
        "nipreps/mriqc:latest",
        "/data",
        "/out",
        "participant",
        "--participant_label", subject,
        "--session-id", session,
        "--verbose-reports",
        "--mem_gb", str(mem_gb)
    ]
    
    logger.debug(f"Command: {' '.join(cmd)}")
    
    # run mriqc
    sess.paths["logs"].mkdir(parents=True, exist_ok=True)
    
    with open(log_file, "w") as logf:
        result = subprocess.run(cmd, stdout=logf, stderr=subprocess.STDOUT)
    
    if result.returncode != 0:
        logger.error(f"MRIQC failed with exit code {result.returncode}")
        logger.error(f"See log: {log_file}")
        return False
    
    logger.info("✓ MRIQC completed successfully")
    logger.info(f"Reports: {mriqc_out}")
    
    return True

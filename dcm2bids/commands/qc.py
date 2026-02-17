"""
qc command - Run MRIQC quality control.

"""

import subprocess
import shutil
from pathlib import Path
from typing import List, Optional

from dcm2bids.core import Session, setup_logging, get_docker_user_args


def run_qc(
    studydir: Path,
    subject: str,
    session: str,
    modalities: Optional[List[str]] = None,
    mem_gb: int = 8,
    n_procs: int = 4,
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
    modalities : list, optional
        Modalities to process (T1w, T2w, bold, dwi). If None, auto-detect.
    mem_gb : int
        Memory limit in GB (default: 8)
    n_procs : int
        Number of parallel processes (default: 4)
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
    
    #  directories
    mriqc_out = sess.studydir / "derivatives" / "qc" / "mriqc"
    mriqc_work = mriqc_out / "work" / f"sub-{subject}_ses-{session}"
    mriqc_logs = mriqc_out / "logs"
    
    log_file = mriqc_logs / f"sub-{subject}_ses-{session}_mriqc.log"
    mriqc_logs.mkdir(parents=True, exist_ok=True)
    
    logger = setup_logging("qc", log_file, verbose)
    
    rawdata_root = sess.studydir / "rawdata"
    session_dir = rawdata_root / f"sub-{subject}" / f"ses-{session}"
    
    if not session_dir.exists():
        logger.error(f"Session directory not found: {session_dir}")
        return False
    
    logger.info(f"Running MRIQC for sub-{subject}_ses-{session}")
    
    # existing output
    subj_out = mriqc_out / f"sub-{subject}"
    if subj_out.exists() and any(subj_out.rglob("*.html")) and not force:
        logger.info(f"MRIQC reports already exist. Use --force to regenerate.")
        return True
    
    # find modalities if not specified
    if modalities is None:
        modalities = _detect_modalities(session_dir, logger)
    
    if not modalities:
        logger.warning("No processable modalities found (T1w, T2w, bold, dwi)")
        return True
    
    logger.info(f"Modalities: {modalities}")
    
    # directories
    mriqc_out.mkdir(parents=True, exist_ok=True)
    mriqc_work.mkdir(parents=True, exist_ok=True)
    
    # docker command
    user_args = get_docker_user_args()
    
    cmd = [
        "docker", "run", "--rm",
        *user_args,
        "--volume", f"{rawdata_root}:/data:ro",
        "--volume", f"{mriqc_out}:/out",
        "--volume", f"{mriqc_work}:/work",
        "nipreps/mriqc:latest",
        "/data",
        "/out",
        "participant",
        "--participant-label", subject,
        "--session-id", session,
        "-w", "/work",
        "--verbose-reports",
        "--mem_gb", str(mem_gb),
        "--nprocs", str(n_procs),
        "--no-sub",
        "--modalities", *modalities,
    ]
    
    logger.debug(f"Command: {' '.join(cmd)}")
    
    # run MRIQC
    with open(log_file, "w") as logf:
        result = subprocess.run(cmd, stdout=logf, stderr=subprocess.STDOUT)
    
    if result.returncode != 0:
        logger.error(f"MRIQC failed with exit code {result.returncode}")
        logger.error(f"See log: {log_file}")
        return False
    
    # clean work directory
    if mriqc_work.exists():
        shutil.rmtree(mriqc_work, ignore_errors=True)
    
    logger.info("MRIQC completed successfully!")
    return True


def _detect_modalities(session_dir: Path, logger) -> List[str]:
    """Detect available modalities for MRIQC."""
    modalities = []
    
    anat_dir = session_dir / "anat"
    if anat_dir.exists():
        t1w = [f for f in anat_dir.glob("*_T1w.nii.gz") 
               if "inv-" not in f.name and "part-" not in f.name]
        if t1w:
            modalities.append("T1w")
        if list(anat_dir.glob("*_T2w.nii.gz")):
            modalities.append("T2w")
    
    if (session_dir / "func").exists() and list((session_dir / "func").glob("*_bold.nii.gz")):
        modalities.append("bold")
    
    if (session_dir / "dwi").exists() and list((session_dir / "dwi").glob("*_dwi.nii.gz")):
        modalities.append("dwi")
    
    return modalities
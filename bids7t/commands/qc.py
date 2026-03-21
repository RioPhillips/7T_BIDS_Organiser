"""qc. runs MRIQC quality control."""

import subprocess, shutil
from pathlib import Path
from typing import List, Optional
from bids7t.core import Session, setup_logging, get_docker_user_args


def run_qc(studydir: Path, subject: str, session: Optional[str] = None,
           modalities: Optional[List[str]] = None, mem_gb: int = 8,
           n_procs: int = 4, force: bool = False, verbose: bool = False) -> bool:
    sess = Session(studydir, subject, session)
    session_label = f"_ses-{session}" if session else ""
    work_label = f"sub-{subject}{session_label}"
    mriqc_out = sess.studydir / "derivatives" / "qc" / "mriqc"
    mriqc_work = mriqc_out / "work" / work_label
    mriqc_logs = mriqc_out / "logs"
    log_file = mriqc_logs / f"{work_label}_mriqc.log"
    mriqc_logs.mkdir(parents=True, exist_ok=True)
    logger = setup_logging("qc", log_file, verbose)
    rawdata_root = sess.studydir / "rawdata"
    session_dir = sess.paths["rawdata"]
    if not session_dir.exists():
        logger.error(f"Directory not found: {session_dir}"); return False
    logger.info(f"Running MRIQC for {work_label}")
    subj_out = mriqc_out / f"sub-{subject}"
    if subj_out.exists() and any(subj_out.rglob("*.html")) and not force:
        logger.info("Reports exist. Use --force to regenerate."); return True
    if modalities is None:
        modalities = _detect_modalities(session_dir)
    if not modalities:
        logger.warning("No processable modalities"); return True
    mriqc_out.mkdir(parents=True, exist_ok=True)
    mriqc_work.mkdir(parents=True, exist_ok=True)
    user_args = get_docker_user_args()
    cmd = ["docker", "run", "--rm", *user_args,
           "--volume", f"{rawdata_root}:/data:ro", "--volume", f"{mriqc_out}:/out",
           "--volume", f"{mriqc_work}:/work", "nipreps/mriqc:latest",
           "/data", "/out", "participant", "--participant-label", subject]
    if session:
        cmd.extend(["--session-id", session])
    cmd.extend(["-w", "/work", "--verbose-reports", "--mem_gb", str(mem_gb),
                "--nprocs", str(n_procs), "--no-sub", "--modalities", *modalities])
    with open(log_file, "w") as logf:
        result = subprocess.run(cmd, stdout=logf, stderr=subprocess.STDOUT)
    if mriqc_work.exists():
        shutil.rmtree(mriqc_work, ignore_errors=True)
    if result.returncode != 0:
        logger.error(f"MRIQC failed (code {result.returncode})"); return False
    logger.info("MRIQC completed!"); return True


def _detect_modalities(session_dir):
    mods = []
    anat = session_dir / "anat"
    if anat.exists():
        if [f for f in anat.glob("*_T1w.nii.gz") if "inv-" not in f.name and "part-" not in f.name]:
            mods.append("T1w")
    if (session_dir / "func").exists() and list((session_dir / "func").glob("*_bold.nii.gz")):
        mods.append("bold")
    if (session_dir / "dwi").exists() and list((session_dir / "dwi").glob("*_dwi.nii.gz")):
        mods.append("dwi")
    return mods
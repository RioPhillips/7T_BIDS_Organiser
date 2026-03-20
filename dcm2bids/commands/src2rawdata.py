"""
src2rawdata command - Convert sourcedata to BIDS rawdata using heudiconv.

This command runs heudiconv to convert DICOMs in sourcedata to NIfTI files
in the BIDS rawdata directory structure.

Session support:
- With session: heuristic templates MUST include {session} in paths
- Without session: heuristic templates should NOT include {session}
"""

import subprocess
import shutil
from pathlib import Path
from typing import Optional, List

from dcm2bids.core import (
    Session, 
    setup_logging, 
    run_command, 
    check_outputs_exist,
    load_config,
    get_heuristic_path,
    get_docker_user_args
)


def run_src2rawdata(
    studydir: Path,
    subject: str,
    session: Optional[str] = None,
    heuristic: Optional[Path] = None,
    force: bool = False,
    verbose: bool = False,
    use_docker: bool = False,
    notop: bool = False
) -> List[Path]:
    """
    Convert sourcedata to BIDS rawdata using heudiconv.
    
    Parameters
    ----------
    studydir : Path
        Path to BIDS study directory
    subject : str
        Subject ID (without sub- prefix)
    session : str or None
        Session ID (without ses- prefix). None for single-session studies.
    heuristic : Path, optional
        Path to heuristic file (defaults to config.json setting)
    force : bool
        Force overwrite existing files
    verbose : bool
        Enable verbose output
    use_docker : bool
        Run heudiconv via Docker
    notop : bool
        Skip creation of top-level BIDS files (for batch processing).
        Use 'dcm2bids populate-templates' afterwards to create them.
        
    Returns
    -------
    list
        List of created NIfTI files
    """
    sess = Session(studydir, subject, session)
    log_file = sess.paths["logs"] / "src2rawdata.log"
    logger = setup_logging("src2rawdata", log_file, verbose)
    
    session_label = f"_ses-{session}" if session else ""
    logger.info(f"Starting heudiconv for sub-{subject}{session_label}")
    
    # heuristic path
    if heuristic is None:
        config = load_config(studydir)
        heuristic = get_heuristic_path(studydir, config)
    
    if heuristic is None or not heuristic.exists():
        raise FileNotFoundError(
            f"Heuristic file not found. Please specify via --heuristic or in code/config.json"
        )
    
    logger.info(f"Using heuristic: {heuristic}")
    
    # check session consistency between heuristic and CLI
    _check_heuristic_session_consistency(heuristic, session, logger)
    
    sourcedata = sess.paths["sourcedata"]
    if not sourcedata.exists() or not any(sourcedata.iterdir()):
        raise FileNotFoundError(
            f"Sourcedata not found or empty: {sourcedata}\n"
            f"Run 'dcm2bids dcm2src' first."
        )
    
    # check outputs doesnt exist already
    rawdata = sess.paths["rawdata"]
    if rawdata.exists():
        existing_niftis = list(rawdata.rglob("*.nii.gz"))
        if existing_niftis:
            should_run, _ = check_outputs_exist(existing_niftis[:1], logger, force)
            if not should_run:
                return existing_niftis
            
            if force:
                logger.info(f"Removing existing rawdata: {rawdata}")
                shutil.rmtree(rawdata)
    
    # make dirs and run heudiconv
    sess.ensure_directories("rawdata", "logs")

    _run_heudiconv(
        sess=sess,
        heuristic=heuristic,
        use_docker=use_docker,
        notop=notop,
        logger=logger
    )
    
    # clean leftover cache
    _clean_heudiconv_cache(sess, logger)
    
    # remove ADC files 
    _remove_adc_files(sess, logger)
    
    created_files = list(rawdata.rglob("*.nii.gz"))
    logger.info(f"Successfully converted {len(created_files)} NIfTI files")
    
    if notop:
        logger.info("Note: Top-level BIDS files were skipped (--notop).")
        logger.info("Run 'dcm2bids populate-templates' to create them.")
    
    return created_files


def _check_heuristic_session_consistency(heuristic: Path, session: Optional[str], logger) -> None:
    """
    Check if heuristic file is consistent with session usage.
    
    Warns if:
    - Session provided but heuristic has no {session} in templates
    - No session but heuristic has {session} in templates
    """
    try:
        with open(heuristic, 'r') as f:
            content = f.read()
        
        has_session_in_heuristic = '{session}' in content
        
        if session and not has_session_in_heuristic:
            logger.warning("=" * 60)
            logger.warning("WARNING: --session provided but heuristic has no {session} templates!")
            logger.warning("Templates should include {session} in the path, e.g.:")
            logger.warning("  'sub-{subject}/{session}/anat/sub-{subject}_{session}_T1w'")
            logger.warning("Without this, files will NOT be organized by session.")
            logger.warning("=" * 60)
        
        if not session and has_session_in_heuristic:
            logger.warning("=" * 60)
            logger.warning("WARNING: No --session provided but heuristic uses {session}!")
            logger.warning("Either provide --session or use a heuristic without {session}.")
            logger.warning("Heudiconv may fail or produce unexpected output.")
            logger.warning("=" * 60)
            
    except Exception as e:
        logger.debug(f"Could not check heuristic for session support: {e}")


def _run_heudiconv(
    sess: Session,
    heuristic: Path,
    use_docker: bool,
    notop: bool,
    logger
) -> None:
    """Run heudiconv to convert DICOMs."""
    sourcedata_root = sess.studydir / "sourcedata"
    rawdata_root = sess.studydir / "rawdata"
    log_file = sess.paths["logs"] / "heudiconv.log"
    
    # build heudiconv arguments depending on session
    heudi_args = [
        "-s", sess.subject,
        "-c", "dcm2niix",
        "--dcmconfig", "/data/projects/7T049_Visual_Brain/7T049_CVI_pRF_lund/code/b1_fix.json"
    ]
    
    if sess.has_session:
        heudi_args.extend(["-ss", sess.session])
    
    if notop:
        logger.info("Using --notop mode (skipping top-level BIDS files)")
        heudi_args.extend(["-b", "notop"])
    else:
        heudi_args.append("-b")
    
    heudi_args.append("--overwrite")
    
    # build DICOM pattern based on session
    if sess.has_session:
        dicom_subpath = f"sub-{{subject}}/ses-{{session}}/*/*.dcm"
    else:
        dicom_subpath = f"sub-{{subject}}/*/*.dcm"
    
    if use_docker:
        logger.info("Running heudiconv via Docker")
        user_args = get_docker_user_args()
        
        cmd = [
            "docker", "run", "--rm",
            *user_args,
            "--volume", f"{sess.studydir}:/base",
            "--volume", f"{sourcedata_root}:/sourcedata:ro",
            "--volume", f"{rawdata_root}:/rawdata",
            "nipy/heudiconv:latest",
            "-d", f"/sourcedata/{dicom_subpath}",
            "-f", f"/base/code/{heuristic.name}",
            "-o", "/rawdata",
            *heudi_args
        ]
    else:
        logger.info("Running heudiconv locally")
        
        # pattern for finding DICOMs
        dicom_pattern = str(sourcedata_root / dicom_subpath)
        
        cmd = [
            "heudiconv",
            "-d", dicom_pattern,
            "-f", str(heuristic),
            "-o", str(rawdata_root),
            *heudi_args
        ]
    
    logger.debug(f"Command: {' '.join(cmd)}")
    run_command(cmd, logger, log_file)
    
    logger.info("Heudiconv completed successfully")


def _clean_heudiconv_cache(sess: Session, logger) -> None:
    """Remove heudiconv hidden cache directory."""
    heudiconv_dir = sess.studydir / "rawdata" / ".heudiconv"
    
    if heudiconv_dir.exists():
        # remove subject-specific files
        for f in heudiconv_dir.glob(f"{sess.subject}*"):
            logger.debug(f"Removing heudiconv cache: {f}")
            if f.is_dir():
                shutil.rmtree(f)
            else:
                f.unlink()


def _remove_adc_files(sess: Session, logger) -> None:
    """Remove redundant ADC files from dwi directory."""
    dwi_dir = sess.paths.get("dwi") or sess.paths["rawdata"] / "dwi"
    
    if not dwi_dir.exists():
        return
    
    for adc_file in dwi_dir.glob(f"*_ADC.nii.gz"):
        logger.info(f"Removing redundant ADC file: {adc_file.name}")
        adc_file.unlink()
        
        # remove JSON sidecar
        json_file = adc_file.with_suffix("").with_suffix(".json")
        if json_file.exists():
            json_file.unlink()
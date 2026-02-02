"""
src2rawdata command - Convert sourcedata to BIDS rawdata using heudiconv.

This command runs heudiconv to convert DICOMs in sourcedata to NIfTI files
in the BIDS rawdata directory structure.

IMPORTANT: Your heuristic file MUST include {session} in the template paths
for session-level organization to work. Example:
    create_key('sub-{subject}/{session}/anat/sub-{subject}_{session}_T1w')
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
    session: str,
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
    session : str
        Session ID (without ses- prefix)
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
    
    logger.info(f"Starting heudiconv for sub-{subject}_ses-{session}")
    
    # heuristic path
    if heuristic is None:
        config = load_config(studydir)
        heuristic = get_heuristic_path(studydir, config)
    
    if heuristic is None or not heuristic.exists():
        raise FileNotFoundError(
            f"Heuristic file not found. Please specify via --heuristic or in code/config.json"
        )
    
    logger.info(f"Using heuristic: {heuristic}")
    
    # check session in heuristic has session support
    # and sourcedata/-dir exists
    _check_heuristic_session_support(heuristic, logger)
    
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


def _check_heuristic_session_support(heuristic: Path, logger) -> None:
    """
    Check if heuristic file includes {session} in templates.
    
    Warns the user if session support appears to be missing.
    """
    try:
        with open(heuristic, 'r') as f:
            content = f.read()
        
        # checking some patterns for session support in the heuristic
        has_session_in_path = '{session}/' in content or '/{session}/' in content
        has_session_in_filename = '_ses-{session}_' in content
        
        if not has_session_in_path:
            logger.warning("=" * 60)
            logger.warning("WARNING: Your heuristic may not support sessions!")
            logger.warning("Templates should include {session} in the path, e.g.:")
            logger.warning("  'sub-{subject}/{session}/anat/sub-{subject}_ses-{session}_T1w'")
            logger.warning("Without this, files will NOT be organized by session.")
            logger.warning("=" * 60)
        elif not has_session_in_filename:
            logger.warning("Heuristic has {session} in path but not in filenames.")
            logger.warning("Consider using: sub-{subject}_ses-{session}_<suffix>")
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
    sourcedata_root = sess.paths["sourcedata"].parent.parent  # studydir/sourcedata
    rawdata_root = sess.paths["rawdata"].parent.parent  # studydir/rawdata
    log_file = sess.paths["logs"] / "heudiconv.log"
    
    # heudiconv arguments
    # note: -b notop must be passed as two separate arguments
    if notop:
        logger.info("Using --notop mode (skipping top-level BIDS files)")
        heudi_args = [
            "-s", sess.subject,
            "-ss", sess.session,
            "-c", "dcm2niix",
            "-b", "notop",
            "--overwrite"
        ]
    else:
        heudi_args = [
            "-s", sess.subject,
            "-ss", sess.session,
            "-c", "dcm2niix",
            "-b",
            "--overwrite"
        ]
    
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
            "-d", "/sourcedata/sub-{subject}/ses-{session}/*/*.dcm",
            "-f", f"/base/code/{heuristic.name}",
            "-o", "/rawdata",
            *heudi_args
        ]
    else:
        logger.info("Running heudiconv locally")
        
        # pattern for finding DICOMs
        dicom_pattern = str(sourcedata_root / "sub-{subject}" / "ses-{session}" / "*" / "*.dcm")
        
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
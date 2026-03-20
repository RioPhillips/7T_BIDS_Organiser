"""
dcm2src command - Import DICOMs to sourcedata directory.

Handles zip file inputs (e.g., S01_ses-MR1.zip) and organizes DICOMs
into the BIDS sourcedata structure:
    sourcedata/sub-{subject}/ses-{session}/<series_name>/*.dcm
"""

import shutil
import subprocess
from pathlib import Path
from typing import List, Optional

from dcm2bids.core import Session, setup_logging, run_command, check_outputs_exist


def run_dcm2src(
    studydir: Path,
    subject: str,
    session: str,
    dicom_dir: Path,
    force: bool = False,
    verbose: bool = False,
    zip_input: bool = False
) -> List[Path]:
    """
    Import DICOMs to sourcedata directory.
    
    The input can be:
    1. A zip file (e.g., S01_ses-MR1.zip) - will be auto-detected or use --zip-input
    2. A directory containing the zip file - will search for matching zip
    3. A directory containing DICOMs directly
    
    Parameters
    ----------
    studydir : Path
        Path to BIDS study directory
    subject : str
        Subject ID (without sub- prefix)
    session : str
        Session ID (without ses- prefix)
    dicom_dir : Path
        Path to source DICOM directory, zip file, or directory containing zip
    force : bool
        Force overwrite existing files
    verbose : bool
        Enable verbose output
    zip_input : bool
        Explicitly specify that input is a zip file
        
    Returns
    -------
    list
        List of created DICOM files
    """
    sess = Session(studydir, subject, session, dicom_dir)
    log_file = sess.paths["logs"] / "dcm2src.log"
    logger = setup_logging("dcm2src", log_file, verbose)
    
    logger.info(f"Starting DICOM import for sub-{subject}_ses-{session}")
    logger.info(f"Input path: {dicom_dir}")
    logger.info(f"Target: {sess.paths['sourcedata']}")
    
    # check if output exist
    sourcedata_dir = sess.paths["sourcedata"]
    if sourcedata_dir.exists() and any(sourcedata_dir.iterdir()):
        existing_files = list(sourcedata_dir.rglob("*.dcm"))
        should_run, _ = check_outputs_exist(existing_files[:1], logger, force)
        if not should_run:
            return existing_files
        
        if force:
            logger.info(f"Removing existing sourcedata: {sourcedata_dir}")
            shutil.rmtree(sourcedata_dir)
    
    # creates directories needed 
    sess.ensure_directories("sourcedata", "logs")
    
    # determine input type and find zip file if needed
    zip_file, dicom_source, temp_dir = _resolve_input(
        dicom_dir=dicom_dir,
        subject=subject,
        session=session,
        zip_input=zip_input,
        logger=logger
    )
    
    # extract the zip file if one was found and then run dcm2niix to organize
    # the dicom source to sourcedata
    try:
        if zip_file:
            temp_dir = sourcedata_dir.parent / f"temp_{subject}_ses-{session}"
            dicom_source = _extract_zip(zip_file, temp_dir, logger)
        
        created_files = _convert_to_sourcedata(sess, dicom_source, logger)
        logger.info(f"Successfully imported {len(created_files)} DICOM files")
        return created_files
        
    # clean up temp dirs
    finally:
        if temp_dir and temp_dir.exists():
            logger.info(f"Cleaning up temp directory: {temp_dir}")
            shutil.rmtree(temp_dir, ignore_errors=True)


def _resolve_input(
    dicom_dir: Path,
    subject: str,
    session: str,
    zip_input: bool,
    logger
) -> tuple[Optional[Path], Optional[Path], Optional[Path]]:
    """
    Resolve the input path to find zip file or DICOM directory.
    
    Returns
    -------
    tuple
        (zip_file, dicom_source, temp_dir)
        - zip_file: Path to zip file if found, None otherwise
        - dicom_source: Path to DICOM directory (if not zipped)
        - temp_dir: Will be set later if extraction is needed
    """
    dicom_dir = Path(dicom_dir)
    
    # works through 3 cases based on whats given 
    
    # 1: direct zip file path
    if dicom_dir.is_file() and dicom_dir.suffix == ".zip":
        logger.info(f"Input is a zip file: {dicom_dir.name}")
        return dicom_dir, None, None
    
    # 2: explicit zip_input flag but path is a directory - search for zip
    if zip_input and dicom_dir.is_dir():
        zip_file = _find_zip_file(dicom_dir, subject, session, logger)
        if zip_file:
            return zip_file, None, None
        raise FileNotFoundError(
            f"No matching zip file found for {subject}_ses-{session} in {dicom_dir}"
        )
    
    # 3: directory - check if it contains a matching zip or DICOMs
    if dicom_dir.is_dir():
        # trying to look for a matching zip file
        zip_file = _find_zip_file(dicom_dir, subject, session, logger)
        if zip_file:
            logger.info(f"Found matching zip file: {zip_file.name}")
            return zip_file, None, None
        
        # if not found assume it's a directory with .dcm 
        dcm_files = list(dicom_dir.rglob("*.dcm")) + list(dicom_dir.rglob("*.DCM"))
        if dcm_files:
            logger.info(f"Input is a DICOM directory with {len(dcm_files)} files")
            return None, dicom_dir, None
        
        # check for DICOM files without extension
        # by looking for subdirectories
        subdirs = [d for d in dicom_dir.iterdir() if d.is_dir()]
        if subdirs:
            logger.info(f"Input directory has {len(subdirs)} subdirectories, assuming DICOM source")
            return None, dicom_dir, None
        
        raise FileNotFoundError(
            f"No zip file or DICOM files found in {dicom_dir}"
        )
    
    raise FileNotFoundError(f"Input path does not exist: {dicom_dir}")


def _find_zip_file(directory: Path, subject: str, session: str, logger) -> Optional[Path]:
    """
    Find a zip file matching the subject/session pattern.
    
    Searches for patterns like:
    - S01_ses-MR1.zip
    - S01_MR1.zip
    - sub-S01_ses-MR1.zip
    - S01-ses-MR1.zip
    """
    patterns = [
        f"{subject}_ses-{session}.zip",
        f"{subject}_ses_{session}.zip",
        f"{subject}_{session}.zip",
        f"{subject}-ses-{session}.zip",
        f"sub-{subject}_ses-{session}.zip",
        f"sub-{subject}_ses_{session}.zip",
    ]
    
    # trying case-insensitive search
    all_zips = list(directory.glob("*.zip"))
    
    # first trying exact matches
    for pattern in patterns:
        zip_path = directory / pattern
        if zip_path.exists():
            return zip_path
    
    # then case-insensitive matching
    for zip_file in all_zips:
        name_lower = zip_file.name.lower()
        for pattern in patterns:
            if name_lower == pattern.lower():
                return zip_file
    
    # if not trying partial matching
    # i.e only condition = subject and session appear in filename
    for zip_file in all_zips:
        name_lower = zip_file.name.lower()
        if subject.lower() in name_lower and session.lower() in name_lower:
            logger.info(f"Found zip by partial match: {zip_file.name}")
            return zip_file
    
    return None


def _extract_zip(zip_path: Path, target_dir: Path, logger) -> Path:
    """Extract a zip file to target directory."""
    if not zip_path.exists():
        raise FileNotFoundError(f"Zip file not found: {zip_path}")
    
    # make sure target dir is empty
    if target_dir.exists():
        shutil.rmtree(target_dir)
    target_dir.mkdir(parents=True)
    
    logger.info(f"Extracting {zip_path.name} to {target_dir}")
    
    cmd = ["unzip", "-q", "-o", str(zip_path), "-d", str(target_dir)]
    result = subprocess.run(cmd, capture_output=True, text=True)
    
    # unzip return codes: 0=OK, 1=warnings, 81=unsupported compression
    # this is true on the dev machine atleast :)
    if result.returncode not in (0, 1, 81):
        if "password" in (result.stderr or "").lower():
            raise RuntimeError(
                f"Zip file appears to be encrypted: {zip_path}"
            )
        raise RuntimeError(
            f"Failed to extract {zip_path}: {result.stderr}"
        )
    
    if result.returncode == 81:
        logger.warning("Unzip reported unsupported compression (possibly for keyfile only). Continuing...")
    
    # find he actual DICOM root (which might be nested)
    dicom_root = _find_dicom_root(target_dir, logger)
    
    return dicom_root


def _find_dicom_root(extracted_dir: Path, logger) -> Path:
    """
    Find the root directory containing DICOMs after extraction.
    
    Sometimes zip files have nested directories, so we need to find
    where the actual DICOM files are.
    """
    # check if the DICOMs are directly in extracted_dir
    dcm_files = list(extracted_dir.glob("*.dcm")) + list(extracted_dir.glob("*.DCM"))
    if dcm_files:
        return extracted_dir
    
    # also check subdirectories (with depth=3)
    for depth in range(1, 4):
        pattern = "/".join(["*"] * depth)
        for subdir in extracted_dir.glob(pattern):
            if subdir.is_dir():
                dcm_files = list(subdir.glob("*.dcm")) + list(subdir.glob("*.DCM"))
                if dcm_files:
                    logger.debug(f"Found DICOMs at depth {depth}: {subdir}")
                    return subdir
    
    # unlikely but if no .dcm files found
    # return the extracted dir and let dcm2niix figure it out
    logger.warning("No .dcm files found in extracted directory, using root")
    return extracted_dir


def _convert_to_sourcedata(sess: Session, dicom_dir: Path, logger) -> List[Path]:
    """
    Run dcm2niix to reorganize DICOMs into sourcedata layout.
    
    Uses dcm2niix with -b o (no BIDS) to just reorganize files.
    """
    sourcedata = sess.paths["sourcedata"]
    log_file = sess.paths["logs"] / "dcm2niix_import.log"
    
    # dcm2niix command to reorganize DICOMs
    # -b o : output only DICOM reorganization (no NIfTI, no JSON)
    # -r y : rename instead of copy
    # -w 0 : skip duplicates
    # -f pattern : output filename pattern (series_name/dicom_number.dcm)
    cmd = [
        "dcm2niix",
        "-v", "0",
        "-b", "o",        
        "-r", "y",        
        "-w", "0",        
        "-o", str(sourcedata),
        "-f", "%s_%d/%d_%5r.dcm",  # series_name/series_dicom.dcm
        str(dicom_dir),
    ]
    
    run_command(cmd, logger, log_file)
    
    created_files = list(sourcedata.rglob("*.dcm"))
    logger.info(f"Organized {len(created_files)} DICOMs into sourcedata")
    
    return created_files

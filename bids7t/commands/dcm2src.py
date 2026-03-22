# dcm2src command to import DICOMs to sourcedata directory.
# handles zip file inputs and organizes DICOMs into the BIDS sourcedata structure.

import re
import shutil
import subprocess
from pathlib import Path
from typing import List, Optional, Tuple

from bids7t.core import Session, setup_logging, run_command, check_outputs_exist


def run_dcm2src(
    studydir: Path, subject: str, session: Optional[str] = None,
    dicom_dir: Path = None, force: bool = False, verbose: bool = False,
    zip_input: bool = False
) -> List[Path]:
    sess = Session(studydir, subject, session, dicom_dir)
    log_file = sess.paths["logs"] / "dcm2src.log"
    logger = setup_logging("dcm2src", log_file, verbose)
    
    session_label = f"_ses-{session}" if session else ""
    logger.info(f"Starting DICOM import for sub-{subject}{session_label}")
    logger.info(f"Input path: {dicom_dir}")
    
    # when session=None, check if dicom_dir has multiple session-specific zips
    # --> process each one into the correct session directory
    if session is None and dicom_dir is not None and Path(dicom_dir).is_dir():
        session_zips = _find_session_zips(Path(dicom_dir), subject, logger)
        if len(session_zips) > 1:
            logger.info(f"Found {len(session_zips)} session-specific zips, processing each")
            all_created = []
            for ses_id, zip_path in session_zips:
                logger.info(f"Processing session {ses_id} from {zip_path.name}")
                ses_sess = Session(studydir, subject, ses_id, dicom_dir)
                ses_sess.ensure_directories("sourcedata", "logs")
                created = _import_single_zip(
                    zip_path=zip_path, sess=ses_sess,
                    force=force, logger=logger
                )
                all_created.extend(created)
            logger.info(f"Imported {len(all_created)} DICOM files across {len(session_zips)} sessions")
            return all_created
    
    # standard single-session/single-zip 
    logger.info(f"Target: {sess.paths['sourcedata']}")
    
    sourcedata_dir = sess.paths["sourcedata"]
    if sourcedata_dir.exists() and any(sourcedata_dir.iterdir()):
        existing_files = list(sourcedata_dir.rglob("*.dcm"))
        should_run, _ = check_outputs_exist(existing_files[:1], logger, force)
        if not should_run:
            return existing_files
        if force:
            logger.info(f"Removing existing sourcedata: {sourcedata_dir}")
            shutil.rmtree(sourcedata_dir)
    
    sess.ensure_directories("sourcedata", "logs")
    
    zip_file, dicom_source, temp_dir = _resolve_input(
        dicom_dir=dicom_dir, subject=subject, session=session,
        zip_input=zip_input, logger=logger
    )
    
    try:
        if zip_file:
            temp_suffix = f"_{subject}"
            if session:
                temp_suffix += f"_ses-{session}"
            temp_dir = sourcedata_dir.parent / f"temp{temp_suffix}"
            dicom_source = _extract_zip(zip_file, temp_dir, logger)
        
        created_files = _convert_to_sourcedata(sess, dicom_source, logger)
        logger.info(f"Successfully imported {len(created_files)} DICOM files")
        return created_files
    finally:
        if temp_dir and temp_dir.exists():
            logger.info(f"Cleaning up temp directory: {temp_dir}")
            shutil.rmtree(temp_dir, ignore_errors=True)


def _find_session_zips(directory: Path, subject: str, logger) -> List[Tuple[str, Path]]:
    """
    Find all session-specific zip files for a subject in a directory.
    
    Looks for patterns like:
      sub-S01_ses-MR1*.zip, sub-S01_ses-MR2*.zip
      S01_ses-MR1*.zip, S01_MR1*.zip
    
    Returns list of (session_id, zip_path) tuples, sorted by session.
    Returns empty list if no session pattern detected.
    """
    all_zips = sorted(directory.glob("*.zip"))
    if not all_zips:
        return []
    
    # find zips matching this subject that contain a ses- identifier
    ses_pattern = re.compile(
        rf"(?:sub-)?{re.escape(subject)}.*?ses-([A-Za-z0-9]+)",
        re.IGNORECASE
    )
    
    found = []
    for zip_file in all_zips:
        if subject.lower() not in zip_file.name.lower():
            continue
        m = ses_pattern.search(zip_file.name)
        if m:
            ses_id = m.group(1)
            found.append((ses_id, zip_file))
    
    # only return if we found multiple. single zip is handled already
    if len(found) <= 1:
        return []
    
    logger.info(f"Found session zips: {[(s, z.name) for s, z in found]}")
    return sorted(found, key=lambda x: x[0])


def _import_single_zip(zip_path: Path, sess: Session, force: bool, logger) -> List[Path]:
    # extracts a single zip file into the session's sourcedata directory
    sourcedata_dir = sess.paths["sourcedata"]
    
    if sourcedata_dir.exists() and any(sourcedata_dir.iterdir()):
        if not force:
            existing = list(sourcedata_dir.rglob("*.dcm"))
            logger.info(f"Sourcedata folder exists for ses-{sess.session} ({len(existing)} files), skipping")
            return existing
        shutil.rmtree(sourcedata_dir)
    
    sourcedata_dir.mkdir(parents=True, exist_ok=True)
    
    temp_dir = sourcedata_dir.parent / f"temp_{sess.subject}_ses-{sess.session}"
    try:
        dicom_source = _extract_zip(zip_path, temp_dir, logger)
        created_files = _convert_to_sourcedata(sess, dicom_source, logger)
        logger.info(f"  Imported {len(created_files)} DICOMs for ses-{sess.session}")
        return created_files
    finally:
        if temp_dir.exists():
            shutil.rmtree(temp_dir, ignore_errors=True)


def _resolve_input(dicom_dir, subject, session, zip_input, logger):
    dicom_dir = Path(dicom_dir)
    
    if dicom_dir.is_file() and dicom_dir.suffix == ".zip":
        logger.info(f"Input is a zip file: {dicom_dir.name}")
        return dicom_dir, None, None
    
    if zip_input and dicom_dir.is_dir():
        zip_file = _find_zip_file(dicom_dir, subject, session, logger)
        if zip_file:
            return zip_file, None, None
        session_label = f"_ses-{session}" if session else ""
        raise FileNotFoundError(f"No matching zip found for {subject}{session_label} in {dicom_dir}")
    
    if dicom_dir.is_dir():
        zip_file = _find_zip_file(dicom_dir, subject, session, logger)
        if zip_file:
            logger.info(f"Found matching zip file: {zip_file.name}")
            return zip_file, None, None
        
        dcm_files = list(dicom_dir.rglob("*.dcm")) + list(dicom_dir.rglob("*.DCM"))
        if dcm_files:
            logger.info(f"Input is a DICOM directory with {len(dcm_files)} files")
            return None, dicom_dir, None
        
        subdirs = [d for d in dicom_dir.iterdir() if d.is_dir()]
        if subdirs:
            logger.info(f"Input directory has {len(subdirs)} subdirectories, assuming DICOM source")
            return None, dicom_dir, None
        
        raise FileNotFoundError(f"No zip file or DICOM files found in {dicom_dir}")
    
    raise FileNotFoundError(f"Input path does not exist: {dicom_dir}")


def _find_zip_file(directory, subject, session, logger):
    patterns = []
    if session:
        patterns.extend([
            f"{subject}_ses-{session}.zip", f"{subject}_{session}.zip",
            f"sub-{subject}_ses-{session}.zip",
        ])
    else:
        patterns.extend([f"{subject}.zip", f"sub-{subject}.zip"])
    
    all_zips = list(directory.glob("*.zip"))
    
    for pattern in patterns:
        if (directory / pattern).exists():
            return directory / pattern
    
    for zip_file in all_zips:
        name_lower = zip_file.name.lower()
        for pattern in patterns:
            if name_lower == pattern.lower():
                return zip_file
    
    for zip_file in all_zips:
        name_lower = zip_file.name.lower()
        if subject.lower() in name_lower:
            if session is None or session.lower() in name_lower:
                logger.info(f"Found zip by partial match: {zip_file.name}")
                return zip_file
    return None


def _extract_zip(zip_path, target_dir, logger):
    if not zip_path.exists():
        raise FileNotFoundError(f"Zip file not found: {zip_path}")
    if target_dir.exists():
        shutil.rmtree(target_dir)
    target_dir.mkdir(parents=True)
    
    logger.info(f"Extracting {zip_path.name} to {target_dir}")
    cmd = ["unzip", "-q", "-o", str(zip_path), "-d", str(target_dir)]
    result = subprocess.run(cmd, capture_output=True, text=True)
    
    if result.returncode not in (0, 1, 81):
        if "password" in (result.stderr or "").lower():
            raise RuntimeError(f"Zip file appears to be encrypted: {zip_path}")
        raise RuntimeError(f"Failed to extract {zip_path}: {result.stderr}")
    
    return _find_dicom_root(target_dir, logger)


def _find_dicom_root(extracted_dir, logger):
    dcm_files = list(extracted_dir.glob("*.dcm")) + list(extracted_dir.glob("*.DCM"))
    if dcm_files:
        return extracted_dir
    for depth in range(1, 4):
        pattern = "/".join(["*"] * depth)
        for subdir in extracted_dir.glob(pattern):
            if subdir.is_dir():
                dcm_files = list(subdir.glob("*.dcm")) + list(subdir.glob("*.DCM"))
                if dcm_files:
                    return subdir
    logger.warning("No .dcm files found in extracted directory, using root")
    return extracted_dir


def _convert_to_sourcedata(sess, dicom_dir, logger):
    sourcedata = sess.paths["sourcedata"]
    log_file = sess.paths["logs"] / "dcm2niix_import.log"
    
    cmd = [
        "dcm2niix", "-v", "0", "-b", "o", "-r", "y", "-w", "0",
        "-o", str(sourcedata),
        "-f", "%s_%d/%d_%5r.dcm",
        str(dicom_dir),
    ]
    run_command(cmd, logger, log_file)
    
    created_files = list(sourcedata.rglob("*.dcm"))
    logger.info(f"Organized {len(created_files)} DICOMs into sourcedata")
    return created_files
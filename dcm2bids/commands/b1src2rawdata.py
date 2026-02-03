"""
b1src2rawdata command - Convert B1 map DICOMs to BIDS rawdata.

Converts B1 map DICOMs using dcm2niix directly.
This is a workaround for heudiconv issues with B1 maps that cause
incorrect file naming.

When using compatible dcm2niix versions, produces correct output like:
  sub-ID_acq-b1_run-1_epi_e1a.nii.gz
  sub-ID_acq-b1_run-1_epi_e1_ph.nii.gz
  
NOTE: Requires dcm2niix v1.0.20220720 or compatible version.
Some newer versions (e.g., v1.0.20250505) have issues with Philips B1 maps.
"""

import subprocess
from pathlib import Path
from typing import List

from dcm2bids.core import Session, setup_logging


def run_b1src2rawdata(
    studydir: Path,
    subject: str,
    session: str,
    force: bool = False,
    verbose: bool = False
) -> List[Path]:
    """
    Convert B1 map DICOMs to BIDS rawdata using dcm2niix.
    
    Parameters
    ----------
    studydir : Path
        Path to BIDS study directory
    subject : str
        Subject ID (without sub- prefix)
    session : str
        Session ID (without ses- prefix)
    force : bool
        Force overwrite existing files
    verbose : bool
        Enable verbose output
        
    Returns
    -------
    list
        List of created files
    """
    sess = Session(studydir, subject, session)
    log_file = sess.paths["logs"] / "b1src2rawdata.log"
    logger = setup_logging("b1src2rawdata", log_file, verbose)
    
    logger.info(f"Converting B1 maps for sub-{subject}_ses-{session}")
    
    # some newer dcm2niix versions crashes for the B1 files - to be investigated
    # for now run older version  
    _check_dcm2niix_version(logger)
    
    sourcedata = sess.paths["sourcedata"]
    fmap_dir = sess.paths["fmap"]
    
    # b1 map directories in sourcedata
    b1_dirs = _find_b1_dirs(sourcedata)
    
    if not b1_dirs:
        logger.info("No B1map DICOM directories found in sourcedata")
        return []
    
    logger.info(f"Found {len(b1_dirs)} B1map directories: {[d.name for d in b1_dirs]}")
    

    fmap_dir.mkdir(parents=True, exist_ok=True)
    

    created_files = []
    for run_idx, b1_dir in enumerate(b1_dirs, start=1):
        files = _convert_b1_dir(
            b1_dir=b1_dir,
            fmap_dir=fmap_dir,
            sess=sess,
            run=run_idx,
            force=force,
            logger=logger
        )
        created_files.extend(files)
    
    logger.info(f"Created {len(created_files)} B1 map files")
    return created_files


def _check_dcm2niix_version(logger) -> None:
    """Check dcm2niix version and warn if problematic."""
    try:
        result = subprocess.run(
            ['dcm2niix', '-h'],
            capture_output=True,
            text=True,
            timeout=5
        )
        
        if result.returncode == 0 and result.stdout:
            version_line = result.stdout.split('\n')[0]
            logger.debug(f"dcm2niix version: {version_line}")
            
            # these versions have had problems
            problematic_versions = ['v1.0.20250505', 'v1.0.202505']
            
            for bad_version in problematic_versions:
                if bad_version in version_line:
                    logger.warning("="*60)
                    logger.warning(f"WARNING: Detected dcm2niix {bad_version}")
                    logger.warning("This version has known issues with Philips B1 maps")
                    logger.warning("and may produce incorrect file naming (e.g., _r100, _r20).")
                    logger.warning("")
                    logger.warning("Recommended: Install dcm2niix v1.0.20220720")
                    logger.warning("  conda install -c conda-forge dcm2niix=1.0.20220720")
                    logger.warning("")
                    logger.warning("Please check the fmap directory after conversion!")
                    logger.warning("="*60)
                    break
            
    except Exception as e:
        logger.debug(f"Could not check dcm2niix version: {e}")


def _find_b1_dirs(sourcedata: Path) -> List[Path]:
    """Find B1 map DICOM directories in sourcedata."""
    if not sourcedata.exists():
        return []
    
    b1_dirs = [
        d for d in sorted(sourcedata.iterdir())
        if d.is_dir() and "b1map" in d.name.lower()
    ]
    
    return b1_dirs



def _convert_b1_dir(
    b1_dir: Path,
    fmap_dir: Path,
    sess: Session,
    run: int,
    force: bool,
    logger
) -> List[Path]:
    """
    Convert a single B1 map DICOM directory.
    
    Parameters
    ----------
    b1_dir : Path
        Path to B1 DICOM directory
    fmap_dir : Path
        Output fmap directory
    sess : Session
        Session object
    run : int
        Run number
    force : bool
        Force overwrite
    logger
        Logger instance
        
    Returns
    -------
    list
        List of created files
    """
    prefix = sess.subses_prefix
    base_name = f"{prefix}_acq-b1_run-{run}_TB1map"
    
    # checking so output doesnt already exist
    existing = list(fmap_dir.glob(f"{base_name}*.nii.gz"))
    
    if existing and not force:
        logger.info(f"B1 run-{run} already converted ({len(existing)} files)")
        logger.info("Run with --force to reconvert")
        return existing
    
    # if -force
    if existing and force:
        for f in existing:
            # remove metadata
            rel_path = f"fmap/{f.name}"
            sess.remove_from_scans_tsv(rel_path)
            
            f.unlink()
            json_f = f.with_suffix("").with_suffix(".json")
            if json_f.exists():
                json_f.unlink()
    
    logger.info(f"Converting B1 run-{run} from {b1_dir.name}")
    
    # dcm2niix
    # -b y : create BIDS sidecar JSON
    # -z y : compress output
    # -p n : no protocol in filename (we specify our own)
    # -f   : output filename pattern
    cmd = [
        "dcm2niix",
        "-b", "y",
        "-z", "y",
        "-p", "n",
        "-f", base_name,
        "-o", str(fmap_dir),
        str(b1_dir)
    ]
    
    logger.debug(f"Running: {' '.join(cmd)}")
    
    result = subprocess.run(cmd, capture_output=True, text=True)
    
    if result.returncode != 0:
        logger.error(f"dcm2niix failed for {b1_dir.name}")
        logger.error(f"stderr: {result.stderr}")
        raise RuntimeError(f"dcm2niix failed for B1 map: {b1_dir}")
    
    
    if result.stdout and logger.level <= 10:
        logger.debug("dcm2niix output:")
        for line in result.stdout.splitlines()[:20]:
            logger.debug(f"  {line}")
    
    # output files
    created_niftis = sorted(fmap_dir.glob(f"{base_name}*.nii.gz"))
    created_jsons = sorted(fmap_dir.glob(f"{base_name}*.json"))
    
    if not created_niftis:
        logger.warning(f"No NIfTI files created for {b1_dir.name}")
        logger.warning("dcm2niix may have created files with unexpected names")
        
        
        all_b1 = sorted(fmap_dir.glob(f"{prefix}_acq-b1_*.nii.gz"))
        if all_b1:
            logger.warning(f"Found {len(all_b1)} B1 files in output:")
            for f in all_b1[:5]:  
                logger.warning(f"  - {f.name}")
            if len(all_b1) > 5:
                logger.warning(f"  ... and {len(all_b1) - 5} more")
        
        return []
    
    logger.info(f"  Created {len(created_niftis)} NIfTI + {len(created_jsons)} JSON files")
    
    # adds metadata
    for nii_file in created_niftis:
        rel_path = f"fmap/{nii_file.name}"
        

        acq_time = _get_acq_time_from_json(nii_file, sess, logger)
        
        sess.add_to_scans_tsv(rel_path, acq_time=acq_time)
        logger.debug(f"  Added to scans.tsv: {rel_path}")
    
    for f in created_niftis:
        logger.debug(f"  - {f.name}")
    
    return created_niftis + created_jsons


def _get_acq_time_from_json(nii_file: Path, sess: Session, logger) -> str:
    """
    Extract acquisition time from the JSON sidecar.
    
    Parameters
    ----------
    nii_file : Path
        Path to NIfTI file
    sess : Session
        Session object
    logger
        Logger instance
        
    Returns
    -------
    str
        Acquisition time in BIDS format, or "n/a" if not found
    """
    try:
        meta = sess.get_json(nii_file)
        
        # different fields that dcm2niix might populate

        if "AcquisitionDateTime" in meta:
            # format: "2022-12-30T10:27:53.770000"
            return meta["AcquisitionDateTime"]
        
        # combining AcquisitionDate and AcquisitionTime
        if "AcquisitionDate" in meta and "AcquisitionTime" in meta:
            date = meta["AcquisitionDate"]
            time = meta["AcquisitionTime"]
            if len(date) == 8:  # YYYYMMDD
                date = f"{date[:4]}-{date[4:6]}-{date[6:8]}"
            if ":" not in time and len(time) >= 6:  # HHMMSS
                time = f"{time[:2]}:{time[2:4]}:{time[4:]}"
            return f"{date}T{time}"
        
        if "AcquisitionTime" in meta:
            time = meta["AcquisitionTime"]
            if ":" not in time and len(time) >= 6:
                time = f"{time[:2]}:{time[2:4]}:{time[4:]}"
            return f"T{time}"
        
    except Exception as e:
        logger.debug(f"Could not extract acq_time from JSON: {e}")
    
    return "n/a"
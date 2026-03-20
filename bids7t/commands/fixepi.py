"""
fixepi command - Fix EPI JSON metadata.

This command:
- Updates PhaseEncodingDirection in SE-EPI JSON files
- Calculates and adds TotalReadoutTime from DICOM metadata
"""

from pathlib import Path
from typing import List

import pydicom

from dcm2bids.core import Session, setup_logging


def run_fixepi(
    studydir: Path,
    subject: str,
    session: str,
    ap_phase_enc: str = "j-",
    force: bool = False,
    verbose: bool = False
) -> None:
    """
    Fix EPI JSON metadata.
    
    Parameters
    ----------
    studydir : Path
        Path to BIDS study directory
    subject : str
        Subject ID (without sub- prefix)
    session : str
        Session ID (without ses- prefix)
    ap_phase_enc : str
        Phase encoding direction for AP scans (default: j-)
    force : bool
        Force overwrite existing files
    verbose : bool
        Enable verbose output
    """
    sess = Session(studydir, subject, session)
    log_file = sess.paths["logs"] / "fixepi.log"
    logger = setup_logging("fixepi", log_file, verbose)
    
    fmap_dir = sess.paths["fmap"]
    sourcedata_dir = sess.paths["sourcedata"]
    
    if not fmap_dir.exists():
        logger.warning(f"fmap directory not found: {fmap_dir}")
        return
    
    if not sourcedata_dir.exists():
        logger.warning(f"sourcedata directory not found: {sourcedata_dir}")
        return
    
    logger.info(f"Updating EPI JSONs for sub-{subject}_ses-{session}")
    
    # phase encoding directions from config
    phase_dirs = _get_phase_directions(ap_phase_enc, logger)
    if not phase_dirs:
        return
    
    # then just loop through
    for direction, ped in phase_dirs.items():
        _update_direction_jsons(
            fmap_dir=fmap_dir,
            sourcedata_dir=sourcedata_dir,
            sess=sess,
            direction=direction,
            ped=ped,
            force=force,
            logger=logger
        )
    
    logger.info("EPI JSON updates complete")


def _get_phase_directions(ap_phase_enc: str, logger) -> dict:
    """
    Get phase encoding directions for AP and PA.
    
    Parameters
    ----------
    ap_phase_enc : str
        AP phase encoding (e.g., 'j-')
        
    Returns
    -------
    dict
        {'AP': 'j-', 'PA': 'j'} style mapping
    """
    if len(ap_phase_enc) == 2 and ap_phase_enc[1] == '-':
        # e.g., 'j-' -> AP='j-', PA='j'
        return {
            "AP": ap_phase_enc,
            "PA": ap_phase_enc[0]
        }
    elif len(ap_phase_enc) == 1:
        # e.g., 'j' -> AP='j', PA='j-'
        return {
            "AP": ap_phase_enc,
            "PA": ap_phase_enc + "-"
        }
    else:
        logger.error(f"Invalid ap_phase_enc: {ap_phase_enc}")
        return {}


def _update_direction_jsons(
    fmap_dir: Path,
    sourcedata_dir: Path,
    sess: Session,
    direction: str,
    ped: str,
    force: bool,
    logger
) -> None:
    """Update JSON files for a specific phase encoding direction."""
    prefix = sess.subses_prefix
    
    # json files for this direction
    json_files = sorted(fmap_dir.glob(f"*{direction}*.json"))
    
    if not json_files:
        logger.debug(f"No JSON files found for direction {direction}")
        return
    
    # corresponding DICOM series in sourcedata
    series_dirs = [
        p for p in sourcedata_dir.iterdir()
        if p.is_dir() and direction in p.name
    ]
    
    if not series_dirs:
        logger.warning(f"No SE-EPI DICOM series found for {direction}")
        return
    
    # DICOM file for metadata
    dcm_files = list(series_dirs[0].glob("*.dcm"))
    if not dcm_files:
        logger.warning(f"No DICOM files in {series_dirs[0].name}")
        return
    
    dcm_file = dcm_files[0]
    logger.info(f"Using DICOM {dcm_file.name} for {direction} metadata")
    
    # updates for each JSON
    for json_file in json_files:
        _update_single_json(
            json_file=json_file,
            dcm_file=dcm_file,
            ped=ped,
            sess=sess,
            force=force,
            logger=logger
        )


def _update_single_json(
    json_file: Path,
    dcm_file: Path,
    ped: str,
    sess: Session,
    force: bool,
    logger
) -> None:
    """Update a single JSON file with phase encoding metadata."""
    nii_file = json_file.with_suffix(".nii.gz")
    meta = sess.get_json(nii_file)
    
    # check if already updated
    if not force and "TotalReadoutTime" in meta and "PhaseEncodingDirection" in meta:
        logger.debug(f"Already updated: {json_file.name}")
        return
    
    # DICOM metadata
    try:
        ds = pydicom.dcmread(str(dcm_file))
        
        # philips-specific tags for readout time calculation
        water_fat_shift = ds[0x2001, 0x1022].value  # water wat shift
        imag_freq = ds[0x0018, 0x0084].value        # imaging frequency
        epi_factor = ds[0x2001, 0x1013].value       # epi Factor
        
    except KeyError as e:
        logger.error(f"Missing DICOM tag {e} in {dcm_file}")
        return
    except Exception as e:
        logger.error(f"Error reading DICOM {dcm_file}: {e}")
        return
    
    # calculates readout time
    # formula for philips scanners
    actual_echo_spacing = water_fat_shift / (imag_freq * 3.4 * (epi_factor + 1))
    total_readout_time = actual_echo_spacing * epi_factor
    
    # then update JSON
    sess.make_writable(json_file)
    
    meta["PhaseEncodingDirection"] = ped
    meta["TotalReadoutTime"] = total_readout_time
    
    sess.write_json(nii_file, meta)
    sess.make_readonly(json_file)
    
    logger.info(f"Updated {json_file.name}: PED={ped}, TRT={total_readout_time:.6f}")

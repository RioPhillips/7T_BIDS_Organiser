"""
fixepi command. Handles EPI JSON metadata (PhaseEncodingDirection, TotalReadoutTime).

Reads Philips-specific DICOM tags from sourcedata to compute
TotalReadoutTime and sets PhaseEncodingDirection for SE-EPI fieldmaps.
"""

from pathlib import Path
from typing import Optional
import pydicom
from bids7t.core import Session, setup_logging


def run_fixepi(studydir: Path, subject: str, session: Optional[str] = None,
               ap_phase_enc: str = "j-", force: bool = False, verbose: bool = False) -> None:
    sess = Session(studydir, subject, session)
    log_file = sess.paths["logs"] / "fixepi.log"
    logger = setup_logging("fixepi", log_file, verbose)
    
    fmap_dir = sess.paths["fmap"]
    sourcedata_dir = sess.paths["sourcedata"]
    
    if not fmap_dir.exists():
        logger.info("fmap directory not found, skipping")
        return
    if not sourcedata_dir.exists():
        logger.warning("sourcedata directory not found, cannot compute readout time")
        return

    session_label = f"_ses-{session}" if session else ""
    logger.info(f"Updating EPI JSONs for sub-{subject}{session_label}")
    
    phase_dirs = _get_phase_directions(ap_phase_enc, logger)
    if not phase_dirs:
        return
    
    for direction, ped in phase_dirs.items():
        _update_direction_jsons(fmap_dir, sourcedata_dir, sess, direction, ped, force, logger)
    
    logger.info("EPI JSON updates complete")


def _get_phase_directions(ap_phase_enc, logger):
    if len(ap_phase_enc) == 2 and ap_phase_enc[1] == '-':
        return {"AP": ap_phase_enc, "PA": ap_phase_enc[0]}
    elif len(ap_phase_enc) == 1:
        return {"AP": ap_phase_enc, "PA": ap_phase_enc + "-"}
    logger.error(f"Invalid ap_phase_enc: {ap_phase_enc}")
    return {}


def _update_direction_jsons(fmap_dir, sourcedata_dir, sess, direction, ped, force, logger):
    json_files = sorted(fmap_dir.glob(f"*{direction}*.json"))
    if not json_files:
        return
    
    series_dirs = [p for p in sourcedata_dir.iterdir() if p.is_dir() and direction in p.name]
    if not series_dirs:
        logger.warning(f"No DICOM series found for {direction}")
        return
    
    dcm_files = list(series_dirs[0].glob("*.dcm"))
    if not dcm_files:
        return
    
    dcm_file = dcm_files[0]
    logger.info(f"Using DICOM {dcm_file.name} for {direction} metadata")
    
    for json_file in json_files:
        nii_file = json_file.with_suffix(".nii.gz")
        meta = sess.get_json(nii_file)
        
        if not force and "TotalReadoutTime" in meta and "PhaseEncodingDirection" in meta:
            continue
        
        try:
            ds = pydicom.dcmread(str(dcm_file))
            wfs = ds[0x2001, 0x1022].value   # Water Fat Shift (Philips)
            imf = ds[0x0018, 0x0084].value   # Imaging Frequency
            epf = ds[0x2001, 0x1013].value   # EPI Factor (Philips)
        except Exception as e:
            logger.error(f"Error reading DICOM: {e}")
            continue
        
        # Philips TotalReadoutTime formula
        aes = wfs / (imf * 3.4 * (epf + 1))
        trt = aes * epf
        
        sess.make_writable(json_file)
        meta["PhaseEncodingDirection"] = ped
        meta["TotalReadoutTime"] = trt
        sess.write_json(nii_file, meta)
        sess.make_readonly(json_file)
        logger.info(f"Updated {json_file.name}: PED={ped}, TRT={trt:.6f}")
"""
fixepi command. Handles EPI JSON metadata (PhaseEncodingDirection, TotalReadoutTime).

Reads Philips-specific DICOM tags from sourcedata to compute
TotalReadoutTime and sets PhaseEncodingDirection for SE-EPI fieldmaps.
"""

from pathlib import Path
from typing import Optional, Dict, List
import pydicom

from bids7t.core import Session, setup_logging
from bids7t.core.bids_naming import parse_bids_name


def run_fixepi(studydir: Path, subject: str, session: Optional[str] = None,
               ap_phase_enc: str = "j-", force: bool = False,
               verbose: bool = False) -> None:
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
        _update_direction_jsons(
            fmap_dir, sourcedata_dir, sess, direction, ped, force, logger
        )

    logger.info("EPI JSON updates complete")


def _get_phase_directions(ap_phase_enc: str, logger) -> Dict[str, str]:
    """
    Parse the AP phase encoding direction into AP and PA values.

    Parameters
    ----------
    ap_phase_enc : str
        Phase encoding direction for AP scans (e.g. 'j-' or 'j').

    Returns
    -------
    dict
        {'AP': ped_value, 'PA': ped_value} or empty dict on error.
    """
    if len(ap_phase_enc) == 2 and ap_phase_enc[1] == '-':
        return {"AP": ap_phase_enc, "PA": ap_phase_enc[0]}
    elif len(ap_phase_enc) == 1:
        return {"AP": ap_phase_enc, "PA": ap_phase_enc + "-"}
    logger.error(f"Invalid ap_phase_enc: {ap_phase_enc}")
    return {}


def _update_direction_jsons(fmap_dir: Path, sourcedata_dir: Path,
                            sess: Session, direction: str, ped: str,
                            force: bool, logger) -> None:
    """
    Update EPI JSON sidecars for a specific phase encoding direction.

    Discovers EPI files by suffix + dir entity (e.g. dir-AP) instead of
    string-matching "AP" anywhere in the filename. This prevents false
    positives from entities like acq-WRAP.

    Also searches for ANY fmap file with the dir entity matching,
    in case the user mapped SE fieldmaps to a non-epi suffix.

    Parameters
    ----------
    direction : str
        'AP' or 'PA'
    ped : str
        Phase encoding direction value (e.g. 'j-' or 'j')
    """
    # find EPI files with this dir entity
    epi_jsons = sess.find_by_suffix(
        "fmap", "epi", {"dir": direction}, extension="*.json"
    )

    if not epi_jsons:
        return

    # find matching DICOM series in sourcedata for readout time computation
    series_dirs = [
        p for p in sourcedata_dir.iterdir()
        if p.is_dir() and direction in p.name
    ]
    if not series_dirs:
        logger.warning(f"No DICOM series found for {direction}")
        return

    dcm_files = list(series_dirs[0].glob("*.dcm"))
    if not dcm_files:
        return

    dcm_file = dcm_files[0]
    logger.info(f"Using DICOM {dcm_file.name} for {direction} metadata")

    for json_file in epi_jsons:
        nii_file = json_file.with_suffix("").with_suffix(".nii.gz")
        # handle .nii.gz -> the json might correspond to a .nii.gz file
        if not nii_file.exists():
            nii_file = json_file.with_suffix(".nii.gz")
        meta = sess.get_json(nii_file)

        if (not force and
                "TotalReadoutTime" in meta and
                "PhaseEncodingDirection" in meta):
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
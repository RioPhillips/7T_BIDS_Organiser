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

    PhaseEncodingDirection comes from the dir entity + config. TotalReadoutTime
    is taken from the EPI's own dcm2niix EstimatedTotalReadoutTime, falling back
    to a Philips WFS computation from the correctly-matched SE-EPI DICOM.
    """
    epi_jsons = sess.find_by_suffix(
        "fmap", "epi", {"dir": direction}, extension="*.json"
    )
    if not epi_jsons:
        return

    for json_file in epi_jsons:
        nii_file = json_file.with_suffix("").with_suffix(".nii.gz")
        if not nii_file.exists():
            nii_file = json_file.with_suffix(".nii.gz")
        meta = sess.get_json(nii_file)

        if (not force and
                "TotalReadoutTime" in meta and
                "PhaseEncodingDirection" in meta):
            continue

        trt = _resolve_epi_trt(sess, nii_file, sourcedata_dir, direction, logger)
        if trt is None:
            logger.warning(
                f"  {nii_file.name}: could not determine TotalReadoutTime; "
                f"setting PhaseEncodingDirection only"
            )

        sess.make_writable(json_file)
        meta["PhaseEncodingDirection"] = ped
        if trt is not None:
            meta["TotalReadoutTime"] = trt
        sess.write_json(nii_file, meta)
        sess.make_readonly(json_file)
        trt_str = f", TRT={trt:.6f}" if trt is not None else ""
        logger.info(f"Updated {json_file.name}: PED={ped}{trt_str}")


def _resolve_epi_trt(sess, nii_file: Path, sourcedata_dir: Path,
                     direction: str, logger) -> Optional[float]:
    """Prefer dcm2niix's EstimatedTotalReadoutTime; fall back to DICOM."""
    meta = sess.get_json(nii_file)
    if "EstimatedTotalReadoutTime" in meta:
        try:
            return float(meta["EstimatedTotalReadoutTime"])
        except (TypeError, ValueError):
            pass
    return _trt_from_epi_dicom(sourcedata_dir, direction, logger)


def _trt_from_epi_dicom(sourcedata_dir: Path, direction: str,
                        logger) -> Optional[float]:
    """
    Compute TRT from the SE-EPI fieldmap DICOM for this direction.

    Requires 'dir-<direction>' in the folder name and excludes BOLD/func
    series, so the 'AP' fieldmap is never confused with an
    'fmri_..._dir-AP' BOLD series.
    """
    candidate = None
    for p in sorted(sourcedata_dir.iterdir()):
        if not p.is_dir():
            continue
        name = p.name.lower()
        if f"dir-{direction}".lower() not in name:
            continue
        if any(x in name for x in ("fmri", "bold", "func")):
            continue
        candidate = p
        break
    if candidate is None:
        return None
    dcms = list(candidate.glob("*.dcm")) + list(candidate.glob("*.DCM"))
    if not dcms:
        return None
    try:
        ds = pydicom.dcmread(str(sorted(dcms)[0]), stop_before_pixels=True)
        wfs = ds[0x2001, 0x1022].value   # Water Fat Shift (Philips)
        imf = ds[0x0018, 0x0084].value   # Imaging Frequency
        epf = ds[0x2001, 0x1013].value   # EPI Factor (Philips)
        return (wfs / (imf * 3.4 * (epf + 1))) * epf
    except Exception as e:
        logger.debug(f"Could not compute TRT from DICOM ({direction}): {e}")
        return None
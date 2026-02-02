"""
reorient command - Reorient images to standard orientation.

Uses FSL fslswapdim to reorient NIfTI images to the specified
orientation code (e.g., LPI, RAS).
"""

import subprocess
from pathlib import Path
from typing import List, Optional

import nibabel as nib
import numpy as np

from dcm2bids.core import Session, setup_logging, find_files


def run_reorient(
    studydir: Path,
    subject: str,
    session: str,
    orientation: str = "LPI",
    modality: str = "all",
    force: bool = False,
    verbose: bool = False
) -> None:
    """
    Reorient images to standard orientation.
    
    Parameters
    ----------
    studydir : Path
        Path to BIDS study directory
    subject : str
        Subject ID (without sub- prefix)
    session : str
        Session ID (without ses- prefix)
    orientation : str
        Target orientation code (default: FreeSurfer LPI )
    modality : str
        Which modality to process ('all', 'anat', 'func', 'fmap', 'dwi')
    force : bool
        Force reprocess already oriented files
    verbose : bool
        Enable verbose output
    """
    sess = Session(studydir, subject, session)
    log_file = sess.paths["logs"] / "reorient.log"
    logger = setup_logging("reorient", log_file, verbose)
    
    rawdata = sess.paths["rawdata"]
    
    if not rawdata.exists():
        logger.warning(f"rawdata directory not found: {rawdata}")
        return
    
    logger.info(f"Reorienting images for sub-{subject}_ses-{session}")
    logger.info(f"Target orientation: {orientation}")
    
    # which dirs to process
    if modality == "all":
        modalities = ["anat", "func", "fmap", "dwi"]
    else:
        modalities = [modality]
    

    total_processed = 0
    for mod in modalities:
        mod_dir = rawdata / mod
        if not mod_dir.exists():
            logger.debug(f"Modality directory not found: {mod}")
            continue
        
        nifti_files = find_files(mod_dir, "*.nii.gz")
        if not nifti_files:
            logger.debug(f"No NIfTI files in {mod}")
            continue
        
        logger.info(f"Processing {len(nifti_files)} files in {mod}/")
        
        for nii_file in nifti_files:
            success = _reorient_file(
                nii_file=nii_file,
                orientation=orientation,
                sess=sess,
                force=force,
                logger=logger
            )
            if success:
                total_processed += 1
    
    logger.info(f"Reorientation complete. Processed {total_processed} files.")


def _reorient_file(
    nii_file: Path,
    orientation: str,
    sess: Session,
    force: bool,
    logger
) -> bool:
    """
    Reorient a single NIfTI file.
    
    Returns True if file was processed, False if skipped.
    """
    # check current orientation
    current_orient = _get_orientation(nii_file)
    
    if current_orient == orientation.upper() and not force:
        logger.debug(f"Already {orientation}: {nii_file.name}")
        return False
    
    logger.info(f"Reorienting {nii_file.name}: {current_orient} -> {orientation}")
    
    try:
        _reorient_img(
            img_path=str(nii_file),
            code=orientation,
            out=str(nii_file)
        )
        return True
    except Exception as e:
        logger.error(f"Failed to reorient {nii_file.name}: {e}")
        return False


def _get_orientation(nii_path: Path) -> str:
    """
    Get the current orientation of a NIfTI file.
    
    Returns orientation code like 'RAS', 'LPI', etc.
    """
    img = nib.load(nii_path)
    orient = nib.orientations.aff2axcodes(img.affine)
    return "".join(orient)


def _reorient_img(
    img_path: str,
    code: str = "RAS",
    out: Optional[str] = None,
    qform: str = "orig"
) -> None:
    """
    Reorient an image to the specified orientation.
    
    Parameters
    ----------
    img_path : str
        Input NIfTI file path
    code : str
        Target orientation code (e.g., 'LPI', 'RAS')
        Use 'NB' for nibabel-based reorientation
    out : str, optional
        Output path (defaults to overwriting input)
    qform : str
        qform handling ('orig' to preserve, or numeric code)
    """
    if out is None:
        out = img_path

        # using either nibabel or fslswapdim
    
    if code.upper() == "NB":

        img_nib = nib.load(img_path)
        qform_code = img_nib.header.get("qform_code", 1) if qform == "orig" else int(qform)
        ras = nib.as_closest_canonical(img_nib)
        ras.header["qform_code"] = np.array([qform_code], dtype=np.int16)
        ras.to_filename(out)
        return
    

    pairs = {
        "L": "LR", "R": "RL",
        "A": "AP", "P": "PA", 
        "S": "SI", "I": "IS"
    }
    
    if len(code) != 3:
        raise ValueError(f"Invalid orientation code: {code}")
    
    orient_parts = []
    for c in code.upper():
        if c not in pairs:
            raise ValueError(f"Invalid orientation character: {c}")
        orient_parts.append(pairs[c])
    

    tmp_out = str(Path(out).with_suffix("")) + "_tmp.nii.gz"
    
    cmd = ["fslswapdim", img_path] + orient_parts + [tmp_out]
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    except subprocess.CalledProcessError:
        # tries to flip first axis if it fails
        if orient_parts[0] == "LR":
            orient_parts[0] = "RL"
        elif orient_parts[0] == "RL":
            orient_parts[0] = "LR"
        
        cmd = ["fslswapdim", img_path] + orient_parts + [tmp_out]
        subprocess.run(cmd, capture_output=True, text=True, check=True)
    
    # replace original file with tmp
    Path(tmp_out).replace(out)

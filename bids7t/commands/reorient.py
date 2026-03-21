"""
reorient command. reorients images to LPI orientation using FSL or nibabel.

for more information about this see: 
https://github.com/tknapen/tknapen.github.io/wiki/Anatomical-workflows#coordinate-systems-across-software-packages
"""

import subprocess
from pathlib import Path
from typing import Optional
import nibabel as nib
import numpy as np
from bids7t.core import Session, setup_logging, find_files


def run_reorient(studydir: Path, subject: str, session: Optional[str] = None,
                 orientation: str = "LPI", modality: str = "all",
                 force: bool = False, verbose: bool = False) -> None:
    sess = Session(studydir, subject, session)
    log_file = sess.paths["logs"] / "reorient.log"
    logger = setup_logging("reorient", log_file, verbose)
    rawdata = sess.paths["rawdata"]
    if not rawdata.exists():
        logger.warning(f"rawdata not found: {rawdata}"); return
    session_label = f"_ses-{session}" if session else ""
    logger.info(f"Reorienting for sub-{subject}{session_label}, target: {orientation}")
    mods = ["anat", "func", "fmap", "dwi"] if modality == "all" else [modality]
    total = 0
    for mod in mods:
        mod_dir = rawdata / mod
        if not mod_dir.exists():
            continue
        niftis = find_files(mod_dir, "*.nii.gz")
        for nii in niftis:
            current = _get_orientation(nii)
            if current == orientation.upper() and not force:
                continue
            logger.info(f"Reorienting {nii.name}: {current} -> {orientation}")
            try:
                _reorient(str(nii), orientation, str(nii))
                total += 1
            except Exception as e:
                logger.error(f"Failed: {nii.name}: {e}")
    logger.info(f"Reorientation complete. Processed {total} files.")


def _get_orientation(path):
    img = nib.load(path)
    return "".join(nib.orientations.aff2axcodes(img.affine))


def _reorient(img_path, code, out):
    if code.upper() == "NB":
        img = nib.load(img_path)
        ras = nib.as_closest_canonical(img)
        ras.to_filename(out)
        return
    pairs = {"L":"LR","R":"RL","A":"AP","P":"PA","S":"SI","I":"IS"}
    orient_parts = [pairs[c] for c in code.upper()]
    tmp = out.replace(".nii.gz", "_tmp.nii.gz")
    cmd = ["fslswapdim", img_path] + orient_parts + [tmp]
    try:
        subprocess.run(cmd, capture_output=True, text=True, check=True)
    except subprocess.CalledProcessError:
        if orient_parts[0] == "LR": orient_parts[0] = "RL"
        elif orient_parts[0] == "RL": orient_parts[0] = "LR"
        cmd = ["fslswapdim", img_path] + orient_parts + [tmp]
        subprocess.run(cmd, capture_output=True, text=True, check=True)
    Path(tmp).replace(out)
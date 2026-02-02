"""
slicetime command - Slice timing correction for functional data.

Uses FSL slicetimer to correct for slice acquisition timing
differences in functional images.
"""

import subprocess
from pathlib import Path
from typing import List

import nibabel as nib

from dcm2bids.core import Session, setup_logging, find_files


def run_slicetime(
    studydir: Path,
    subject: str,
    session: str,
    slice_order: str = "down",
    slice_direction: int = 3,
    force: bool = False,
    verbose: bool = False
) -> None:
    """
    Perform slice timing correction on functional data.
    
    Parameters
    ----------
    studydir : Path
        Path to BIDS study directory
    subject : str
        Subject ID (without sub- prefix)
    session : str
        Session ID (without ses- prefix)
    slice_order : str
        Slice acquisition order ('up', 'down', 'odd', 'even')
    slice_direction : int
        Slice direction axis (1=x, 2=y, 3=z)
    force : bool
        Force reprocess files with SliceTiming already set
    verbose : bool
        Enable verbose output
    """
    sess = Session(studydir, subject, session)
    log_file = sess.paths["logs"] / "slicetime.log"
    logger = setup_logging("slicetime", log_file, verbose)
    
    func_dir = sess.paths["func"]
    
    if not func_dir.exists():
        logger.warning(f"func directory not found: {func_dir}")
        return
    
    logger.info(f"Slice timing correction for sub-{subject}_ses-{session}")
    logger.info(f"Slice order: {slice_order}, Direction: axis {slice_direction}")
    
    # find func files
    bold_files = find_files(func_dir, "*_bold.nii.gz")
    
    if not bold_files:
        logger.warning("No BOLD files found")
        return
    
    logger.info(f"Found {len(bold_files)} BOLD files")
    
    # process each file
    processed = 0
    for bold_file in bold_files:
        success = _correct_slicetiming(
            bold_file=bold_file,
            sess=sess,
            slice_order=slice_order,
            slice_direction=slice_direction,
            force=force,
            logger=logger
        )
        if success:
            processed += 1
    
    logger.info(f"Slice timing correction complete. Processed {processed} files.")


def _correct_slicetiming(
    bold_file: Path,
    sess: Session,
    slice_order: str,
    slice_direction: int,
    force: bool,
    logger
) -> bool:
    """
    Apply slice timing correction to a single BOLD file.
    
    Returns True if processed, False if skipped.
    """
    json_file = bold_file.with_suffix("").with_suffix(".json")
    
    if not json_file.exists():
        logger.warning(f"No JSON sidecar for {bold_file.name}, skipping")
        return False
    
    meta = sess.get_json(bold_file)
    
    # check TR exist
    if "RepetitionTime" not in meta:
        logger.warning(f"No RepetitionTime in {json_file.name}, skipping")
        return False
    
    tr = meta["RepetitionTime"]
    
    # check if already processed
    if "SliceTiming" in meta and not force:
        logger.debug(f"SliceTiming already set for {bold_file.name}")
        return False
    
    logger.info(f"Processing {bold_file.name} (TR={tr}s)")
    
    # temp output
    tmp_out = bold_file.with_name(bold_file.stem + "_st_tmp.nii.gz")
    
    # slicetimer command
    cmd = [
        "slicetimer",
        "-i", str(bold_file),
        "-o", str(tmp_out),
        "-r", str(tr),
        "-d", str(slice_direction)
    ]
    
    # slice order flag
    if slice_order == "down":
        cmd.append("--down")
    elif slice_order == "odd":
        cmd.append("--odd")
    # 'up' and 'even' are default behaviors
    
    logger.debug(f"Running: {' '.join(cmd)}")
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    except subprocess.CalledProcessError as e:
        logger.error(f"slicetimer failed for {bold_file.name}: {e.stderr}")
        if tmp_out.exists():
            tmp_out.unlink()
        return False
    
    # replace original with new
    sess.make_writable(bold_file)
    tmp_out.replace(bold_file)
    
    # updates JSON with SliceTiming if not present
    if "SliceTiming" not in meta:
        n_slices = nib.load(bold_file).shape[2]
        
        # slice timing based on order
        if slice_order == "up":
            slice_times = [(i * tr) / n_slices for i in range(n_slices)]
        elif slice_order == "down":
            slice_times = [((n_slices - 1 - i) * tr) / n_slices for i in range(n_slices)]
        elif slice_order == "odd":
            # odd slices first, then even
            odd = list(range(0, n_slices, 2))
            even = list(range(1, n_slices, 2))
            order = odd + even
            slice_times = [0.0] * n_slices
            for t_idx, s_idx in enumerate(order):
                slice_times[s_idx] = (t_idx * tr) / n_slices
        elif slice_order == "even":
            # even slices first, then odd
            even = list(range(1, n_slices, 2))
            odd = list(range(0, n_slices, 2))
            order = even + odd
            slice_times = [0.0] * n_slices
            for t_idx, s_idx in enumerate(order):
                slice_times[s_idx] = (t_idx * tr) / n_slices
        else:
            slice_times = [(i * tr) / n_slices for i in range(n_slices)]
        
        sess.make_writable(json_file)
        meta["SliceTiming"] = slice_times
        sess.write_json(bold_file, meta)
        sess.make_readonly(json_file)
        
        logger.debug(f"Added SliceTiming field ({n_slices} slices)")
    
    sess.make_readonly(bold_file)
    
    return True

"""slicetime - Slice timing correction using FSL slicetimer."""

import subprocess
from pathlib import Path
from typing import Optional
import nibabel as nib
from bids7t.core import Session, setup_logging, find_files


def run_slicetime(studydir: Path, subject: str, session: Optional[str] = None,
                  slice_order: str = "down", slice_direction: int = 3,
                  force: bool = False, verbose: bool = False) -> None:
    sess = Session(studydir, subject, session)
    log_file = sess.paths["logs"] / "slicetime.log"
    logger = setup_logging("slicetime", log_file, verbose)
    func_dir = sess.paths["func"]
    if not func_dir.exists():
        logger.warning("func directory not found"); return
    session_label = f"_ses-{session}" if session else ""
    logger.info(f"Slice timing for sub-{subject}{session_label}")
    bolds = find_files(func_dir, "*_bold.nii.gz")
    if not bolds:
        logger.warning("No BOLD files found"); return
    processed = 0
    for bold in bolds:
        meta = sess.get_json(bold)
        if "RepetitionTime" not in meta:
            continue
        tr = meta["RepetitionTime"]
        if "SliceTiming" in meta and not force:
            continue
        logger.info(f"Processing {bold.name} (TR={tr}s)")
        tmp = bold.with_name(bold.stem + "_st_tmp.nii.gz")
        cmd = ["slicetimer", "-i", str(bold), "-o", str(tmp), "-r", str(tr), "-d", str(slice_direction)]
        if slice_order == "down": cmd.append("--down")
        elif slice_order == "odd": cmd.append("--odd")
        try:
            subprocess.run(cmd, capture_output=True, text=True, check=True)
        except subprocess.CalledProcessError as e:
            logger.error(f"slicetimer failed: {e.stderr}")
            if tmp.exists(): tmp.unlink()
            continue
        sess.make_writable(bold)
        tmp.replace(bold)
        if "SliceTiming" not in meta:
            n_slices = nib.load(bold).shape[2]
            if slice_order == "up":
                st = [(i * tr) / n_slices for i in range(n_slices)]
            elif slice_order == "down":
                st = [((n_slices - 1 - i) * tr) / n_slices for i in range(n_slices)]
            else:
                st = [(i * tr) / n_slices for i in range(n_slices)]
            json_f = bold.with_suffix("").with_suffix(".json")
            sess.make_writable(json_f)
            meta["SliceTiming"] = st
            sess.write_json(bold, meta)
            sess.make_readonly(json_f)
        sess.make_readonly(bold)
        processed += 1
    logger.info(f"Processed {processed} files.")
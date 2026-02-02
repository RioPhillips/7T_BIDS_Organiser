"""
fixanat command - Fix anatomical files (MP2RAGE processing).

This command:
- Splits combined inv-1and2 files into separate inv1/inv2 files
- Computes magnitude and phase from real/imag pairs
- Reshapes UNIT1 (T1w) files if they have dummy dimensions
- Updates scans.tsv accordingly
"""

import re
import json
from pathlib import Path
from typing import List, Set

import numpy as np
import nibabel as nib

from dcm2bids.core import Session, setup_logging, check_outputs_exist


def run_fixanat(
    studydir: Path,
    subject: str,
    session: str,
    force: bool = False,
    verbose: bool = False
) -> None:
    """
    Fix anatomical files (MP2RAGE processing).
    
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
    """
    sess = Session(studydir, subject, session)
    log_file = sess.paths["logs"] / "fixanat.log"
    logger = setup_logging("fixanat", log_file, verbose)
    
    anat_dir = sess.paths["anat"]
    
    if not anat_dir.exists():
        logger.warning(f"Anat directory not found: {anat_dir}")
        return
    
    logger.info(f"Fixing anatomical files for sub-{subject}_ses-{session}")
    
    # finds all existing run numbers from filenames
    run_numbers = _find_run_numbers(anat_dir, sess.subses_prefix)
    
    if not run_numbers:
        logger.warning("No run tags found in anat filenames, assuming run=1")
        run_numbers = {1}
    
    logger.info(f"Found anatomical runs: {sorted(run_numbers)}")
    
    for run in sorted(run_numbers):
        # check if the outputs already exist
        expected_outputs = _get_expected_outputs(anat_dir, sess.subses_prefix, run)
        
        if expected_outputs:
            should_run, existing = check_outputs_exist(expected_outputs, logger, force)
            if not should_run:
                logger.info(f"Skipping run-{run} (outputs exist)")
                continue
        
        logger.info(f"Processing run-{run}")
        
        # splits inv-1and2 files --> inv1 and inv2 separate
        _split_inv_files(anat_dir, sess, logger, run)
        
        # calculates magnitude and phase from real/imag
        _compute_mag_phase(anat_dir, sess, logger, run)
        
        # removes scanner dummy-dimension from UNIT1 (T1w) 
        _reshape_unit1(anat_dir, sess, logger, run)
    

    _remove_combined_files(anat_dir, sess, logger)
    _remove_temp_files(anat_dir, sess, logger)
    
    # syncs scans.tsv with actual files on disk
    logger.info("Synchronizing scans.tsv with actual files...")
    sync_result = sess.sync_scans_tsv(remove_missing=True, add_new=False)
    if sync_result["removed"]:
        logger.info(f"  Removed {len(sync_result['removed'])} orphaned entries from scans.tsv")
    
    logger.info("Anatomical fixes complete")


def _find_run_numbers(anat_dir: Path, prefix: str) -> Set[int]:
    """Find run numbers from filenames."""
    run_numbers = set()
    for f in anat_dir.glob(f"{prefix}_*MP2RAGE.nii.gz"):
        m = re.search(r"run-(\d+)", f.name)
        if m:
            run_numbers.add(int(m.group(1)))
    return run_numbers


def _get_expected_outputs(anat_dir: Path, prefix: str, run: int) -> List[Path]:
    """Get list of expected output files for a run."""
    outputs = []
    for inv in [1, 2]:
        for part in ["mag", "phase"]:
            outputs.append(
                anat_dir / f"{prefix}_run-{run}_inv-{inv}_part-{part}_MP2RAGE.nii.gz"
            )
    return outputs


def _split_inv_files(anat_dir: Path, sess: Session, logger, run: int) -> None:
    """
    Split combined inv-1and2 files into separate inv1/inv2 files.
    
    Handles real, imag, and main MP2RAGE variants.
    Updates scans.tsv to replace combined entries with split entries.
    """
    prefix = sess.subses_prefix
    
    variants = [
        ("real", f"{prefix}_run-{run}_inv-1and2_part-real_MP2RAGE.nii.gz"),
        ("imag", f"{prefix}_run-{run}_inv-1and2_part-imag_MP2RAGE.nii.gz"),
        (None, f"{prefix}_run-{run}_inv-1and2_MP2RAGE.nii.gz"),  # main image
    ]
    
    for part_bids, fname in variants:
        nii_path = anat_dir / fname
        json_path = nii_path.with_suffix("").with_suffix(".json")
        
        if not nii_path.exists():
            logger.debug(f"No combined file for run-{run}, variant={part_bids or 'main'}")
            continue
        
        logger.info(f"Splitting: {nii_path.name}")
        
        nii = nib.load(nii_path)
        data = nii.get_fdata()
        
        if not json_path.exists():
            logger.warning(f"Missing JSON for {nii_path.name}")
            json_dict = {}
        else:
            with open(json_path) as f:
                json_dict = json.load(f)
        
        # check shape
        if data.ndim != 4 or data.shape[-1] != 2:
            logger.warning(f"Unexpected shape for {nii_path.name}: {data.shape}")
            continue
        
        # tracks created files for bids metadata jsons
        new_rel_paths = []
        
        # split inv1-and2 --> inv1 and inv2
        for i, inv in enumerate([1, 2]):
            if part_bids:
                # these are not bids-tracked
                # as they are not kept after
                out_name = f"{prefix}_run-{run}_inv-{inv}_part-{part_bids}_temp_MP2RAGE"
            else:
                # the main mp2rage is tracked
                out_name = f"{prefix}_run-{run}_inv-{inv}_MP2RAGE"
            
            out_nii = anat_dir / f"{out_name}.nii.gz"
            out_json = anat_dir / f"{out_name}.json"
            
            # saved as nii
            img = nib.Nifti1Image(data[..., i], nii.affine, nii.header)
            nib.save(img, out_nii)
            
            # jsons updated
            out_meta = dict(json_dict)
            out_meta["dcmmeta_shape"] = list(data[..., i].shape)
            if part_bids:
                out_meta["part"] = part_bids
            elif "part" in out_meta:
                out_meta.pop("part")
            
            with open(out_json, "w") as f:
                json.dump(out_meta, f, indent=2)
            
            logger.info(f"  Created: {out_nii.name}")
            
            # bids-track non-temp files
            if not part_bids:
                new_rel_paths.append(f"anat/{out_nii.name}")
        
        # update with newly created files
        if new_rel_paths:
            old_rel_path = f"anat/{fname}"
            if sess.replace_in_scans_tsv(old_rel_path, new_rel_paths):
                logger.debug(f"  Updated scans.tsv: {old_rel_path} -> {new_rel_paths}")


def _compute_mag_phase(anat_dir: Path, sess: Session, logger, run: int) -> None:
    """
    Compute magnitude and phase from real/imag pairs.
    
    Adds new mag/phase entries to scans.tsv, inheriting metadata from inv files.
    """
    prefix = sess.subses_prefix
    
    for inv in [1, 2]:
        real_file = anat_dir / f"{prefix}_run-{run}_inv-{inv}_part-real_temp_MP2RAGE.nii.gz"
        imag_file = anat_dir / f"{prefix}_run-{run}_inv-{inv}_part-imag_temp_MP2RAGE.nii.gz"
        
        if not real_file.exists() or not imag_file.exists():
            logger.debug(f"Missing real/imag pair for inv-{inv}, skipping mag/phase")
            continue
        
        logger.info(f"Computing mag/phase for inv-{inv}")
        
        nii_real = nib.load(real_file)
        nii_imag = nib.load(imag_file)
        real_data = nii_real.get_fdata()
        imag_data = nii_imag.get_fdata()
        
        if real_data.shape != imag_data.shape:
            logger.error(f"Shape mismatch: real={real_data.shape}, imag={imag_data.shape}")
            continue
        
        # computes magnitude and phase
        mag = np.sqrt(real_data**2 + imag_data**2)
        phase = np.arctan2(imag_data, real_data)
        
        # JSON for metadata
        real_json = real_file.with_suffix("").with_suffix(".json")
        if real_json.exists():
            with open(real_json) as f:
                base_meta = json.load(f)
        else:
            base_meta = {}
        
        # copy metadata from the corresponding inv file in scans.tsv 
        inv_rel_path = f"anat/{prefix}_run-{run}_inv-{inv}_MP2RAGE.nii.gz"
        inv_entry = sess.get_scans_entry(inv_rel_path)
        inherited_metadata = {}
        if inv_entry:
            # everything except filename
            inherited_metadata = {k: v for k, v in inv_entry.items() if k != "filename"}
        
        # save mag/phase
        for part, data in [("mag", mag), ("phase", phase)]:
            out_name = f"{prefix}_run-{run}_inv-{inv}_part-{part}_MP2RAGE"
            out_nii = anat_dir / f"{out_name}.nii.gz"
            out_json = anat_dir / f"{out_name}.json"
            
            img = nib.Nifti1Image(data, nii_real.affine, nii_real.header)
            nib.save(img, out_nii)
            
            out_meta = dict(base_meta)
            out_meta["dcmmeta_shape"] = list(data.shape)
            out_meta["part"] = part
            
            with open(out_json, "w") as f:
                json.dump(out_meta, f, indent=2)
            
            logger.info(f"  Created: {out_nii.name}")
            
            # add metadata to scans.tsv
            rel_path = f"anat/{out_nii.name}"
            if inherited_metadata:
                sess.add_to_scans_tsv(rel_path, **inherited_metadata)
                logger.debug(f"  Added to scans.tsv: {rel_path}")
            else:
                sess.add_to_scans_tsv(rel_path)
                logger.debug(f"  Added to scans.tsv (no inherited metadata): {rel_path}")


def _reshape_unit1(anat_dir: Path, sess: Session, logger, run: int) -> None:
    """Reshape UNIT1 (T1w) files if they have a dummy 4D dimension."""
    prefix = sess.subses_prefix
    
    t1w_nii = anat_dir / f"{prefix}_acq-mp2rage_run-{run}_T1w.nii.gz"
    t1w_json = anat_dir / f"{prefix}_acq-mp2rage_run-{run}_T1w.json"
    
    if not t1w_nii.exists():
        logger.debug(f"No T1w file found for run-{run}")
        return
    
    nii = nib.load(t1w_nii)
    data = nii.get_fdata()
    
    # checks if needs reshaping (4D with any dimension = 1)
    if data.ndim == 4 and 1 in data.shape:
        logger.info(f"Reshaping T1w from {data.shape} to 3D")
        
        if data.shape[0] == 1:
            new_data = data[0, :, :, :]
        elif data.shape[1] == 1:
            new_data = data[:, 0, :, :]
        elif data.shape[2] == 1:
            new_data = data[:, :, 0, :]
        elif data.shape[3] == 1:
            new_data = data[:, :, :, 0]
        else:
            # shouldn't happen given the check above, but just in case
            logger.warning(f"Unexpected shape {data.shape}, cannot determine which dimension to squeeze")
            return
        
        logger.info(f"  New shape: {new_data.shape}")
        
        new_nii = nib.Nifti1Image(new_data, nii.affine)
        new_nii.header.set_xyzt_units(*nii.header.get_xyzt_units())
        
        # to temp, then replace
        temp_file = anat_dir / ".t1w_tmp.nii.gz"
        nib.save(new_nii, temp_file)
        temp_file.replace(t1w_nii)
        
        # JSON update
        if t1w_json.exists():
            sess.make_writable(t1w_json)
            meta = sess.get_json(t1w_nii)
            meta["dcmmeta_shape"] = list(new_data.shape)
            sess.write_json(t1w_nii, meta)
            sess.make_readonly(t1w_json)
        
        logger.info(f"  Reshaped: {t1w_nii.name}")
    else:
        logger.debug(f"T1w run-{run} shape is {data.shape}, no dummy dimension to remove")


def _remove_combined_files(anat_dir: Path, sess: Session, logger) -> None:
    """Remove combined inv-1and2 files."""
    prefix = sess.subses_prefix
    
    for f in anat_dir.glob(f"{prefix}_*inv-1and2_*"):
        try:
            f.unlink()
            logger.info(f"Removed combined: {f.name}")
        except Exception as e:
            logger.warning(f"Failed to remove {f.name}: {e}")


def _remove_temp_files(anat_dir: Path, sess: Session, logger) -> None:
    """Remove temporary real/imag intermediate files."""
    prefix = sess.subses_prefix
    
    for f in anat_dir.glob(f"{prefix}_*_temp_MP2RAGE*"):
        try:
            f.unlink()
            logger.debug(f"Removed temp: {f.name}")
        except Exception as e:
            logger.warning(f"Failed to remove temp {f.name}: {e}")
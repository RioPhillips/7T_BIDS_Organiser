"""
fixfmap command - Fix fieldmap files.

This command:
- Renames B0 shimmed fieldmap files to BIDS convention
- Renames GRE fieldmap/magnitude files to BIDS convention (legacy)
- Adds Units field to GRE/B0 fieldmap JSON
- Adds IntendedFor field to fieldmap JSON files
"""

import re
from pathlib import Path
from typing import Set, List, Optional

from dcm2bids.core import Session, setup_logging, check_outputs_exist


def run_fixfmap(
    studydir: Path,
    subject: str,
    session: str,
    force: bool = False,
    verbose: bool = False
) -> None:
    """
    Fix fieldmap files.
    
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
    log_file = sess.paths["logs"] / "fixfmap.log"
    logger = setup_logging("fixfmap", log_file, verbose)
    
    fmap_dir = sess.paths["fmap"]
    func_dir = sess.paths["func"]
    
    if not fmap_dir.exists():
        logger.info(f"fmap directory not found: {fmap_dir}")
        logger.info("No fieldmap fixes needed.")
        return
    
    logger.info(f"Fixing fieldmap files for sub-{subject}_ses-{session}")
    
    prefix = sess.subses_prefix

    # finds run numbers and checks for existing runs    
    run_numbers = _find_run_numbers(fmap_dir, prefix)
    
    if not run_numbers:
        logger.info("No run tags found in fmap filenames")
        fmap_files = list(fmap_dir.glob("*.nii.gz"))
        if not fmap_files:
            logger.info("No NIfTI files in fmap directory, nothing to fix")
            return
        logger.info("Assuming run=1 for files without run tag")
        run_numbers = {1}
    
    logger.info(f"Found fmap runs: {sorted(run_numbers)}")
    
    for run in sorted(run_numbers):
        # B0 shimmed fieldmaps (7079)
        _fix_b0_maps(fmap_dir, sess, logger, run, force)
        
        # GRE fieldmap/magnitude files (7T049)
        _rename_gre_files(fmap_dir, sess, logger, run, force)
        
        # adds "Units" to fieldmap JSONs 
        # check with clinical if these are right units
        _add_units_to_fieldmaps(fmap_dir, sess, logger, run)
        
        # adds intendedfor BIDS metadata pointing at all func files
        if func_dir.exists():
            _add_intended_for(fmap_dir, func_dir, sess, logger, run)
    
    # handle files without run numbers
    _fix_b1_maps_no_run(fmap_dir, sess, logger, force)
    
    logger.info("Fieldmap fixes complete")


def _find_run_numbers(fmap_dir: Path, prefix: str) -> Set[int]:
    """Find run numbers from filenames."""
    run_numbers = set()
    for f in fmap_dir.glob(f"{prefix}_*.nii.gz"):
        m = re.search(r"run-(\d+)", f.name)
        if m:
            run_numbers.add(int(m.group(1)))
    return run_numbers


def _fix_b0_maps(
    fmap_dir: Path,
    sess: Session,
    logger,
    run: int,
    force: bool
) -> None:
    """
    Fix B0 shimmed fieldmap files to BIDS convention.
    
    Heudiconv outputs (with 7T079 pilot heuristic):
      - {prefix}_run-{run}_b0-combined1.nii.gz -> magnitude
      - {prefix}_run-{run}_b0-combined2.nii.gz -> fieldmap
    
    BIDS expects:
      - {prefix}_acq-b0_run-{run}_magnitude.nii.gz
      - {prefix}_acq-b0_run-{run}_fieldmap.nii.gz
    """
    prefix = sess.subses_prefix
    
    # source pattern -> target pattern
    mappings = [
        (f"{prefix}_run-{run}_b0-combined1", f"{prefix}_acq-b0_run-{run}_magnitude"),
        (f"{prefix}_run-{run}_b0-combined2", f"{prefix}_acq-b0_run-{run}_fieldmap"),
    ]
    
    found_any = False
    for src_base, dst_base in mappings:
        src_nii = fmap_dir / f"{src_base}.nii.gz"
        src_json = fmap_dir / f"{src_base}.json"
        dst_nii = fmap_dir / f"{dst_base}.nii.gz"
        dst_json = fmap_dir / f"{dst_base}.json"
        
        if not src_nii.exists():
            logger.debug(f"B0 source not found: {src_nii.name}")
            continue
        
        found_any = True
        
        if dst_nii.exists() and not force:
            logger.debug(f"B0 target already exists: {dst_nii.name}, skipping")
            continue
        
        # rename json and nifty and update 
        sess.rename_file(src_nii, dst_nii)
        logger.info(f"Renamed: {src_nii.name} -> {dst_nii.name}")
        
        if src_json.exists():
            sess.rename_file(src_json, dst_json)
            logger.debug(f"Renamed: {src_json.name} -> {dst_json.name}")
        
        # updates scans.tsv
        old_rel = f"fmap/{src_nii.name}"
        new_rel = f"fmap/{dst_nii.name}"
        if sess.rename_in_scans_tsv(old_rel, new_rel):
            logger.debug(f"Updated scans.tsv: {old_rel} -> {new_rel}")
    
    if not found_any:
        logger.debug(f"No B0 shimmed fieldmap files found for run-{run}")


def _fix_b1_maps_no_run(
    fmap_dir: Path,
    sess: Session,
    logger,
    force: bool
) -> None:
    """
    Handle B1 map files that don't have run numbers
    """
    prefix = sess.subses_prefix
    
    for b1_file in fmap_dir.glob(f"{prefix}_b1-combined.nii.gz"):
        target_nii = fmap_dir / f"{prefix}_acq-dream_TB1map.nii.gz"
        target_json = fmap_dir / f"{prefix}_acq-dream_TB1map.json"
        
        if target_nii.exists() and not force:
            logger.debug(f"TB1map already exists: {target_nii.name}, skipping")
            continue
        
        b1_json = b1_file.with_suffix("").with_suffix(".json")
        
        sess.rename_file(b1_file, target_nii)
        logger.info(f"Renamed (legacy): {b1_file.name} -> {target_nii.name}")
        
        if b1_json.exists():
            sess.rename_file(b1_json, target_json)
            logger.debug(f"Renamed: {b1_json.name} -> {target_json.name}")
        
        old_rel = f"fmap/{b1_file.name}"
        new_rel = f"fmap/{target_nii.name}"
        if sess.rename_in_scans_tsv(old_rel, new_rel):
            logger.debug(f"Updated scans.tsv: {old_rel} -> {new_rel}")


def _rename_gre_files(
    fmap_dir: Path, 
    sess: Session, 
    logger, 
    run: int,
    force: bool
) -> None:
    """
    Rename GRE fieldmap/magnitude files to BIDS convention.
    
    Heudiconv outputs:
      - {prefix}_acq-gre_dir-AP_run-{run}_epi1.nii.gz -> fieldmap
      - {prefix}_acq-gre_dir-AP_run-{run}_epi2.nii.gz -> magnitude
    
    BIDS expects:
      - {prefix}_acq-gre_run-{run}_fieldmap.nii.gz
      - {prefix}_acq-gre_run-{run}_magnitude.nii.gz
    """
    prefix = sess.subses_prefix
    
    # source -> target mapping
    gre_base = fmap_dir / f"{prefix}_acq-gre_dir-AP_run-{run}_epi"
    
    mappings = [
        (f"{gre_base}1", fmap_dir / f"{prefix}_acq-gre_run-{run}_fieldmap"),
        (f"{gre_base}2", fmap_dir / f"{prefix}_acq-gre_run-{run}_magnitude"),
    ]
    
    found_any = False
    for src_prefix, dst_prefix in mappings:
        src_nii = Path(f"{src_prefix}.nii.gz")
        dst_nii = Path(f"{dst_prefix}.nii.gz")
        src_json = Path(f"{src_prefix}.json")
        dst_json = Path(f"{dst_prefix}.json")
        
        if not src_nii.exists():
            continue  # Silent skip
        
        found_any = True
        
        if dst_nii.exists() and not force:
            logger.debug(f"GRE target exists, skipping: {dst_nii.name}")
            continue
        
        # rename niift and json
        sess.rename_file(src_nii, dst_nii)
        logger.info(f"Renamed: {src_nii.name} -> {dst_nii.name}")
        
        if src_json.exists():
            sess.rename_file(src_json, dst_json)
            logger.debug(f"Renamed: {src_json.name} -> {dst_json.name}")
        
        # updates scans.tsv
        old_rel_path = f"fmap/{src_nii.name}"
        new_rel_path = f"fmap/{dst_nii.name}"
        if sess.rename_in_scans_tsv(old_rel_path, new_rel_path):
            logger.debug(f"Updated scans.tsv: {old_rel_path} -> {new_rel_path}")
    
    if found_any:
        logger.debug(f"Processed GRE fieldmap files for run-{run}")


def _add_units_to_fieldmaps(fmap_dir: Path, sess: Session, logger, run: int) -> None:
    """
    Add Units field to fieldmap JSONs (GRE and B0).
    
    BIDS requires Units field for fieldmaps. Common values:
      - "rad/s" for phase difference maps
      - "Hz" for frequency maps
      - "T" for Tesla
    """
    prefix = sess.subses_prefix
    
    # files that need Units
    fieldmap_patterns = [
        f"{prefix}_acq-gre_run-{run}_fieldmap",
        f"{prefix}_acq-b0_run-{run}_fieldmap",
    ]
    
    for pattern in fieldmap_patterns:
        fieldmap_json = fmap_dir / f"{pattern}.json"
        fieldmap_nii = fmap_dir / f"{pattern}.nii.gz"
        
        if not fieldmap_json.exists():
            continue  
        
        meta = sess.get_json(fieldmap_nii)
        
        if meta.get("Units") == "rad/s":
            logger.debug(f"Units already set for {fieldmap_json.name}")
            continue
        
        sess.make_writable(fieldmap_json)
        meta["Units"] = "rad/s"
        sess.write_json(fieldmap_nii, meta)
        sess.make_readonly(fieldmap_json)
        
        logger.info(f"Added Units=rad/s to {fieldmap_json.name}")


def _add_intended_for(
    fmap_dir: Path, 
    func_dir: Path, 
    sess: Session, 
    logger, 
    run: int
) -> None:
    """
    Add IntendedFor field to fieldmap JSON files.
    
    IntendedFor points to all functional BOLD files that this fieldmap
    is intended to correct.
    """
    prefix = sess.subses_prefix
    
    # func runs
    intended_for = []
    for func_file in sorted(func_dir.glob(f"{prefix}_task-*_bold.nii.gz")):
        rel_path = func_file.relative_to(sess.paths["rawdata_subject"])
        intended_for.append(str(rel_path))
    
    if not intended_for:
        logger.debug("No functional runs found for IntendedFor")
        return
    
    logger.info(f"Adding IntendedFor with {len(intended_for)} functional runs")
    
    # files that need IntendedFor
    fieldmap_patterns = [
        # B0 shimmed 
        f"{prefix}_acq-b0_run-{run}_fieldmap",
        # GRE fieldmaps
        f"{prefix}_acq-gre_run-{run}_fieldmap",
        # SE-EPI fieldmaps
        f"{prefix}_acq-se_dir-AP_run-{run}_epi",
        f"{prefix}_acq-se_dir-PA_run-{run}_epi",
    ]
    
    found_any = False
    for pattern in fieldmap_patterns:
        fmap_nii = fmap_dir / f"{pattern}.nii.gz"
        fmap_json = fmap_dir / f"{pattern}.json"
        
        if not fmap_json.exists():
            continue  
        
        found_any = True
        meta = sess.get_json(fmap_nii)
        
        if meta.get("IntendedFor") == intended_for:
            logger.debug(f"IntendedFor already set for {fmap_json.name}")
            continue
        
        sess.make_writable(fmap_json)
        meta["IntendedFor"] = intended_for
        sess.write_json(fmap_nii, meta)
        sess.make_readonly(fmap_json)
        
        logger.info(f"Updated IntendedFor in {fmap_json.name}")
    
    if not found_any:
        logger.debug(f"No fieldmap JSONs found for IntendedFor (run-{run})")
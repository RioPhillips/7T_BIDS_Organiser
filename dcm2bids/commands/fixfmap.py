"""
fixfmap command - Fix fieldmap files.

This command:
- Renames GRE fieldmap/magnitude files to BIDS convention
- Adds Units field to GRE fieldmap JSON
- Adds IntendedFor field to SE-EPI JSON files
"""

import re
from pathlib import Path
from typing import Set, List

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
        logger.warning(f"fmap directory not found: {fmap_dir}")
        return
    
    logger.info(f"Fixing fieldmap files for sub-{subject}_ses-{session}")
    
    prefix = sess.subses_prefix
    
    # find all existing run numbers
    run_numbers = _find_run_numbers(fmap_dir, prefix)
    
    if not run_numbers:
        logger.warning("No run tags found in fmap filenames, assuming run=1")
        run_numbers = {1}
    
    logger.info(f"Found fmap runs: {sorted(run_numbers)}")
    
    for run in sorted(run_numbers):
        # rename GRE fieldmap/magnitude files
        _rename_gre_files(fmap_dir, sess, logger, run, force)
        
        # adds "Units" to GRE fmap JSON
        _add_units_to_gre(fmap_dir, sess, logger, run)
        
        # adds "IntendedFor" to SE-EPI JSONs
        if func_dir.exists():
            _add_intended_for(fmap_dir, func_dir, sess, logger, run)
    
    logger.info("Fieldmap fixes complete")


def _find_run_numbers(fmap_dir: Path, prefix: str) -> Set[int]:
    """Find run numbers from filenames."""
    run_numbers = set()
    for f in fmap_dir.glob(f"{prefix}_*.nii.gz"):
        m = re.search(r"run-(\d+)", f.name)
        if m:
            run_numbers.add(int(m.group(1)))
    return run_numbers


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
      
    Also updates scans.tsv to reflect the new filenames.
    """
    prefix = sess.subses_prefix
    
    # source -> target mapping
    gre_base = fmap_dir / f"{prefix}_acq-gre_dir-AP_run-{run}_epi"
    
    mappings = [
        (f"{gre_base}1", fmap_dir / f"{prefix}_acq-gre_run-{run}_fieldmap"),
        (f"{gre_base}2", fmap_dir / f"{prefix}_acq-gre_run-{run}_magnitude"),
    ]
    
    for src_prefix, dst_prefix in mappings:
        src_nii = Path(f"{src_prefix}.nii.gz")
        dst_nii = Path(f"{dst_prefix}.nii.gz")
        src_json = Path(f"{src_prefix}.json")
        dst_json = Path(f"{dst_prefix}.json")
        
        if not src_nii.exists():
            logger.debug(f"Source not found: {src_nii.name}")
            continue
        
        if dst_nii.exists() and not force:
            logger.debug(f"Target exists, skipping: {dst_nii.name}")
            continue
        
        # renames niifty file
        sess.rename_file(src_nii, dst_nii)
        logger.info(f"Renamed: {src_nii.name} -> {dst_nii.name}")
        
        # renames the JSON file
        if src_json.exists():
            sess.rename_file(src_json, dst_json)
            logger.debug(f"Renamed: {src_json.name} -> {dst_json.name}")
        
        # metadata update in scans.tsv
        old_rel_path = f"fmap/{src_nii.name}"
        new_rel_path = f"fmap/{dst_nii.name}"
        if sess.rename_in_scans_tsv(old_rel_path, new_rel_path):
            logger.debug(f"Updated scans.tsv: {old_rel_path} -> {new_rel_path}")


def _add_units_to_gre(fmap_dir: Path, sess: Session, logger, run: int) -> None:
    """Add Units field to GRE fieldmap JSON."""
    prefix = sess.subses_prefix
    
    fieldmap_json = fmap_dir / f"{prefix}_acq-gre_run-{run}_fieldmap.json"
    fieldmap_nii = fmap_dir / f"{prefix}_acq-gre_run-{run}_fieldmap.nii.gz"
    
    if not fieldmap_json.exists():
        logger.debug(f"GRE fieldmap JSON not found for run-{run}")
        return
    
    meta = sess.get_json(fieldmap_nii)
    
    if meta.get("Units") == "rad/s":
        logger.debug(f"Units already set for run-{run}")
        return
    
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
    """Add IntendedFor field to SE-EPI JSON files."""
    prefix = sess.subses_prefix
    
    # collect func runs
    intended_for = []
    for func_file in sorted(func_dir.glob(f"{prefix}_task-*_bold.nii.gz")):
        # "IntendedFor" should be relative to session directory
        rel_path = func_file.relative_to(sess.paths["rawdata_subject"])
        intended_for.append(str(rel_path))
    
    if not intended_for:
        logger.debug("No functional runs found for IntendedFor")
        return
    
    logger.info(f"Adding IntendedFor with {len(intended_for)} functional runs")
    
    # updates SE-EPI JSONs
    for pe_dir in ["AP", "PA"]:
        se_nii = fmap_dir / f"{prefix}_acq-se_dir-{pe_dir}_run-{run}_epi.nii.gz"
        se_json = fmap_dir / f"{prefix}_acq-se_dir-{pe_dir}_run-{run}_epi.json"
        
        if not se_json.exists():
            logger.debug(f"SE-EPI JSON not found: {se_json.name}")
            continue
        
        meta = sess.get_json(se_nii)
        
        if meta.get("IntendedFor") == intended_for:
            logger.debug(f"IntendedFor already set for {se_json.name}")
            continue
        
        sess.make_writable(se_json)
        meta["IntendedFor"] = intended_for
        sess.write_json(se_nii, meta)
        sess.make_readonly(se_json)
        
        logger.info(f"Updated IntendedFor in {se_json.name}")
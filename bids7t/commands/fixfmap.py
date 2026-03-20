"""
fixfmap command - Fix fieldmap files.

This command:
- Cleans up dcm2niix multi-output suffixes (_e1a, _e1_ph, _e2, _r100, etc.)
  for B1 DREAM maps and renames to proper BIDS TB1map/magnitude
- Renames B0 shimmed fieldmap numbered variants to BIDS convention
- Renames GRE fieldmap/magnitude numbered variants to BIDS convention
- Adds Units field to fieldmap JSONs
- Adds IntendedFor field to fieldmap JSON files
"""

import re
from pathlib import Path
from typing import Set, Optional

from bids7t.core import Session, setup_logging


def run_fixfmap(
    studydir: Path,
    subject: str,
    session: Optional[str] = None,
    force: bool = False,
    verbose: bool = False
) -> None:
    sess = Session(studydir, subject, session)
    log_file = sess.paths["logs"] / "fixfmap.log"
    logger = setup_logging("fixfmap", log_file, verbose)
    
    fmap_dir = sess.paths["fmap"]
    func_dir = sess.paths["func"]
    
    if not fmap_dir.exists():
        logger.info(f"fmap directory not found: {fmap_dir}")
        logger.info("No fieldmap fixes needed.")
        return
    
    session_label = f"_ses-{session}" if session else ""
    logger.info(f"Fixing fieldmap files for sub-{subject}{session_label}")
    
    prefix = sess.subses_prefix
    run_numbers = _find_run_numbers(fmap_dir, prefix)
    
    if not run_numbers:
        fmap_files = list(fmap_dir.glob("*.nii.gz"))
        if not fmap_files:
            logger.info("No NIfTI files in fmap directory, nothing to fix")
            return
        logger.info("No run tags found, assuming run=1")
        run_numbers = {1}
    
    logger.info(f"Found fmap runs: {sorted(run_numbers)}")
    
    for run in sorted(run_numbers):
        # B1 DREAM maps: clean dcm2niix multi-output suffixes
        _fix_b1_suffixes(fmap_dir, sess, logger, run, force)
        
        # B0 shimmed fieldmaps: numbered variants
        _fix_b0_maps(fmap_dir, sess, logger, run, force)
        
        # GRE fieldmaps: numbered variants
        _fix_gre_maps(fmap_dir, sess, logger, run, force)
        
        # Units metadata
        _add_units_to_fieldmaps(fmap_dir, sess, logger, run)
        
        # IntendedFor
        if func_dir.exists():
            _add_intended_for(fmap_dir, func_dir, sess, logger, run)
    
    logger.info("Fieldmap fixes complete")


def _find_run_numbers(fmap_dir: Path, prefix: str) -> Set[int]:
    run_numbers = set()
    for f in fmap_dir.glob(f"{prefix}_*.nii.gz"):
        m = re.search(r"run-(\d+)", f.name)
        if m:
            run_numbers.add(int(m.group(1)))
    return run_numbers


def _fix_b1_suffixes(fmap_dir: Path, sess: Session, logger, run: int, force: bool) -> None:
    """
    Clean up dcm2niix multi-output suffixes on B1 map files.
    
    dcm2niix produces multiple outputs from Philips DREAM B1 sequences
    with suffixes like _e1a, _e1_ph, _e1_pha, _e1, _e2, _r100, _r20_ph.
    
    We keep the magnitude (_e1a) and B1 field map, renaming them properly:
      _e1a  -> TB1map (magnitude/anatomical from DREAM)  
      _e1   -> kept as intermediate (magnitude FFE)
      _e1_ph -> kept as intermediate (phase FFE)
      _e1_pha -> kept as intermediate (phase B1)
      
    For the DREAM-specific outputs via PRIDE reconstruction:
      The DREAMB1_combined series -> TB1map (already named by our mapping)
      The DREAM_anat series -> magnitude (already named by our mapping)
    
    For raw B1 dual-TR series, dcm2niix adds echo suffixes to our naming.
    """
    prefix = sess.subses_prefix
    
    # pattern: look for B1-related files with dcm2niix echo/phase suffixes
    # these have patterns like: {prefix}_acq-b1_run-{run}_TB1map_e1a.nii.gz
    b1_base = f"{prefix}_acq-b1_run-{run}_TB1map"
    
    # mapping of dcm2niix suffixes to final BIDS names
    # _e1a = magnitude (anatomical, B1-weighted)
    # _e1  = magnitude (FFE) - not typically needed for BIDS
    # _e1_ph = phase (FFE) - not typically needed for BIDS
    # _e1_pha = phase (B1) - not typically needed for BIDS
    suffix_targets = {
        "_e1a":   f"{prefix}_acq-b1_run-{run}_TB1map",
        "_e1_ph": None,    # remove or keep as-is
        "_e1_pha": None,   # remove or keep as-is
        "_e1":    None,    # intermediate, remove
    }
    
    found_any = False
    for dcm_suffix, target_base in suffix_targets.items():
        for ext in [".nii.gz", ".json"]:
            src = fmap_dir / f"{b1_base}{dcm_suffix}{ext}"
            if not src.exists():
                continue
            
            found_any = True
            
            if target_base is None:
                # remove intermediate files we don't need
                logger.debug(f"  Removing intermediate B1 file: {src.name}")
                src.unlink()
                if ext == ".nii.gz":
                    sess.remove_from_scans_tsv(f"fmap/{src.name}")
            else:
                dst = fmap_dir / f"{target_base}{ext}"
                if dst.exists() and not force:
                    logger.debug(f"  Target exists: {dst.name}")
                    continue
                if src.name != dst.name:
                    sess.rename_file(src, dst)
                    logger.info(f"  Renamed: {src.name} -> {dst.name}")
                    if ext == ".nii.gz":
                        sess.rename_in_scans_tsv(f"fmap/{src.name}", f"fmap/{dst.name}")
    
    # also handle _r100 / _r20_ph pattern (different dcm2niix versions)
    r_suffix_targets = {
        "_r100":   f"{prefix}_acq-b1_run-{run}_TB1map",
        "_r20_ph": None,  # remove phase map
        "_r20":    None,  # remove
    }
    
    for dcm_suffix, target_base in r_suffix_targets.items():
        for ext in [".nii.gz", ".json"]:
            src = fmap_dir / f"{b1_base}{dcm_suffix}{ext}"
            if not src.exists():
                continue
            
            found_any = True
            
            if target_base is None:
                logger.debug(f"  Removing intermediate B1 file: {src.name}")
                src.unlink()
                if ext == ".nii.gz":
                    sess.remove_from_scans_tsv(f"fmap/{src.name}")
            else:
                dst = fmap_dir / f"{target_base}{ext}"
                if dst.exists() and not force:
                    continue
                if src.name != dst.name:
                    sess.rename_file(src, dst)
                    logger.info(f"  Renamed: {src.name} -> {dst.name}")
                    if ext == ".nii.gz":
                        sess.rename_in_scans_tsv(f"fmap/{src.name}", f"fmap/{dst.name}")
    
    if not found_any:
        logger.debug(f"No B1 suffix cleanup needed for run-{run}")


def _fix_b0_maps(fmap_dir: Path, sess: Session, logger, run: int, force: bool) -> None:
    """
    Fix B0 shimmed fieldmap files.
    
    dcm2niix can produce numbered variants when a series has multiple outputs:
      {prefix}_acq-b0_run-{run}_fieldmap1 -> magnitude
      {prefix}_acq-b0_run-{run}_fieldmap2 -> fieldmap
    """
    prefix = sess.subses_prefix
    
    # numbered variants pattern
    mappings = [
        (f"{prefix}_acq-b0_run-{run}_fieldmap1", f"{prefix}_acq-b0_run-{run}_magnitude"),
        (f"{prefix}_acq-b0_run-{run}_fieldmap2", f"{prefix}_acq-b0_run-{run}_fieldmap"),
    ]
    
    # also check the old heudiconv-style b0-combined pattern
    mappings.extend([
        (f"{prefix}_run-{run}_b0-combined1", f"{prefix}_acq-b0_run-{run}_magnitude"),
        (f"{prefix}_run-{run}_b0-combined2", f"{prefix}_acq-b0_run-{run}_fieldmap"),
    ])
    
    for src_base, dst_base in mappings:
        for ext in [".nii.gz", ".json"]:
            src = fmap_dir / f"{src_base}{ext}"
            dst = fmap_dir / f"{dst_base}{ext}"
            if not src.exists():
                continue
            if dst.exists() and not force:
                continue
            sess.rename_file(src, dst)
            logger.info(f"Renamed: {src.name} -> {dst.name}")
            if ext == ".nii.gz":
                sess.rename_in_scans_tsv(f"fmap/{src.name}", f"fmap/{dst.name}")


def _fix_gre_maps(fmap_dir: Path, sess: Session, logger, run: int, force: bool) -> None:
    """
    Fix GRE fieldmap/magnitude files.
    
    dcm2niix numbered variants:
      {prefix}_acq-gre_run-{run}_fieldmap1 -> fieldmap
      {prefix}_acq-gre_run-{run}_fieldmap2 -> magnitude
      
    Also legacy heudiconv patterns:
      {prefix}_acq-gre_dir-AP_run-{run}_epi1 -> fieldmap
      {prefix}_acq-gre_dir-AP_run-{run}_epi2 -> magnitude
    """
    prefix = sess.subses_prefix
    
    mappings = [
        # dcm2niix numbered pattern
        (f"{prefix}_acq-gre_run-{run}_fieldmap1", f"{prefix}_acq-gre_run-{run}_fieldmap"),
        (f"{prefix}_acq-gre_run-{run}_fieldmap2", f"{prefix}_acq-gre_run-{run}_magnitude"),
        # legacy heudiconv pattern
        (f"{prefix}_acq-gre_dir-AP_run-{run}_epi1", f"{prefix}_acq-gre_run-{run}_fieldmap"),
        (f"{prefix}_acq-gre_dir-AP_run-{run}_epi2", f"{prefix}_acq-gre_run-{run}_magnitude"),
    ]
    
    for src_base, dst_base in mappings:
        for ext in [".nii.gz", ".json"]:
            src = fmap_dir / f"{src_base}{ext}"
            dst = fmap_dir / f"{dst_base}{ext}"
            if not src.exists():
                continue
            if dst.exists() and not force:
                continue
            sess.rename_file(src, dst)
            logger.info(f"Renamed: {src.name} -> {dst.name}")
            if ext == ".nii.gz":
                sess.rename_in_scans_tsv(f"fmap/{src.name}", f"fmap/{dst.name}")


def _add_units_to_fieldmaps(fmap_dir: Path, sess: Session, logger, run: int) -> None:
    prefix = sess.subses_prefix
    
    for pattern in [
        f"{prefix}_acq-gre_run-{run}_fieldmap",
        f"{prefix}_acq-b0_run-{run}_fieldmap",
    ]:
        nii = fmap_dir / f"{pattern}.nii.gz"
        json_f = fmap_dir / f"{pattern}.json"
        if not json_f.exists():
            continue
        
        meta = sess.get_json(nii)
        if meta.get("Units") == "rad/s":
            continue
        
        sess.make_writable(json_f)
        meta["Units"] = "rad/s"
        sess.write_json(nii, meta)
        sess.make_readonly(json_f)
        logger.info(f"Added Units=rad/s to {json_f.name}")


def _add_intended_for(fmap_dir: Path, func_dir: Path, sess: Session, logger, run: int) -> None:
    prefix = sess.subses_prefix
    
    intended_for = []
    for func_file in sorted(func_dir.glob(f"{prefix}_task-*_bold.nii.gz")):
        rel_path = func_file.relative_to(sess.paths["rawdata_subject"])
        intended_for.append(str(rel_path))
    
    if not intended_for:
        return
    
    logger.info(f"Adding IntendedFor with {len(intended_for)} functional runs")
    
    for pattern in [
        f"{prefix}_acq-b0_run-{run}_fieldmap",
        f"{prefix}_acq-gre_run-{run}_fieldmap",
        f"{prefix}_acq-se_dir-AP_run-{run}_epi",
        f"{prefix}_acq-se_dir-PA_run-{run}_epi",
    ]:
        json_f = fmap_dir / f"{pattern}.json"
        nii = fmap_dir / f"{pattern}.nii.gz"
        if not json_f.exists():
            continue
        
        meta = sess.get_json(nii)
        if meta.get("IntendedFor") == intended_for:
            continue
        
        sess.make_writable(json_f)
        meta["IntendedFor"] = intended_for
        sess.write_json(nii, meta)
        sess.make_readonly(json_f)
        logger.info(f"Updated IntendedFor in {json_f.name}")
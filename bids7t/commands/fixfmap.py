"""
fixfmap command. handle the  fieldmap files.

This command:
- Cleans up dcm2niix multi-output suffixes (_e1a, _e1_ph, _e2, _r100, etc.)
  for B1 DREAM maps and renames to proper BIDS TB1map/magnitude
- Renames B0 shimmed fieldmap numbered variants to BIDS convention
- Renames GRE fieldmap/magnitude numbered variants to BIDS convention
  (also strips invalid dir- entity from fieldmap/magnitude names)
- Adds Units field to fieldmap JSONs
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
    Clean up dcm2niix multi-output suffixes on B1 DREAM map files.
    
    dcm2niix produces multiple outputs from Philips DREAM B1 sequences.
    The exact suffixes depend on dcm2niix version:
    
    Older versions (echo-based):
      _e1    FID image (anatomical reference for coregistration) 
      _e1a   B1-map in % of nominal B1 
      _e1_ph B1 phase image 
      _e2    STEAM image
    
    Newer versions (ratio-based):
      (base) one of the outputs gets the base name
      _ph    phase 
      _r100  rescaled B1 
      _r100_ph phase of rescaled 
      _r20   another rescale 
      _r20_ph phase 
    
    Currently we keep the B1 map as TB1map, keep the FID/anatomical
    reference as magnitude companion, remove everything else.
    """
    prefix = sess.subses_prefix
    b1_base = f"{prefix}_acq-b1_run-{run}_TB1map"
    
    # suffices to REMOVE (intermediate/phase/steam files)
    remove_suffixes = [
        "_e1_ph", "_e1_pha", "_e2",           
        "_ph", "_r100_ph", "_r20_ph", "_r20",  
    ]
    
    # suffixes to RENAME to TB1map (the actual B1 field map)
    b1map_suffixes = ["_e1a", "_r100"]
    
    # suffixes to RENAME to magnitude companion (FID anatomical reference)
    magnitude_base = f"{prefix}_acq-b1_run-{run}_magnitude"
    magnitude_suffixes = ["_e1"]
    
    found_any = False
    
    # removes non-wanted files
    for dcm_suffix in remove_suffixes:
        for ext in [".nii.gz", ".json"]:
            src = fmap_dir / f"{b1_base}{dcm_suffix}{ext}"
            if not src.exists():
                continue
            found_any = True
            logger.info(f"  Removing intermediate B1 file: {src.name}")
            src.unlink()
            if ext == ".nii.gz":
                sess.remove_from_scans_tsv(f"fmap/{src.name}")
    
    # renames B1 map (_e1a -> TB1map)
    tb1_target = fmap_dir / f"{b1_base}.nii.gz"
    for dcm_suffix in b1map_suffixes:
        for ext in [".nii.gz", ".json"]:
            src = fmap_dir / f"{b1_base}{dcm_suffix}{ext}"
            if not src.exists():
                continue
            found_any = True
            dst = fmap_dir / f"{b1_base}{ext}"
            if dst.exists():
                # if target already exists this is a duplicate, remove 
                logger.info(f"  Removing duplicate B1 file: {src.name} (target exists)")
                src.unlink()
                if ext == ".nii.gz":
                    sess.remove_from_scans_tsv(f"fmap/{src.name}")
            else:
                sess.rename_file(src, dst)
                logger.info(f"  Renamed: {src.name} -> {dst.name}")
                if ext == ".nii.gz":
                    sess.rename_in_scans_tsv(f"fmap/{src.name}", f"fmap/{dst.name}")
    
    # rename FID/anatomical reference to magnitude companion
    for dcm_suffix in magnitude_suffixes:
        for ext in [".nii.gz", ".json"]:
            src = fmap_dir / f"{b1_base}{dcm_suffix}{ext}"
            if not src.exists():
                continue
            found_any = True
            dst = fmap_dir / f"{magnitude_base}{ext}"
            if dst.exists() and not force:
                logger.debug(f"  Magnitude target exists: {dst.name}")
                continue
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
    
    dcm2niix can add echo suffixes or numbered variants to the base name.
    This function separates into proper BIDS fieldmap + magnitude files.
    
    BIDS does not allow the 'dir-' entity on fieldmap/magnitude
    suffixes (only on epi). If the YAML config included dir-AP for a GRE
    series, it is stripped from the final BIDS name here.
    
    Echo-based pattern:
      {prefix}_acq-gre_dir-AP_run-{run}_fieldmap_e1a -> acq-gre_run-{run}_magnitude
      {prefix}_acq-gre_dir-AP_run-{run}_fieldmap_e1  -> acq-gre_run-{run}_fieldmap
      {prefix}_acq-gre_dir-AP_run-{run}_fieldmap_e1_ph -> remove
    
    Numbered pattern:
      {prefix}_acq-gre_run-{run}_fieldmap1 -> fieldmap
      {prefix}_acq-gre_run-{run}_fieldmap2 -> magnitude
    """
    prefix = sess.subses_prefix
    
    # target names never have dir- entity (not BIDS-valid for fieldmap/magnitude)
    clean_fieldmap = f"{prefix}_acq-gre_run-{run}_fieldmap"
    clean_magnitude = f"{prefix}_acq-gre_run-{run}_magnitude"
    
    # echo-based pattern (Philips B0mapShimmed)
    # try various dir patterns since user config may have added dir-AP/PA
    for base_suffix in ["fieldmap", "epi"]:
        for dir_part in ["_dir-AP", "_dir-PA", ""]:
            gre_base = f"{prefix}_acq-gre{dir_part}_run-{run}_{base_suffix}"
            
            # _e1a -> magnitude (anatomical echo)
            for ext in [".nii.gz", ".json"]:
                src = fmap_dir / f"{gre_base}_e1a{ext}"
                if not src.exists():
                    continue
                dst = fmap_dir / f"{clean_magnitude}{ext}"
                if dst.exists() and not force:
                    continue
                sess.rename_file(src, dst)
                logger.info(f"Renamed: {src.name} -> {dst.name}")
                if ext == ".nii.gz":
                    sess.rename_in_scans_tsv(f"fmap/{src.name}", f"fmap/{dst.name}")
            
            # _e1 -> fieldmap (strip echo suffix AND dir entity)
            for ext in [".nii.gz", ".json"]:
                src = fmap_dir / f"{gre_base}_e1{ext}"
                if not src.exists():
                    continue
                dst = fmap_dir / f"{clean_fieldmap}{ext}"
                if dst.exists() and not force:
                    continue
                sess.rename_file(src, dst)
                logger.info(f"Renamed: {src.name} -> {dst.name}")
                if ext == ".nii.gz":
                    sess.rename_in_scans_tsv(f"fmap/{src.name}", f"fmap/{dst.name}")
            
            # _e1_ph, _e2 -> remove
            for remove_suffix in ["_e1_ph", "_e2", "_e2_ph"]:
                for ext in [".nii.gz", ".json"]:
                    src = fmap_dir / f"{gre_base}{remove_suffix}{ext}"
                    if src.exists():
                        logger.info(f"  Removing intermediate GRE file: {src.name}")
                        src.unlink()
                        if ext == ".nii.gz":
                            sess.remove_from_scans_tsv(f"fmap/{src.name}")
            
            # also handle base file exists with dir- but no echo suffix
            # (user config produced fieldmap with dir-AP, no echo split)
            if dir_part:
                for ext in [".nii.gz", ".json"]:
                    src = fmap_dir / f"{gre_base}{ext}"
                    dst = fmap_dir / f"{clean_fieldmap}{ext}"
                    if not src.exists():
                        continue
                    if dst.exists() and not force:
                        continue
                    if src.name != dst.name:
                        sess.rename_file(src, dst)
                        logger.info(f"Renamed (stripped dir): {src.name} -> {dst.name}")
                        if ext == ".nii.gz":
                            sess.rename_in_scans_tsv(f"fmap/{src.name}", f"fmap/{dst.name}")
    
    # numbered pattern 
    mappings = [
        (f"{prefix}_acq-gre_run-{run}_fieldmap1", clean_fieldmap),
        (f"{prefix}_acq-gre_run-{run}_fieldmap2", clean_magnitude),
        # legacy heudiconv pattern
        (f"{prefix}_acq-gre_dir-AP_run-{run}_epi1", clean_fieldmap),
        (f"{prefix}_acq-gre_dir-AP_run-{run}_epi2", clean_magnitude),
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
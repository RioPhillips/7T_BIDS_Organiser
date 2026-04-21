"""
fixfmap command. Handle fieldmap files.

This command cleans up dcm2niix multi-output files in the fmap/ directory
and ensures BIDS-compliant naming. All operations discover files by their
BIDS suffix and preserve user-specified entities from bids7t.yaml.

Operations performed:
  1. B1 maps: classify dcm2niix outputs using JSON metadata (ImageType)
     and rename to proper TB1map + magnitude companion
  2. Fieldmap echo outputs: classify _e1/_e1a/_e1_ph patterns on
     fieldmap/epi suffixes and rename to fieldmap + magnitude
  3. Numbered variants: rename fieldmap1/2, epi1/2, b0-combined1/2
     to proper BIDS fieldmap + magnitude
  4. Dir-entity stripping: remove invalid dir- entity from
     fieldmap/magnitude suffixes (BIDS only allows dir- on epi)
  5. Units metadata: add Units=rad/s to fieldmap JSONs

Supported B1 sequences:
  - DREAM (echo-based): _e1 (FID/magnitude), _e1a (B1 map),
    _e1_ph (phase), _e2 (STEAM). No base file produced.
  - Dual TR / ratio-based: base (FFE magnitude), _r100 (B1 map),
    _r20 (rescaled), _ph/_r100_ph/_r20_ph (phases).
"""

import re
from pathlib import Path
from typing import Optional

from bids7t.core import Session, setup_logging
from bids7t.core.bids_naming import (
    parse_bids_name,
    derive_bids_name,
    strip_dcm2niix_suffix,
    classify_dcm2niix_output,
)


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

    if not list(fmap_dir.glob("*.nii.gz")):
        logger.info("No NIfTI files in fmap directory, nothing to fix")
        return

    # 1. B1 map outputs (TB1map — uses JSON metadata for classification)
    _fix_b1_outputs(fmap_dir, sess, logger, force)

    # 2. Fieldmap echo-based outputs (fieldmap/epi with _e1/_e1a/_e1_ph)
    _fix_fieldmap_echo_outputs(fmap_dir, sess, logger, force)

    # 3. Numbered variants (fieldmap1/2, epi1/2, b0-combined1/2)
    _fix_numbered_variants(fmap_dir, sess, logger, force)

    # 4. Strip invalid dir- entity from fieldmap/magnitude
    _strip_dir_from_non_epi(fmap_dir, sess, logger, force)

    # 5. Units metadata on fieldmap JSONs
    _add_units_to_fieldmaps(fmap_dir, sess, logger)

    logger.info("Fieldmap fixes complete")


# ============================================================
# Shared helpers
# ============================================================

def _remove_with_sidecar(nii_path: Path, sess: Session, logger) -> None:
    """Remove a NIfTI file and its JSON sidecar, updating scans.tsv."""
    logger.info(f"  Removing intermediate: {nii_path.name}")
    sess.remove_from_scans_tsv(f"fmap/{nii_path.name}")
    nii_path.unlink(missing_ok=True)
    json_path = nii_path.with_suffix("").with_suffix(".json")
    if json_path.exists():
        json_path.unlink()


def _rename_pair(fmap_dir: Path, src_nii: Path, dst_name: str,
                 sess: Session, logger, force: bool) -> None:
    """
    Rename a NIfTI + JSON pair to a new BIDS name, updating scans.tsv.

    If the target already exists and force is False, removes the source
    as a duplicate instead.
    """
    if src_nii.name == dst_name:
        return  # already has the correct name

    dst_nii = fmap_dir / dst_name
    src_json = src_nii.with_suffix("").with_suffix(".json")
    dst_json_name = derive_bids_name(dst_name, extension='.json')
    dst_json = fmap_dir / dst_json_name

    # if target exists: remove src as duplicate (unless force)
    if dst_nii.exists() and not force:
        logger.info(f"  Removing duplicate (target exists): {src_nii.name}")
        sess.remove_from_scans_tsv(f"fmap/{src_nii.name}")
        src_nii.unlink()
        if src_json.exists():
            src_json.unlink()
        return

    # rename NIfTI
    if src_nii.exists():
        sess.rename_file(src_nii, dst_nii)
        logger.info(f"  Renamed: {src_nii.name} -> {dst_name}")
        sess.rename_in_scans_tsv(f"fmap/{src_nii.name}", f"fmap/{dst_name}")

    # rename JSON sidecar
    if src_json.exists():
        if dst_json.exists() and not force:
            src_json.unlink()
        else:
            sess.rename_file(src_json, dst_json)


# ============================================================
# 1. B1 map outputs — JSON-based classification
# ============================================================

def _classify_b1_from_json(nii_path: Path, sess: Session) -> Optional[str]:
    """
    Classify a B1 map file using DICOM ImageType from its JSON sidecar.

    The ImageType field is preserved by dcm2niix and contains the
    actual DICOM series type, which deterministically identifies
    what each output represents regardless of dcm2niix naming.

    DICOM ImageType examples from Philips:
      ["ORIGINAL", "PRIMARY", "M_B1", "M", "B1"]      -> b1_map
      ["ORIGINAL", "PRIMARY", "M_FFE", "M", "FFE"]     -> b1_magnitude
      ["ORIGINAL", "PRIMARY", "M_IR", "M", "IR"]       -> b1_intermediate
      ["ORIGINAL", "PRIMARY", "PHASE MAP", "P", "B1"]  -> b1_phase
      ["ORIGINAL", "PRIMARY", "PHASE MAP", "P", "FFE"] -> b1_phase
      ["ORIGINAL", "PRIMARY", "PHASE MAP", "P", "IR"]  -> b1_phase

    Returns
    -------
    str or None
        'b1_map', 'b1_magnitude', 'b1_phase', 'b1_intermediate',
        or None if ImageType is not available.
    """
    meta = sess.get_json(nii_path)
    image_type = meta.get("ImageType", [])

    if not image_type:
        return None

    # normalize to uppercase for matching
    image_type_upper = [str(t).upper() for t in image_type]

    # check for phase first (PHASE MAP or P marker)
    is_phase = any("PHASE" in t for t in image_type_upper)
    if is_phase:
        return "b1_phase"

    # check for B1 map (M_B1 or just B1 in magnitude context)
    has_b1 = any(t in ("B1", "M_B1") for t in image_type_upper)
    has_ffe = any(t in ("FFE", "M_FFE") for t in image_type_upper)
    has_ir = any(t in ("IR", "M_IR") for t in image_type_upper)

    if has_b1:
        return "b1_map"
    elif has_ffe:
        return "b1_magnitude"
    elif has_ir:
        return "b1_intermediate"

    return None


def _fix_b1_outputs(fmap_dir: Path, sess: Session, logger, force: bool) -> None:
    """
    Clean up dcm2niix multi-output suffixes on B1 map files.

    Discovers TB1map files by BIDS suffix, preserving whatever entities
    the user configured (acq-b1, acq-dream, etc.).

    Classification priority:
      1. JSON metadata (ImageType from DICOM) — deterministic
      2. dcm2niix suffix patterns (_e1a, _r100, etc.) — fallback

    After classification:
      - b1_map        -> rename to clean TB1map
      - b1_magnitude  -> rename to magnitude companion
      - b1_phase      -> remove
      - b1_intermediate -> remove
      - None (clean, no variants) -> keep as-is

    Special handling when a clean base file coexists with a b1_map:
      The base is the magnitude companion (dual TR case), not a B1 map.
      It must be renamed BEFORE the actual b1_map claims the TB1map name.
    """
    tb1_files = sess.find_by_suffix_parsed("fmap", "TB1map")
    if not tb1_files:
        return

    logger.info(f"  Processing {len(tb1_files)} TB1map file(s)")

    # Group files by their clean base name (same entities, ignoring
    # dcm2niix suffix) to detect base+variant coexistence
    groups = {}
    for parsed in tb1_files:
        clean = strip_dcm2niix_suffix(parsed['path'].name)
        groups.setdefault(clean, []).append(parsed)

    for clean_name, group in groups.items():
        # Classify each file but only reclassify files with dcm2niix suffixes.
        # Clean files (no dcm2niix suffix) are already correctly named by
        # src2rawdata based on the user's YAML mapping.
        classified = []
        for parsed in group:
            path = parsed['path']
            cls = parsed['classification']

            if cls is not None:
                # File has a dcm2niix suffix — try JSON metadata first
                json_cls = _classify_b1_from_json(path, sess)
                if json_cls is not None:
                    cls = json_cls

            classified.append((parsed, cls))
            if cls is not None:
                logger.debug(f"  Classified {path.name} -> {cls}")

        # Sort into buckets
        clean_files = []     # cls is None (no dcm2niix suffix, no JSON match)
        b1_map_files = []    # actual B1 map
        b1_mag_files = []    # magnitude/anatomical reference
        remove_files = []    # phase, intermediate, etc.

        for parsed, cls in classified:
            if cls is None:
                clean_files.append(parsed)
            elif cls == 'b1_map':
                b1_map_files.append(parsed)
            elif cls == 'b1_magnitude':
                b1_mag_files.append(parsed)
            elif cls in ('b1_phase', 'b1_intermediate'):
                remove_files.append(parsed)
            else:
                logger.debug(
                    f"  Unclassified TB1map output: {parsed['path'].name} ({cls})"
                )

        # Remove phase/intermediate files first
        for parsed in remove_files:
            _remove_with_sidecar(parsed['path'], sess, logger)

        # Process explicit magnitude files (_e1 from DREAM, or JSON-classified FFE)
        for parsed in b1_mag_files:
            mag_name = derive_bids_name(parsed['path'].name, suffix='magnitude')
            _rename_pair(fmap_dir, parsed['path'], mag_name, sess, logger, force)

        # Determine if the clean base file is actually the magnitude.
        # This happens with dual TR sequences: the base (no dcm2niix
        # suffix) is the FFE magnitude, and _r100 is the actual B1 map.
        # Must rename base BEFORE b1_map claims the TB1map slot.
        base_is_magnitude = len(clean_files) > 0 and len(b1_map_files) > 0

        if base_is_magnitude:
            for parsed in clean_files:
                mag_name = derive_bids_name(parsed['path'].name, suffix='magnitude')
                logger.info(f"  Base file is magnitude (b1_map variant exists)")
                _rename_pair(fmap_dir, parsed['path'], mag_name, sess, logger, force)
        # else: clean file with no b1_map coexisting -> already correct TB1map

        # Process b1_map files (_e1a from DREAM, _r100 from dual TR)
        # Safe to rename now since base has been moved out of the way
        for parsed in b1_map_files:
            _rename_pair(fmap_dir, parsed['path'], clean_name, sess, logger, force)


# ============================================================
# 2. Fieldmap echo-based outputs
# ============================================================

def _fix_fieldmap_echo_outputs(fmap_dir: Path, sess: Session, logger, force: bool) -> None:
    """
    Clean up dcm2niix echo-based suffixes on fieldmap/epi files.

    Handles both GRE-based and B0-shimmed fieldmaps. Discovers by suffix
    and preserves user entities. Also strips invalid dir- entity from
    non-epi targets.

    Classification mapping:
      - fieldmap_magnitude  (_e1a) -> magnitude (dir- stripped)
      - fieldmap_main       (_e1)  -> fieldmap  (dir- stripped if not epi)
      - fieldmap_intermediate (_e1_ph, _e2, _e2_ph) -> remove
    """
    for suffix in ['fieldmap', 'epi']:
        parsed_files = sess.find_by_suffix_parsed("fmap", suffix)

        for parsed in parsed_files:
            path = parsed['path']
            cls = parsed['classification']

            if cls is None:
                continue  # clean file

            if cls == 'fieldmap_intermediate':
                _remove_with_sidecar(path, sess, logger)

            elif cls == 'fieldmap_magnitude':
                # magnitude companion — strip dir- (not BIDS-valid on magnitude)
                mag_name = derive_bids_name(
                    path.name, suffix='magnitude',
                    remove_entities=['dir']
                )
                _rename_pair(fmap_dir, path, mag_name, sess, logger, force)

            elif cls == 'fieldmap_main':
                # the fieldmap itself
                # dir- is valid on epi but NOT on fieldmap/magnitude
                remove = ['dir'] if suffix != 'epi' else None
                clean_name = derive_bids_name(
                    path.name, suffix='fieldmap',
                    remove_entities=remove
                )
                _rename_pair(fmap_dir, path, clean_name, sess, logger, force)


# ============================================================
# 3. Numbered variants
# ============================================================

_NUMBERED_PATTERN = re.compile(r'^(fieldmap|epi|b0-combined)(\d+)$')


def _fix_numbered_variants(fmap_dir: Path, sess: Session, logger, force: bool) -> None:
    """
    Handle dcm2niix numbered output variants.

    dcm2niix sometimes produces numbered outputs instead of echo-based::

        sub-X_acq-b0_run-1_fieldmap1.nii.gz  -> magnitude
        sub-X_acq-b0_run-1_fieldmap2.nii.gz  -> fieldmap

    Also handles legacy heudiconv patterns (epi1/2, b0-combined1/2).

    Default convention: 1 = magnitude, 2 = fieldmap.
    All user entities are preserved through the rename.
    """
    # collect files first to avoid modifying dir while iterating
    to_process = []
    for f in sorted(fmap_dir.glob("*.nii.gz")):
        parsed = parse_bids_name(f.name)
        m = _NUMBERED_PATTERN.match(parsed['suffix'])
        if m:
            to_process.append((f, parsed, m.group(1), int(m.group(2))))

    if not to_process:
        return

    logger.info(f"  Processing {len(to_process)} numbered variant(s)")

    for f, parsed, base_suffix, number in to_process:
        # convention: 1 = magnitude, 2 = fieldmap
        if number == 1:
            target_suffix = 'magnitude'
        elif number == 2:
            target_suffix = 'fieldmap'
        else:
            logger.debug(f"  Skipping unexpected numbered variant: {f.name}")
            continue

        # strip dir- from non-epi targets (not BIDS-valid)
        remove = ['dir'] if target_suffix in ('fieldmap', 'magnitude') else None

        target_name = derive_bids_name(
            f.name, suffix=target_suffix,
            remove_entities=remove
        )
        _rename_pair(fmap_dir, f, target_name, sess, logger, force)


# ============================================================
# 4. Strip invalid dir- entity
# ============================================================

def _strip_dir_from_non_epi(fmap_dir: Path, sess: Session, logger, force: bool) -> None:
    """
    Strip invalid dir- entity from fieldmap and magnitude files.

    BIDS only allows the dir- entity on the epi suffix. If user config
    or upstream processing left dir-AP/PA on fieldmap or magnitude files,
    strip it here.
    """
    for suffix in ['fieldmap', 'magnitude']:
        files = sess.find_by_suffix("fmap", suffix, include_dcm2niix=False)
        for f in files:
            parsed = parse_bids_name(f.name)
            if 'dir' not in parsed['entities']:
                continue

            clean_name = derive_bids_name(f.name, remove_entities=['dir'])
            if clean_name == f.name:
                continue

            dst = fmap_dir / clean_name
            if dst.exists() and not force:
                logger.debug(f"  Target exists, skipping dir strip: {f.name}")
                continue

            _rename_pair(fmap_dir, f, clean_name, sess, logger, force)


# ============================================================
# 5. Units metadata
# ============================================================

def _add_units_to_fieldmaps(fmap_dir: Path, sess: Session, logger) -> None:
    """
    Add Units=rad/s to all fieldmap JSON sidecars.

    Discovers fieldmap files by suffix, regardless of user entities.
    """
    fieldmap_files = sess.find_by_suffix(
        "fmap", "fieldmap", include_dcm2niix=False
    )

    for nii in fieldmap_files:
        json_f = nii.with_suffix("").with_suffix(".json")
        if not json_f.exists():
            continue

        meta = sess.get_json(nii)
        if meta.get("Units") == "rad/s":
            continue

        sess.make_writable(json_f)
        meta["Units"] = "rad/s"
        sess.write_json(nii, meta)
        sess.make_readonly(json_f)
        logger.info(f"  Added Units=rad/s to {json_f.name}")
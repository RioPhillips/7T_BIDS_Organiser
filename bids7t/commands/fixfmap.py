"""
fixfmap command. Handle fieldmap files.

This command cleans up dcm2niix multi-output files in the fmap/ directory
and ensures BIDS-compliant naming. All operations discover files by their
BIDS suffix and preserve user-specified entities from bids7t.yaml.

Operations performed:
  1. B1 DREAM maps: classify dcm2niix outputs (_e1a, _e1, _e1_ph, _e2,
     _r100, etc.) and rename to proper TB1map + magnitude companion
  2. Fieldmap echo outputs: classify _e1/_e1a/_e1_ph patterns on
     fieldmap/epi suffixes and rename to fieldmap + magnitude
  3. Numbered variants: rename fieldmap1/2, epi1/2, b0-combined1/2
     to proper BIDS fieldmap + magnitude
  4. Dir-entity stripping: remove invalid dir- entity from
     fieldmap/magnitude suffixes (BIDS only allows dir- on epi)
  5. Units metadata: add Units=rad/s to fieldmap JSONs

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

    # 1. B1 map outputs (TB1map with dcm2niix echo/ratio suffixes)
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
# 1. B1 DREAM map outputs
# ============================================================

def _fix_b1_outputs(fmap_dir: Path, sess: Session, logger, force: bool) -> None:
    """
    Clean up dcm2niix multi-output suffixes on B1 DREAM map files.

    Discovers TB1map files by BIDS suffix, preserving whatever entities
    the user configured (acq-b1, acq-dream, desc-whatever, etc.).

    Uses classify_dcm2niix_output() to determine each file's role:
      - b1_map     (_e1a, _r100)  -> rename to clean TB1map
      - b1_magnitude (_e1)        -> rename to magnitude companion
      - b1_phase, b1_intermediate -> remove
      - None       (clean file)   -> keep as-is
    """
    tb1_files = sess.find_by_suffix_parsed("fmap", "TB1map")
    if not tb1_files:
        return

    logger.info(f"  Processing {len(tb1_files)} TB1map file(s)")

    for parsed in tb1_files:
        path = parsed['path']
        cls = parsed['classification']

        if cls is None:
            continue  # already clean

        if cls in ('b1_phase', 'b1_intermediate'):
            _remove_with_sidecar(path, sess, logger)

        elif cls == 'b1_map':
            # strip dcm2niix suffix -> clean TB1map name
            clean_name = strip_dcm2niix_suffix(path.name)
            _rename_pair(fmap_dir, path, clean_name, sess, logger, force)

        elif cls == 'b1_magnitude':
            # change suffix to magnitude, preserving all user entities
            mag_name = derive_bids_name(path.name, suffix='magnitude')
            _rename_pair(fmap_dir, path, mag_name, sess, logger, force)

        else:
            logger.debug(f"  Unclassified TB1map output: {path.name} ({cls})")


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
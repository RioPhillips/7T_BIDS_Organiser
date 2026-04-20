"""
fixanat command. Handles anatomical files (MP2RAGE processing).

Works with dcm2niix output patterns (e.g. _real, _imaginary suffixes),
splits combined inv-1and2 files, computes mag/phase from real/imag,
reshapes UNIT1, injects MP2RAGE metadata.

All operations discover files by BIDS suffix and preserve user-specified
entities from bids7t.yaml.
"""

import re
import json
from pathlib import Path
from typing import List, Set, Optional, Dict, Any, Tuple

import numpy as np
import nibabel as nib

from bids7t.core import Session, setup_logging, check_outputs_exist
from bids7t.core.session import load_mp2rage_params
from bids7t.core.bids_naming import (
    parse_bids_name,
    build_bids_name,
    derive_bids_name,
    classify_dcm2niix_output,
    strip_dcm2niix_suffix,
    BIDS_ENTITY_ORDER,
)


def run_fixanat(studydir: Path, subject: str, session: Optional[str] = None,
                force: bool = False, verbose: bool = False) -> None:
    sess = Session(studydir, subject, session)
    log_file = sess.paths["logs"] / "fixanat.log"
    logger = setup_logging("fixanat", log_file, verbose)

    anat_dir = sess.paths["anat"]
    if not anat_dir.exists():
        logger.info("No anat directory found, skipping.")
        return

    session_label = f"_ses-{session}" if session else ""
    logger.info(f"Fixing anatomical files for sub-{subject}{session_label}")

    mp2rage_params = load_mp2rage_params(studydir)

    # normalize legacy MP2RAGE1/2/3 naming
    _normalize_mp2rage_names(anat_dir, sess, logger)

    # find all runs that have MP2RAGE data
    run_numbers = _find_run_numbers(anat_dir, sess)

    if not run_numbers:
        all_mp2rage = sess.find_by_suffix("anat", "MP2RAGE")
        if not all_mp2rage:
            logger.info("No MP2RAGE files found, skipping")
        return

    logger.info(f"Found anatomical runs: {sorted(run_numbers)}")

    for run in sorted(run_numbers):
        expected = _get_expected_outputs(anat_dir, sess, run)
        if expected:
            should_run, _ = check_outputs_exist(expected, logger, force)
            if not should_run:
                continue
        logger.info(f"Processing run-{run}")

        # split combined inv-1and2 files
        _split_inv_files(anat_dir, sess, logger, run)

        # compute magnitude/phase from real+imag pairs
        _compute_mag_phase(anat_dir, sess, logger, run)

        # reshape UNIT1 (T1w) if it has dummy dimensions
        _reshape_unit1(anat_dir, sess, logger, run)

        # inject MP2RAGE-specific BIDS metadata
        if mp2rage_params:
            _inject_mp2rage_metadata(anat_dir, sess, logger, mp2rage_params, run)

    # remove combined originals and temp files
    _remove_combined_files(anat_dir, sess, logger)
    _remove_temp_files(anat_dir, sess, logger)
    sess.sync_scans_tsv(remove_missing=True, add_new=False)
    logger.info("Anatomical fixes complete")


# ============================================================
# Temp file naming helper
# ============================================================

def _make_temp_name(source_name: str, inv: int, part_label: str,
                    extension: Optional[str] = None) -> str:
    """
    Create a temp intermediate filename for mag/phase computation.

    Preserves all user entities from the source name, changes inv and part,
    and adds a ``_temp`` marker between entities and suffix. The marker
    is automatically stripped by ``derive_bids_name`` when creating final
    output names from temp files.

    Parameters
    ----------
    source_name : str
        Source BIDS filename (typically an inv-1and2 file).
    inv : int
        Inversion number (1 or 2).
    part_label : str
        Part label ('real' or 'imag').
    extension : str, optional
        Override extension. None keeps source extension.
    """
    parsed = parse_bids_name(source_name)
    entities = dict(parsed['entities'])
    entities['inv'] = str(inv)
    entities['part'] = part_label
    ext = extension if extension is not None else parsed['extension']

    parts = [parsed['prefix']] if parsed['prefix'] else []
    added = set()
    for ek in BIDS_ENTITY_ORDER:
        if ek in entities:
            parts.append(f"{ek}-{entities[ek]}")
            added.add(ek)
    for k in sorted(entities):
        if k not in added:
            parts.append(f"{k}-{entities[k]}")
    parts.append('temp')
    parts.append(parsed['suffix'])
    return '_'.join(parts) + ext


# ============================================================
# Discovery helpers
# ============================================================

def _find_run_numbers(anat_dir: Path, sess: Session) -> Set[int]:
    """Find all run numbers that have MP2RAGE data."""
    all_mp2rage = sess.find_by_suffix("anat", "MP2RAGE")
    runs = set()
    for f in all_mp2rage:
        parsed = parse_bids_name(f.name)
        run_val = parsed['entities'].get('run')
        if run_val is not None:
            try:
                runs.add(int(run_val))
            except ValueError:
                pass
    return runs


def _get_expected_outputs(anat_dir: Path, sess: Session, run: int) -> List[Path]:
    """
    Build expected output paths from existing inv-1and2 files.

    Derives the expected output names from the actual source files,
    preserving user entities.
    """
    inv_files = sess.find_by_suffix("anat", "MP2RAGE",
                                    {"inv": "1and2", "run": str(run)})
    if not inv_files:
        return []

    # use the first file as a template for name derivation
    template = inv_files[0].name
    expected = []
    for inv in [1, 2]:
        for part in ["mag", "phase"]:
            name = derive_bids_name(template, inv=str(inv), part=part)
            expected.append(anat_dir / name)
    return expected


# ============================================================
# 1. Normalize legacy MP2RAGE1/2/3 naming
# ============================================================

def _normalize_mp2rage_names(anat_dir: Path, sess: Session, logger) -> None:
    """
    Handle older heudiconv MP2RAGE1/2/3 naming patterns.

    Renames numbered MP2RAGE suffixes to standard BIDS names::

        MP2RAGE1 -> MP2RAGE            (combined magnitude)
        MP2RAGE2 -> part-real_MP2RAGE  (real component)
        MP2RAGE3 -> part-imag_MP2RAGE  (imaginary component)

    User entities from the source filename are preserved.
    """
    mp2rage_num_re = re.compile(r'^MP2RAGE(\d)$')

    to_rename = []
    for f in sorted(anat_dir.iterdir()):
        if not (f.name.endswith('.nii.gz') or f.name.endswith('.json')):
            continue
        parsed = parse_bids_name(f.name)
        m = mp2rage_num_re.match(parsed['suffix'])
        if m:
            to_rename.append((f, parsed, m.group(1)))

    if not to_rename:
        return

    logger.info("Found MP2RAGE1/2/3 pattern -> renaming")

    # mapping: suffix number -> entity overrides for derive_bids_name
    # '1' is the combined magnitude (no extra part entity)
    # '2' is the real component
    # '3' is the imaginary component
    suffix_map = {
        '1': {},
        '2': {'part': 'real'},
        '3': {'part': 'imag'},
    }

    for src, parsed, num in to_rename:
        if num not in suffix_map:
            continue

        overrides = dict(suffix_map[num])
        overrides['suffix'] = 'MP2RAGE'
        target_name = derive_bids_name(src.name, **overrides)
        dst = anat_dir / target_name

        if dst.exists():
            continue

        sess.rename_file(src, dst)
        logger.info(f"  Renamed: {src.name} -> {target_name}")
        if src.name.endswith('.nii.gz'):
            sess.rename_in_scans_tsv(f"anat/{src.name}", f"anat/{target_name}")


# ============================================================
# 2. Split combined inv-1and2 files
# ============================================================

def _split_inv_files(anat_dir: Path, sess: Session, logger, run: int) -> None:
    """
    Split combined inv-1and2 files into separate inv-1/inv-2 files.

    Discovers inv-1and2 MP2RAGE files by suffix + entity filter, then
    classifies each by its dcm2niix suffix to determine handling:

    1. ``_real`` suffix -> split into inv-1/inv-2 temp files (for mag/phase)
    2. ``_imaginary`` suffix -> split into inv-1/inv-2 temp files
    3. Clean file (no dcm2niix suffix) -> split into inv-1/inv-2 final files
    4. ``_magnitude``/``_phase`` -> removed if real+imag exist (redundant)
    """
    inv_files = sess.find_by_suffix_parsed("anat", "MP2RAGE",
                                           {"inv": "1and2", "run": str(run)})
    if not inv_files:
        return

    # categorize by dcm2niix classification
    categorized: Dict[str, list] = {
        'real': [], 'imaginary': [], 'magnitude': [], 'other': []
    }
    for parsed in inv_files:
        cls = parsed['classification']
        if cls == 'real':
            categorized['real'].append(parsed)
        elif cls == 'imaginary':
            categorized['imaginary'].append(parsed)
        elif cls in ('magnitude', 'phase'):
            categorized['magnitude'].append(parsed)
        elif cls is None:
            categorized['other'].append(parsed)
        else:
            # unknown dcm2niix suffix — treat as 'other'
            categorized['other'].append(parsed)

    # log what we found
    for category, files in categorized.items():
        if files:
            logger.info(f"  Found {category}: {[p['filename'] for p in files]}")

    has_real = len(categorized['real']) > 0
    has_imag = len(categorized['imaginary']) > 0

    # split real files -> temp inv-1/inv-2 with part-real
    for parsed in categorized['real']:
        _split_4d_inv(anat_dir, parsed['path'], sess, logger, run, part_label="real")

    # split imaginary files -> temp inv-1/inv-2 with part-imag
    for parsed in categorized['imaginary']:
        _split_4d_inv(anat_dir, parsed['path'], sess, logger, run, part_label="imag")

    # split clean inv-1and2 -> final inv-1/inv-2 (magnitude)
    for parsed in categorized['other']:
        _split_4d_inv(anat_dir, parsed['path'], sess, logger, run, part_label=None)

    # remove magnitude dcm2niix outputs if we have real+imag (they're redundant)
    if has_real and has_imag:
        for parsed in categorized['magnitude']:
            path = parsed['path']
            logger.info(f"  Removing redundant magnitude (have real+imag): {path.name}")
            json_path = path.with_suffix("").with_suffix(".json")
            sess.remove_from_scans_tsv(f"anat/{path.name}")
            path.unlink()
            if json_path.exists():
                json_path.unlink()


def _split_4d_inv(anat_dir: Path, nii_path: Path, sess: Session,
                   logger, run: int, part_label: Optional[str]) -> None:
    """
    Split a single 4D inv-1and2 file into two 3D inv files.

    Output naming uses ``derive_bids_name`` (for final files) or
    ``_make_temp_name`` (for intermediates), preserving all user entities.

    Parameters
    ----------
    part_label : str or None
        'real' or 'imag' -> creates _temp_ intermediates for mag/phase
        None -> creates final inv-1/inv-2 magnitude files directly
    """
    source_name = nii_path.name

    logger.info(f"  Splitting: {source_name}")
    try:
        nii = nib.load(nii_path)
        data = nii.get_fdata()
    except Exception as e:
        logger.warning(f"Could not load {source_name}: {e}")
        return

    # read JSON sidecar
    json_path = nii_path.with_suffix("").with_suffix(".json")
    json_dict = {}
    if json_path.exists():
        try:
            with open(json_path) as f:
                json_dict = json.load(f)
        except Exception:
            pass

    if data.ndim != 4 or data.shape[-1] != 2:
        logger.warning(
            f"Unexpected shape {data.shape} for {source_name}, "
            f"expected 4D with 2 volumes"
        )
        return

    new_rels = []
    for i, inv in enumerate([1, 2]):
        if part_label:
            # temp file for mag/phase computation
            out_name = _make_temp_name(source_name, inv, part_label)
        else:
            # final inv file (magnitude) — derive preserving entities
            out_name = derive_bids_name(source_name, inv=str(inv))

        out_nii = anat_dir / out_name
        out_json_name = out_name.replace('.nii.gz', '.json')
        out_json = anat_dir / out_json_name

        try:
            img = nib.Nifti1Image(data[..., i], nii.affine, nii.header)
            nib.save(img, out_nii)

            meta = dict(json_dict)
            meta["dcmmeta_shape"] = list(data[..., i].shape)
            if part_label:
                meta["part"] = part_label

            with open(out_json, "w") as f:
                json.dump(meta, f, indent=2)

            logger.info(f"    Created: {out_nii.name}")

            if not part_label:
                new_rels.append(f"anat/{out_nii.name}")
        except Exception as e:
            logger.warning(f"Failed to create {out_name}: {e}")

    # update scans.tsv for non-temp files
    if new_rels:
        sess.replace_in_scans_tsv(f"anat/{source_name}", new_rels)


# ============================================================
# 3. Compute magnitude/phase from real+imaginary pairs
# ============================================================

def _compute_mag_phase(anat_dir: Path, sess: Session, logger, run: int) -> None:
    """
    Compute magnitude and phase images from real+imaginary temp pairs.

    Discovers temp files by glob + entity parsing. Output names are
    derived from the temp files, which automatically strips the _temp_
    marker and preserves all user entities.
    """
    for inv in [1, 2]:
        real_f = _find_temp_file(anat_dir, run, inv, 'real')
        imag_f = _find_temp_file(anat_dir, run, inv, 'imag')

        if not real_f or not imag_f:
            continue

        logger.info(f"  Computing mag/phase for inv-{inv}")
        try:
            nii_r = nib.load(real_f)
            nii_i = nib.load(imag_f)
            rd, id_ = nii_r.get_fdata(), nii_i.get_fdata()
        except Exception as e:
            logger.warning(f"Could not load files for inv-{inv}: {e}")
            continue

        if rd.shape != id_.shape:
            logger.error(
                f"Shape mismatch inv-{inv}: real={rd.shape}, imag={id_.shape}"
            )
            continue

        mag = np.sqrt(rd**2 + id_**2)
        phase = np.arctan2(id_, rd)

        # base metadata from the real temp JSON
        real_json = real_f.with_suffix("").with_suffix(".json")
        base_meta = {}
        if real_json.exists():
            try:
                with open(real_json) as f:
                    base_meta = json.load(f)
            except Exception:
                pass

        # inherit scans.tsv metadata from the magnitude-only split file (if it exists)
        mag_only_name = derive_bids_name(real_f.name, remove_entities=['part'])
        inv_entry = sess.get_scans_entry(f"anat/{mag_only_name}")
        inherited = {k: v for k, v in (inv_entry or {}).items() if k != "filename"}

        for part_label, d in [("mag", mag), ("phase", phase)]:
            # derive_bids_name from temp file: strips _temp_, sets part
            out_name = derive_bids_name(real_f.name, part=part_label)
            out_nii = anat_dir / out_name
            out_json = anat_dir / out_name.replace('.nii.gz', '.json')
            try:
                nib.save(nib.Nifti1Image(d, nii_r.affine, nii_r.header), out_nii)
                m = dict(base_meta)
                m["dcmmeta_shape"] = list(d.shape)
                m["part"] = part_label
                with open(out_json, "w") as f:
                    json.dump(m, f, indent=2)
                logger.info(f"    Created: {out_nii.name}")
                sess.add_to_scans_tsv(f"anat/{out_nii.name}", **(inherited or {}))
            except Exception as e:
                logger.warning(f"Failed: {out_name}: {e}")


def _find_temp_file(anat_dir: Path, run: int, inv: int,
                    part_label: str) -> Optional[Path]:
    """Find a temp intermediate file by matching run, inv, and part entities."""
    for f in sorted(anat_dir.glob("*_temp_MP2RAGE.nii.gz")):
        parsed = parse_bids_name(f.name)
        e = parsed['entities']
        if (e.get('run') == str(run) and
                e.get('inv') == str(inv) and
                e.get('part') == part_label):
            return f
    return None


# ============================================================
# 4. Reshape UNIT1 (T1w)
# ============================================================

def _reshape_unit1(anat_dir: Path, sess: Session, logger, run: int) -> None:
    """
    Reshape T1w files if they have dummy 4th dimensions.

    Discovers T1w files by suffix for the given run. Handles any acq
    value the user may have configured (acq-mp2rage, acq-UNI, etc.).
    """
    t1w_files = sess.find_by_suffix("anat", "T1w", {"run": str(run)})

    for t1w in t1w_files:
        try:
            nii = nib.load(t1w)
            data = nii.get_fdata()
        except Exception:
            continue

        if data.ndim == 4 and 1 in data.shape:
            logger.info(f"  Reshaping T1w from {data.shape} to 3D")
            new_data = data.squeeze()
            new_nii = nib.Nifti1Image(new_data, nii.affine)
            new_nii.header.set_xyzt_units(*nii.header.get_xyzt_units())
            tmp = anat_dir / ".t1w_tmp.nii.gz"
            nib.save(new_nii, tmp)
            tmp.replace(t1w)
            logger.info(f"  Reshaped: {t1w.name}")


# ============================================================
# 5. MP2RAGE metadata injection
# ============================================================

def _inject_mp2rage_metadata(anat_dir: Path, sess: Session, logger,
                             mp2rage_params: Dict, run: int) -> None:
    """
    Inject MP2RAGE-specific BIDS metadata into JSON sidecars.

    Discovers MP2RAGE and T1w files by suffix, preserving whatever
    entity names the user configured.

    Injects:
    - Common params (RepetitionTimeExcitation, etc.) into all MP2RAGE + T1w
    - Per-inversion params (InversionTime, FlipAngle) into inv-1/inv-2 files
    - Units=rad for phase images
    """
    common = {
        "RepetitionTimeExcitation": mp2rage_params["RepetitionTimeExcitation"],
        "RepetitionTimePreparation": mp2rage_params["RepetitionTimePreparation"],
        "NumberShots": mp2rage_params["NumberShots"],
    }

    # inject into MP2RAGE inv-1 and inv-2 JSON files
    for inv in [1, 2]:
        inv_params = {
            "InversionTime": mp2rage_params["InversionTime"][inv - 1],
            "FlipAngle": mp2rage_params["FlipAngle"][inv - 1],
        }

        mp2rage_jsons = sess.find_by_suffix(
            "anat", "MP2RAGE",
            {"run": str(run), "inv": str(inv)},
            extension="*.json"
        )

        for json_path in mp2rage_jsons:
            # skip temp intermediate files
            if '_temp_' in json_path.name:
                continue
            try:
                with open(json_path) as f:
                    meta = json.load(f)
                meta.update(common)
                meta.update(inv_params)

                # add Units for phase images
                parsed = parse_bids_name(json_path.name)
                if parsed['entities'].get('part') == 'phase':
                    meta["Units"] = "rad"

                sess.make_writable(json_path)
                with open(json_path, "w") as f:
                    json.dump(meta, f, indent=2)
                sess.make_readonly(json_path)
                logger.info(f"  Injected MP2RAGE metadata: {json_path.name}")
            except Exception as e:
                logger.warning(f"Could not update {json_path.name}: {e}")

    # inject common params into T1w files for this run
    t1w_jsons = sess.find_by_suffix(
        "anat", "T1w",
        {"run": str(run)},
        extension="*.json"
    )

    for json_path in t1w_jsons:
        try:
            with open(json_path) as f:
                meta = json.load(f)
            meta.update(common)
            sess.make_writable(json_path)
            with open(json_path, "w") as f:
                json.dump(meta, f, indent=2)
            sess.make_readonly(json_path)
            logger.info(f"  Injected MP2RAGE metadata: {json_path.name}")
        except Exception as e:
            logger.warning(f"Could not update T1w JSON: {e}")


# ============================================================
# 6. Cleanup
# ============================================================

def _remove_combined_files(anat_dir: Path, sess: Session, logger) -> None:
    """Remove original combined inv-1and2 files (including any dcm2niix suffixes)."""
    for f in sorted(anat_dir.glob("*inv-1and2*")):
        f.unlink()
        logger.info(f"Removed combined: {f.name}")


def _remove_temp_files(anat_dir: Path, sess: Session, logger) -> None:
    """Remove temp intermediate files created during mag/phase computation."""
    for f in sorted(anat_dir.glob("*_temp_MP2RAGE*")):
        f.unlink()
        logger.debug(f"Removed temp: {f.name}")
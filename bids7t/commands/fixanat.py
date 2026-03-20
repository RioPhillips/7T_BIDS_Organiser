"""
fixanat command - Fix anatomical files (MP2RAGE processing).

Normalizes MP2RAGE naming, splits inv-1and2, computes mag/phase,
reshapes UNIT1, injects MP2RAGE metadata.
"""

import re
import json
from pathlib import Path
from typing import List, Set, Optional, Dict, Any

import numpy as np
import nibabel as nib

from bids7t.core import Session, setup_logging, check_outputs_exist
from bids7t.core.session import load_mp2rage_params


def _inject_mp2rage_metadata(anat_dir, sess, logger, mp2rage_params, run):
    prefix = sess.subses_prefix
    common = {
        "RepetitionTimeExcitation": mp2rage_params["RepetitionTimeExcitation"],
        "RepetitionTimePreparation": mp2rage_params["RepetitionTimePreparation"],
        "NumberShots": mp2rage_params["NumberShots"],
    }
    for inv in [1, 2]:
        inv_params = {
            "InversionTime": mp2rage_params["InversionTime"][inv - 1],
            "FlipAngle": mp2rage_params["FlipAngle"][inv - 1],
        }
        for json_name in [
            f"{prefix}_run-{run}_inv-{inv}_MP2RAGE.json",
            f"{prefix}_run-{run}_inv-{inv}_part-mag_MP2RAGE.json",
            f"{prefix}_run-{run}_inv-{inv}_part-phase_MP2RAGE.json",
        ]:
            json_path = anat_dir / json_name
            if not json_path.exists():
                continue
            try:
                with open(json_path) as f:
                    meta = json.load(f)
                meta.update(common)
                meta.update(inv_params)
                if "_part-phase_" in json_name:
                    meta["Units"] = "rad"
                sess.make_writable(json_path)
                with open(json_path, "w") as f:
                    json.dump(meta, f, indent=2)
                sess.make_readonly(json_path)
                logger.info(f"  Injected MP2RAGE metadata: {json_name}")
            except Exception as e:
                logger.warning(f"Could not update {json_name}: {e}")

    t1w_json = anat_dir / f"{prefix}_acq-mp2rage_run-{run}_T1w.json"
    if t1w_json.exists():
        try:
            with open(t1w_json) as f:
                meta = json.load(f)
            meta.update(common)
            sess.make_writable(t1w_json)
            with open(t1w_json, "w") as f:
                json.dump(meta, f, indent=2)
            sess.make_readonly(t1w_json)
            logger.info(f"  Injected MP2RAGE metadata: {t1w_json.name}")
        except Exception as e:
            logger.warning(f"Could not update T1w JSON: {e}")


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
    _normalize_mp2rage_names(anat_dir, sess, logger)
    run_numbers = _find_run_numbers(anat_dir, sess.subses_prefix)

    if not run_numbers:
        if not list(anat_dir.glob("*MP2RAGE*.nii.gz")):
            logger.info("No MP2RAGE files found, skipping")
        return

    logger.info(f"Found anatomical runs: {sorted(run_numbers)}")

    for run in sorted(run_numbers):
        expected = _get_expected_outputs(anat_dir, sess.subses_prefix, run)
        if expected:
            should_run, _ = check_outputs_exist(expected, logger, force)
            if not should_run:
                continue
        logger.info(f"Processing run-{run}")
        _split_inv_files(anat_dir, sess, logger, run)
        _compute_mag_phase(anat_dir, sess, logger, run)
        _reshape_unit1(anat_dir, sess, logger, run)
        if mp2rage_params:
            _inject_mp2rage_metadata(anat_dir, sess, logger, mp2rage_params, run)

    _remove_combined_files(anat_dir, sess, logger)
    _remove_temp_files(anat_dir, sess, logger)
    sess.sync_scans_tsv(remove_missing=True, add_new=False)
    logger.info("Anatomical fixes complete")


def _normalize_mp2rage_names(anat_dir, sess, logger):
    prefix = sess.subses_prefix
    numbered_pattern = re.compile(
        rf"({re.escape(prefix)}_run-(\d+)_inv-1and2_MP2RAGE)(\d)\.(nii\.gz|json)"
    )
    files_by_run = {}
    for f in anat_dir.iterdir():
        m = numbered_pattern.match(f.name)
        if m:
            run_num = int(m.group(2))
            suffix_num = m.group(3)
            files_by_run.setdefault(run_num, {}).setdefault(suffix_num, []).append(f)

    if not files_by_run:
        return

    logger.info("Found MP2RAGE1/2/3 pattern -> renaming")
    for run_num in sorted(files_by_run):
        base = f"{prefix}_run-{run_num}_inv-1and2"
        mappings = {"1": f"{base}_MP2RAGE", "2": f"{base}_part-real_MP2RAGE", "3": f"{base}_part-imag_MP2RAGE"}
        for sn, target_base in mappings.items():
            for src in files_by_run[run_num].get(sn, []):
                ext = ".nii.gz" if src.name.endswith(".nii.gz") else ".json"
                dst = anat_dir / f"{target_base}{ext}"
                if dst.exists():
                    continue
                sess.rename_file(src, dst)
                logger.info(f"  Renamed: {src.name} -> {dst.name}")
                if ext == ".nii.gz":
                    sess.rename_in_scans_tsv(f"anat/{src.name}", f"anat/{dst.name}")


def _find_run_numbers(anat_dir, prefix):
    runs = set()
    for f in anat_dir.glob(f"{prefix}_*MP2RAGE*.nii.gz"):
        m = re.search(r"run-(\d+)", f.name)
        if m:
            runs.add(int(m.group(1)))
    return runs


def _get_expected_outputs(anat_dir, prefix, run):
    return [anat_dir / f"{prefix}_run-{run}_inv-{inv}_part-{part}_MP2RAGE.nii.gz"
            for inv in [1, 2] for part in ["mag", "phase"]]


def _split_inv_files(anat_dir, sess, logger, run):
    prefix = sess.subses_prefix
    variants = [
        ("real", f"{prefix}_run-{run}_inv-1and2_part-real_MP2RAGE.nii.gz"),
        ("imag", f"{prefix}_run-{run}_inv-1and2_part-imag_MP2RAGE.nii.gz"),
        (None, f"{prefix}_run-{run}_inv-1and2_MP2RAGE.nii.gz"),
    ]
    for part_bids, fname in variants:
        nii_path = anat_dir / fname
        if not nii_path.exists():
            continue
        logger.info(f"Splitting: {nii_path.name}")
        try:
            nii = nib.load(nii_path)
            data = nii.get_fdata()
        except Exception as e:
            logger.warning(f"Could not load {nii_path.name}: {e}")
            continue
        json_path = nii_path.with_suffix("").with_suffix(".json")
        json_dict = {}
        if json_path.exists():
            try:
                with open(json_path) as f:
                    json_dict = json.load(f)
            except Exception:
                pass
        if data.ndim != 4 or data.shape[-1] != 2:
            logger.warning(f"Unexpected shape {data.shape} for {nii_path.name}")
            continue
        new_rels = []
        for i, inv in enumerate([1, 2]):
            out_name = f"{prefix}_run-{run}_inv-{inv}_part-{part_bids}_temp_MP2RAGE" if part_bids else f"{prefix}_run-{run}_inv-{inv}_MP2RAGE"
            out_nii = anat_dir / f"{out_name}.nii.gz"
            out_json = anat_dir / f"{out_name}.json"
            try:
                img = nib.Nifti1Image(data[..., i], nii.affine, nii.header)
                nib.save(img, out_nii)
                meta = dict(json_dict)
                meta["dcmmeta_shape"] = list(data[..., i].shape)
                if part_bids:
                    meta["part"] = part_bids
                with open(out_json, "w") as f:
                    json.dump(meta, f, indent=2)
                logger.info(f"  Created: {out_nii.name}")
                if not part_bids:
                    new_rels.append(f"anat/{out_nii.name}")
            except Exception as e:
                logger.warning(f"Failed to create {out_name}: {e}")
        if new_rels:
            sess.replace_in_scans_tsv(f"anat/{fname}", new_rels)


def _compute_mag_phase(anat_dir, sess, logger, run):
    prefix = sess.subses_prefix
    for inv in [1, 2]:
        real_f = anat_dir / f"{prefix}_run-{run}_inv-{inv}_part-real_temp_MP2RAGE.nii.gz"
        imag_f = anat_dir / f"{prefix}_run-{run}_inv-{inv}_part-imag_temp_MP2RAGE.nii.gz"
        if not real_f.exists() or not imag_f.exists():
            continue
        logger.info(f"Computing mag/phase for inv-{inv}")
        try:
            nii_r = nib.load(real_f)
            nii_i = nib.load(imag_f)
            rd, id_ = nii_r.get_fdata(), nii_i.get_fdata()
        except Exception as e:
            logger.warning(f"Could not load files for inv-{inv}: {e}")
            continue
        if rd.shape != id_.shape:
            logger.error(f"Shape mismatch inv-{inv}")
            continue
        mag = np.sqrt(rd**2 + id_**2)
        phase = np.arctan2(id_, rd)
        real_json = real_f.with_suffix("").with_suffix(".json")
        base_meta = {}
        if real_json.exists():
            try:
                with open(real_json) as f:
                    base_meta = json.load(f)
            except Exception:
                pass
        inv_entry = sess.get_scans_entry(f"anat/{prefix}_run-{run}_inv-{inv}_MP2RAGE.nii.gz")
        inherited = {k: v for k, v in (inv_entry or {}).items() if k != "filename"}
        for part, d in [("mag", mag), ("phase", phase)]:
            out_name = f"{prefix}_run-{run}_inv-{inv}_part-{part}_MP2RAGE"
            out_nii = anat_dir / f"{out_name}.nii.gz"
            out_json = anat_dir / f"{out_name}.json"
            try:
                nib.save(nib.Nifti1Image(d, nii_r.affine, nii_r.header), out_nii)
                m = dict(base_meta)
                m["dcmmeta_shape"] = list(d.shape)
                m["part"] = part
                with open(out_json, "w") as f:
                    json.dump(m, f, indent=2)
                logger.info(f"  Created: {out_nii.name}")
                sess.add_to_scans_tsv(f"anat/{out_nii.name}", **(inherited or {}))
            except Exception as e:
                logger.warning(f"Failed: {out_name}: {e}")


def _reshape_unit1(anat_dir, sess, logger, run):
    prefix = sess.subses_prefix
    t1w = anat_dir / f"{prefix}_acq-mp2rage_run-{run}_T1w.nii.gz"
    if not t1w.exists():
        return
    try:
        nii = nib.load(t1w)
        data = nii.get_fdata()
    except Exception:
        return
    if data.ndim == 4 and 1 in data.shape:
        logger.info(f"Reshaping T1w from {data.shape} to 3D")
        new_data = data.squeeze()
        new_nii = nib.Nifti1Image(new_data, nii.affine)
        new_nii.header.set_xyzt_units(*nii.header.get_xyzt_units())
        tmp = anat_dir / ".t1w_tmp.nii.gz"
        nib.save(new_nii, tmp)
        tmp.replace(t1w)
        logger.info(f"  Reshaped: {t1w.name}")


def _remove_combined_files(anat_dir, sess, logger):
    for f in anat_dir.glob(f"{sess.subses_prefix}_*inv-1and2_*"):
        f.unlink()
        logger.info(f"Removed combined: {f.name}")


def _remove_temp_files(anat_dir, sess, logger):
    for f in anat_dir.glob(f"{sess.subses_prefix}_*_temp_MP2RAGE*"):
        f.unlink()
        logger.debug(f"Removed temp: {f.name}")
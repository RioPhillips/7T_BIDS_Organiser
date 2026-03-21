"""
fixanat command. Handles the anatomical files (MP2RAGE processing).

Works with dcm2niix output patterns (e.g. _real, _imaginary suffixes),
splits combined inv-1and2 files, computes mag/phase from real/imag,
reshapes UNIT1, injects MP2RAGE metadata.

The thought is that dcm2niix figures out which is real/imaginary well. 
This should probably be checked for consitency. 

"""

import re
import json
from pathlib import Path
from typing import List, Set, Optional, Dict, Any, Tuple

import numpy as np
import nibabel as nib

from bids7t.core import Session, setup_logging, check_outputs_exist
from bids7t.core.session import load_mp2rage_params


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
    
    # normalize MP2RAGE1/2/3 naming
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
        
        #  split combined inv-1and2 files
        # looks at dcm2niix suffixes (_real, _imaginary) 
        _split_inv_files(anat_dir, sess, logger, run)
        
        # computes magnitude/phase from real+imag pairs
        _compute_mag_phase(anat_dir, sess, logger, run)
        
        # reshape UNIT1 (T1w) if it has dummy dimensions
        _reshape_unit1(anat_dir, sess, logger, run)
        
        # inject the MP2RAGE-specific BIDS metadata
        if mp2rage_params:
            _inject_mp2rage_metadata(anat_dir, sess, logger, mp2rage_params, run)

    # removes combined originals and temp 
    _remove_combined_files(anat_dir, sess, logger)
    _remove_temp_files(anat_dir, sess, logger)
    sess.sync_scans_tsv(remove_missing=True, add_new=False)
    logger.info("Anatomical fixes complete")



def _discover_inv_files(anat_dir: Path, prefix: str, run: int
                        ) -> Dict[str, List[Path]]:
    """
    Seacrh for inv-1and2 MP2RAGE files by scanning the directory.
    
    dcm2niix may add suffixes like _real, _imaginary, _magnitude, _phase
    to the BIDS names. 
    
    Returns dict with keys 'real', 'imaginary', 'magnitude', 'other'
    where each value is a list of NIfTI paths.
    """
    run_pattern = f"run-{run}"
    
    found = {"real": [], "imaginary": [], "magnitude": [], "other": []}
    
    for f in sorted(anat_dir.glob("*.nii.gz")):
        # must have inv-1and2 and MP2RAGE and the correct run
        if "inv-1and2" not in f.name:
            continue
        if "MP2RAGE" not in f.name:
            continue
        if run_pattern not in f.name:
            continue
        
        # map by dcm2niix suffix (check before .nii.gz)
        stem = f.name.replace(".nii.gz", "")
        
        if stem.endswith("_real"):
            found["real"].append(f)
        elif stem.endswith("_imaginary"):
            found["imaginary"].append(f)
        elif stem.endswith("_magnitude"):
            found["magnitude"].append(f)
        elif stem.endswith("_phase"):
            found["magnitude"].append(f) 
        else:
            found["other"].append(f)
    
    return found


def _split_inv_files(anat_dir: Path, sess: Session, logger, run: int) -> None:
    """
    Split combined inv-1and2 files into separate inv-1/inv-2 files.
    
    Search files using dcm2niix suffixes. Currently tuned for:
    
    1. dcm2niix _real/_imaginary suffixes (e.g. *_MP2RAGE_real.nii.gz)
       -> split into inv-1/inv-2, tagged as real/imag temps for mag/phase
    
    2. Clean combined files (e.g. *_inv-1and2_MP2RAGE.nii.gz)
       -> split into inv-1/inv-2 magnitude files
    
    3. Files with user-specified part entities that also got dcm2niix suffixes
       (e.g. *_part-real_MP2RAGE_real.nii.gz) -> same as case 1
    """
    prefix = sess.subses_prefix
    discovered = _discover_inv_files(anat_dir, prefix, run)
    
    # logs
    for category, files in discovered.items():
        if files:
            logger.info(f"  Found {category}: {[f.name for f in files]}")
    
    has_real = len(discovered["real"]) > 0
    has_imag = len(discovered["imaginary"]) > 0
    
    # real files (dcm2niix _real suffix)
    for nii_path in discovered["real"]:
        _split_4d_inv(anat_dir, nii_path, sess, logger, run, part_label="real")
    
    # imaginary files (dcm2niix _imaginary suffix)
    for nii_path in discovered["imaginary"]:
        _split_4d_inv(anat_dir, nii_path, sess, logger, run, part_label="imag")
    
    # other/clean inv-1and2 files (without dcm2niix suffix)
    for nii_path in discovered["other"]:
        _split_4d_inv(anat_dir, nii_path, sess, logger, run, part_label=None)
    
    # removes magnitude duplicates if we already have real+imag
    # (the magnitude is redundant when we compute it from real+imag)
    if has_real and has_imag:
        for nii_path in discovered["magnitude"]:
            logger.info(f"  Removing redundant magnitude (have real+imag): {nii_path.name}")
            json_path = nii_path.with_suffix("").with_suffix(".json")
            sess.remove_from_scans_tsv(f"anat/{nii_path.name}")
            nii_path.unlink()
            if json_path.exists():
                json_path.unlink()


def _split_4d_inv(anat_dir: Path, nii_path: Path, sess: Session, 
                   logger, run: int, part_label: Optional[str]) -> None:
    """
    Split a single 4D inv-1and2 file into two 3D inv files.
    
    Parameters
    ----------
    part_label : str or None
        'real' or 'imag' -> creates _temp_ intermediates for mag/phase computation
        None -> creates final inv-1/inv-2 magnitude files directly
    """
    prefix = sess.subses_prefix
    
    logger.info(f"  Splitting: {nii_path.name}")
    try:
        nii = nib.load(nii_path)
        data = nii.get_fdata()
    except Exception as e:
        logger.warning(f"Could not load {nii_path.name}: {e}")
        return
    
    # search for the JSON sidecar (trying to find the matching .json regardless of dcm2niix suffix)
    json_path = nii_path.with_suffix("").with_suffix(".json")
    json_dict = {}
    if json_path.exists():
        try:
            with open(json_path) as f:
                json_dict = json.load(f)
        except Exception:
            pass
    
    if data.ndim != 4 or data.shape[-1] != 2:
        logger.warning(f"Unexpected shape {data.shape} for {nii_path.name}, expected 4D with 2 volumes")
        return
    
    new_rels = []
    for i, inv in enumerate([1, 2]):
        if part_label:
            # temp file for mag/phase computation
            out_name = f"{prefix}_run-{run}_inv-{inv}_part-{part_label}_temp_MP2RAGE"
        else:
            # final inv file (magnitude)
            out_name = f"{prefix}_run-{run}_inv-{inv}_MP2RAGE"
        
        out_nii = anat_dir / f"{out_name}.nii.gz"
        out_json = anat_dir / f"{out_name}.json"
        
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
    
    # updates scans.tsv for non-temp files
    if new_rels:
        sess.replace_in_scans_tsv(f"anat/{nii_path.name}", new_rels)


# computes magnitude/phase from real+imaginary pairs

def _compute_mag_phase(anat_dir: Path, sess: Session, logger, run: int) -> None:
    prefix = sess.subses_prefix
    
    for inv in [1, 2]:
        real_f = anat_dir / f"{prefix}_run-{run}_inv-{inv}_part-real_temp_MP2RAGE.nii.gz"
        imag_f = anat_dir / f"{prefix}_run-{run}_inv-{inv}_part-imag_temp_MP2RAGE.nii.gz"
        
        if not real_f.exists() or not imag_f.exists():
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
            logger.error(f"Shape mismatch inv-{inv}: real={rd.shape}, imag={id_.shape}")
            continue
        
        mag = np.sqrt(rd**2 + id_**2)
        phase = np.arctan2(id_, rd)
        
        # base metadata from real JSON
        real_json = real_f.with_suffix("").with_suffix(".json")
        base_meta = {}
        if real_json.exists():
            try:
                with open(real_json) as f:
                    base_meta = json.load(f)
            except Exception:
                pass
        
        # give scans.tsv the metadata from the unsplit inv file
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
                logger.info(f"    Created: {out_nii.name}")
                sess.add_to_scans_tsv(f"anat/{out_nii.name}", **(inherited or {}))
            except Exception as e:
                logger.warning(f"Failed: {out_name}: {e}")


# MP2RAGE metadata

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


# helpers

def _normalize_mp2rage_names(anat_dir, sess, logger):
    # handles older heudiconv MP2RAGE1/2/3 patterns
    # probably redundant but keeping it for now
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
        mappings = {
            "1": f"{base}_MP2RAGE",
            "2": f"{base}_part-real_MP2RAGE",
            "3": f"{base}_part-imag_MP2RAGE",
        }
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
        logger.info(f"  Reshaping T1w from {data.shape} to 3D")
        new_data = data.squeeze()
        new_nii = nib.Nifti1Image(new_data, nii.affine)
        new_nii.header.set_xyzt_units(*nii.header.get_xyzt_units())
        tmp = anat_dir / ".t1w_tmp.nii.gz"
        nib.save(new_nii, tmp)
        tmp.replace(t1w)
        logger.info(f"  Reshaped: {t1w.name}")


def _remove_combined_files(anat_dir, sess, logger):
    # remove original combined inv-1and2 files (including any dcm2niix suffixes
    for f in sorted(anat_dir.glob("*inv-1and2*")):
        f.unlink()
        logger.info(f"Removed combined: {f.name}")


def _remove_temp_files(anat_dir, sess, logger):
    for f in sorted(anat_dir.glob("*_temp_MP2RAGE*")):
        f.unlink()
        logger.debug(f"Removed temp: {f.name}")
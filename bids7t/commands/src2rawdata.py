"""
src2rawdata command. converts sourcedata to BIDS rawdata using dcm2niix.

Reads series mapping rules from code/bids7t.yaml to determine how each
DICOM series directory maps to BIDS output. 

"""

import re
import json
import shutil
import subprocess
from pathlib import Path
from collections import defaultdict
from typing import Optional, List, Dict, Any

import pydicom

from bids7t.core import Session, setup_logging, check_outputs_exist, load_config, get_series_mapping


def run_src2rawdata(
    studydir: Path,
    subject: str,
    session: Optional[str] = None,
    force: bool = False,
    verbose: bool = False
) -> List[Path]:
    """
    Convert sourcedata to BIDS rawdata using dcm2niix directly.
    
    Reads series mapping rules from code/bids7t.yaml.
    
    Parameters
    ----------
    studydir : Path
        Path to BIDS study directory
    subject : str
        Subject ID (without sub- prefix)
    session : str or None
        Session ID (without ses- prefix). None for single-session studies.
    force : bool
        Force overwrite existing files
    verbose : bool
        Enable verbose output
        
    Returns
    -------
    list
        List of created NIfTI files
    """
    sess = Session(studydir, subject, session)
    log_file = sess.paths["logs"] / "src2rawdata.log"
    logger = setup_logging("src2rawdata", log_file, verbose)
    
    session_label = f"_ses-{session}" if session else ""
    logger.info(f"Starting conversion for sub-{subject}{session_label}")
    
    # load series mapping from bids7t.yaml
    config = load_config(studydir)
    series_rules = get_series_mapping(studydir, config)
    
    if not series_rules:
        raise ValueError(
            f"No series mapping found in code/bids7t.yaml.\n"
            f"Add a 'series:' section with mapping rules."
        )
    
    logger.info(f"Loaded {len(series_rules)} series mapping rules")
    
    # check sourcedata exists
    sourcedata = sess.paths["sourcedata"]
    if not sourcedata.exists() or not any(sourcedata.iterdir()):
        raise FileNotFoundError(
            f"Sourcedata not found or empty: {sourcedata}\n"
            f"Run 'bids7t dcm2src' first."
        )
    
    # check existing output
    rawdata = sess.paths["rawdata"]
    if rawdata.exists():
        existing_niftis = list(rawdata.rglob("*.nii.gz"))
        if existing_niftis:
            should_run, _ = check_outputs_exist(existing_niftis[:1], logger, force)
            if not should_run:
                return existing_niftis
            if force:
                logger.info(f"Removing existing rawdata: {rawdata}")
                shutil.rmtree(rawdata)
    
    sess.ensure_directories("rawdata", "logs")
    
    # get all series directories
    series_dirs = sorted([
        d for d in sourcedata.iterdir()
        if d.is_dir() and not d.name.startswith(".")
    ])
    
    logger.info(f"Found {len(series_dirs)} series directories in sourcedata")
    
    # match and convert
    run_counters: Dict[str, int] = defaultdict(int)
    converted_count = 0
    skipped_dirs = []
    
    for series_dir in series_dirs:
        rule = _match_series(series_dir, series_rules, logger)
        
        if rule is None:
            skipped_dirs.append(series_dir.name)
            continue
        
        # determine run number
        run_key = _run_key(rule)
        run_counters[run_key] += 1
        run_num = run_counters[run_key]
        
        # convert
        created = _convert_series(
            series_dir=series_dir,
            rule=rule,
            sess=sess,
            run_num=run_num,
            logger=logger
        )
        
        if created:
            converted_count += len(created)
    
    if skipped_dirs:
        logger.info(f"Skipped {len(skipped_dirs)} unmatched series:")
        for name in skipped_dirs:
            logger.debug(f"  - {name}")
    
    # post-conversion cleanup
    _remove_adc_files(sess, logger)
    
    # post-conversion metadata
    _update_participants_tsv(sess, logger)
    _create_scans_json(sess, logger)
    _create_task_jsons(sess, logger)
    
    all_niftis = list(rawdata.rglob("*.nii.gz"))
    logger.info(f"Conversion complete: {len(all_niftis)} NIfTI files created")
    
    return all_niftis


def _match_series(series_dir: Path, rules: List[Dict], logger) -> Optional[Dict]:
    """
    Match a sourcedata series directory against the mapping rules.
    
    Returns the first matching rule, or None if no match.
    """
    dirname = series_dir.name
    
    for rule in rules:
        match_spec = rule["match"]
        
        # dir_pattern: regex match on directory name
        if "dir_pattern" in match_spec:
            pattern = match_spec["dir_pattern"]
            if not re.search(pattern, dirname, re.IGNORECASE):
                continue
        
        # exclude_derived: check DICOM ImageType
        if match_spec.get("exclude_derived", False):
            if _is_derived(series_dir):
                continue
        
        # require_derived: only match derived series
        if match_spec.get("require_derived", False):
            if not _is_derived(series_dir):
                continue
        
        # dicom_field: check specific DICOM fields
        if "dicom_field" in match_spec:
            if not _check_dicom_fields(series_dir, match_spec["dicom_field"]):
                continue
        
        rule_name = rule.get("name", rule["suffix"])
        logger.debug(f"Matched: {dirname} -> {rule_name}")
        return rule
    
    return None


def _is_derived(series_dir: Path) -> bool:
    # checks if series is derived by reading one DICOM
    dcm_file = _get_first_dicom(series_dir)
    if dcm_file is None:
        return False
    try:
        ds = pydicom.dcmread(str(dcm_file), stop_before_pixels=True)
        image_type = getattr(ds, 'ImageType', [])
        return 'DERIVED' in image_type
    except Exception:
        return False


def _check_dicom_fields(series_dir: Path, field_checks: Dict[str, str]) -> bool:
    # checks specific DICOM fields against expected values
    dcm_file = _get_first_dicom(series_dir)
    if dcm_file is None:
        return False
    try:
        ds = pydicom.dcmread(str(dcm_file), stop_before_pixels=True)
        for field, expected in field_checks.items():
            val = str(getattr(ds, field, ""))
            if not re.search(expected, val, re.IGNORECASE):
                return False
        return True
    except Exception:
        return False


def _get_first_dicom(series_dir: Path) -> Optional[Path]:
    # get the first DICOM file from a series directory
    dcm_files = list(series_dir.glob("*.dcm")) + list(series_dir.glob("*.DCM"))
    if dcm_files:
        return sorted(dcm_files)[0]
    
    # try files without extension
    for f in sorted(series_dir.iterdir()):
        if f.is_file() and not f.name.startswith("."):
            return f
    return None


def _run_key(rule: Dict) -> str:
    """
    Generate a key for run numbering.
    
    Files with the same target + suffix + non-run entities share a run counter.
    """
    entities = rule.get("entities", {})
    parts = [rule["target"], rule["suffix"]]
    
    # include all entities except run in the key
    for k, v in sorted(entities.items()):
        if k != "run":
            parts.append(f"{k}-{v}")
    
    return "/".join(parts)


def _build_bids_name(prefix: str, rule: Dict, run_num: int) -> str:
    # build the BIDS filename from prefix, rule, and run number
    parts = [prefix]
    
    entities = rule.get("entities", {})
    entity_order = ['task', 'acq', 'ce', 'rec', 'dir', 'run', 'echo', 'flip', 'inv', 'part']
    
    for entity in entity_order:
        if entity in entities:
            val = entities[entity]
            parts.append(f"{entity}-{val}")
        elif entity == "run":
            parts.append(f"run-{run_num}")
    
    parts.append(rule["suffix"])
    return "_".join(parts)


def _convert_series(
    series_dir: Path,
    rule: Dict,
    sess: Session,
    run_num: int,
    logger
) -> List[Path]:
    """
    Converts a single DICOM series directory to BIDS NIfTI.
    
    Returns list of created files.
    """
    target = rule["target"]
    output_dir = sess.paths[target]
    output_dir.mkdir(parents=True, exist_ok=True)
    
    bids_name = _build_bids_name(sess.subses_prefix, rule, run_num)
    
    rule_name = rule.get("name", rule["suffix"])
    logger.info(f"Converting: {series_dir.name} -> {target}/{bids_name}")
    
    # build dcm2niix command
    extra_flags = rule.get("dcm2niix_flags", [])
    
    cmd = [
        "dcm2niix",
        "-b", "y",         # BIDS sidecar JSON
        "-z", "y",         # compress to .nii.gz
        "-f", bids_name,   # output filename
        "-o", str(output_dir),
        *extra_flags,       # per-series flags (e.g. -p n for B1)
        str(series_dir)
    ]
    
    logger.debug(f"  cmd: {' '.join(cmd)}")
    
    result = subprocess.run(cmd, capture_output=True, text=True)
    
    if result.returncode != 0:
        logger.warning(f"dcm2niix returned code {result.returncode} for {series_dir.name}")
        if result.stderr:
            logger.warning(f"  stderr: {result.stderr[:200]}")
        # some series legitimately produce warnings so dont want to crash if that is the case
    
    if result.stdout and logger.level <= 10:
        for line in result.stdout.splitlines()[:10]:
            logger.debug(f"  dcm2niix: {line}")
    
    # find created files
    created_niftis = sorted(output_dir.glob(f"{bids_name}*.nii.gz"))
    created_jsons = sorted(output_dir.glob(f"{bids_name}*.json"))
    
    if not created_niftis:
        logger.warning(f"No NIfTI files created for {series_dir.name}")
        # check if dcm2niix used different naming
        all_new = sorted(output_dir.glob(f"*.nii.gz"))
        if all_new:
            logger.warning(f"  Found {len(all_new)} total NIfTI files in {target}/")
        return []
    
    logger.info(f"  Created {len(created_niftis)} NIfTI + {len(created_jsons)} JSON")
    
    # inject SkullStripped: false into all JSON sidecars at creation time
    # raw scanner data is is probably not skull-stripped but BIDS requires this field.
    # the user should change the specific files in the case that it is
    for json_file in created_jsons:
        try:
            with open(json_file) as f:
                meta = json.load(f)
            meta["SkullStripped"] = False
            with open(json_file, "w") as f:
                json.dump(meta, f, indent=4)
        except Exception:
            pass  
    
    # register in scans.tsv
    for nii_file in created_niftis:
        rel_path = f"{target}/{nii_file.name}"
        acq_time = _get_acq_time(nii_file, sess)
        sess.add_to_scans_tsv(rel_path, acq_time=acq_time)
    
    return created_niftis + created_jsons


def _get_acq_time(nii_file: Path, sess: Session) -> str:
    # get acquisition time from JSON sidecar
    try:
        meta = sess.get_json(nii_file)
        
        if "AcquisitionDateTime" in meta:
            return meta["AcquisitionDateTime"]
        
        if "AcquisitionDate" in meta and "AcquisitionTime" in meta:
            date = meta["AcquisitionDate"]
            time = meta["AcquisitionTime"]
            if len(date) == 8:
                date = f"{date[:4]}-{date[4:6]}-{date[6:8]}"
            if ":" not in time and len(time) >= 6:
                time = f"{time[:2]}:{time[2:4]}:{time[4:]}"
            return f"{date}T{time}"
        
        if "AcquisitionTime" in meta:
            time = meta["AcquisitionTime"]
            if ":" not in time and len(time) >= 6:
                time = f"{time[:2]}:{time[2:4]}:{time[4:]}"
            return f"T{time}"
    except Exception:
        pass
    return "n/a"


def _remove_adc_files(sess: Session, logger) -> None:
    """
    Remove redundant ADC files from dwi directory.
    
    dcm2niix sometimes generate ADC maps from
    DWI data. These are not used to my knowledge.
    """
    dwi_dir = sess.paths["dwi"]
    if not dwi_dir.exists():
        return
    
    for adc_file in sorted(dwi_dir.glob("*_ADC*")):
        logger.info(f"Removing ADC file: {adc_file.name}")
        if adc_file.suffix == ".gz" or adc_file.name.endswith(".nii.gz"):
            sess.remove_from_scans_tsv(f"dwi/{adc_file.name}")
        adc_file.unlink()


def _update_participants_tsv(sess: Session, logger) -> None:
    """
    Add/update this subject's entry in participants.tsv.
    
    Reads age and sex from the first DICOM found in sourcedata.
    Creates the file with header if it doesn't exist.
    """
    rawdata_root = sess.paths["rawdata_root"]
    ptsv = rawdata_root / "participants.tsv"
    participant_id = sess.sub_prefix  
    
    # read existing entries
    existing_ids = set()
    rows = []
    if ptsv.exists():
        with open(ptsv) as f:
            lines = f.read().strip().split("\n")
        if len(lines) > 1:
            for line in lines[1:]:
                parts = line.split("\t")
                if parts:
                    existing_ids.add(parts[0])
                    rows.append(line)
    
    if participant_id in existing_ids:
        logger.debug(f"Participant {participant_id} already in participants.tsv")
        return
    
    # extract age and sex from DICOM
    age, sex = _read_participant_info(sess, logger)
    
    new_row = f"{participant_id}\t{age}\t{sex}\tcontrol"
    rows.append(new_row)
    
    with open(ptsv, "w") as f:
        f.write("participant_id\tage\tsex\tgroup\n")
        for row in rows:
            f.write(row + "\n")
    
    logger.info(f"Added {participant_id} to participants.tsv (age={age}, sex={sex})")


def _read_participant_info(sess: Session, logger) -> tuple:
    """
    Read age and sex from the first DICOM in sourcedata.
    
    Returns (age_str, sex_str) — "n/a" if not available.
    """
    sourcedata = sess.paths["sourcedata"]
    
    # find first DICOM
    dcm_file = None
    for series_dir in sorted(sourcedata.iterdir()):
        if not series_dir.is_dir():
            continue
        dcm_files = list(series_dir.glob("*.dcm")) + list(series_dir.glob("*.DCM"))
        if dcm_files:
            dcm_file = sorted(dcm_files)[0]
            break
    
    if dcm_file is None:
        logger.debug("No DICOM files found for participant info")
        return "n/a", "n/a"
    
    try:
        ds = pydicom.dcmread(str(dcm_file), stop_before_pixels=True)
        
        # age: DICOM tag (0010,1010) PatientAge — format like "025Y"
        age_str = "n/a"
        if hasattr(ds, 'PatientAge') and ds.PatientAge:
            raw_age = str(ds.PatientAge).strip()
            # extract numeric part (e.g. "025Y" -> "25")
            digits = ''.join(c for c in raw_age if c.isdigit())
            if digits:
                age_str = str(int(digits))
        
        # sex: DICOM tag (0010,0040) PatientSex — "M", "F", or "O"
        sex_str = "n/a"
        if hasattr(ds, 'PatientSex') and ds.PatientSex:
            sex_str = str(ds.PatientSex).strip().upper()
            if sex_str not in ("M", "F"):
                sex_str = "n/a"
        
        return age_str, sex_str
        
    except Exception as e:
        logger.debug(f"Could not read participant info from DICOM: {e}")
        return "n/a", "n/a"


def _create_scans_json(sess: Session, logger) -> None:
    """
    Create scans.json alongside scans.tsv (describes columns).
    """
    from bids7t.commands.init import SCANS_JSON_TEMPLATE
    
    scans_json = sess.scans_tsv.with_suffix(".json")
    if scans_json.exists():
        return
    
    with open(scans_json, "w") as f:
        json.dump(SCANS_JSON_TEMPLATE, f, indent=2)
    logger.info(f"Created {scans_json.name}")


def _create_task_jsons(sess: Session, logger) -> None:
    """
    Create top-level task-{name}_bold.json files for each task found.
    
    BIDS requires a task JSON at the top level of rawdata/ for each
    unique task. This provides the TaskName field and any shared metadata.
    """
    rawdata_root = sess.paths["rawdata_root"]
    func_dir = sess.paths["func"]
    
    if not func_dir.exists():
        return
    
    # find unique task names from bold files
    import re
    tasks = set()
    for bold_file in func_dir.glob("*_bold.nii.gz"):
        m = re.search(r"_task-([^_]+)_", bold_file.name)
        if m:
            tasks.add(m.group(1))
    
    for task in sorted(tasks):
        task_json = rawdata_root / f"task-{task}_bold.json"
        if task_json.exists():
            logger.debug(f"Task JSON already exists: {task_json.name}")
            continue
        
        task_meta = {
            "TaskName": f"TODO: full task name for {task}",
            "CogAtlasID": "http://www.cognitiveatlas.org/task/id/TODO"
        }
        
        with open(task_json, "w") as f:
            json.dump(task_meta, f, indent=2)
        logger.info(f"Created {task_json.name}")
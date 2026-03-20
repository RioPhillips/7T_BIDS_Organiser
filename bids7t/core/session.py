"""
Session class for managing subject/session paths and file operations.
Config loading from code/bids7t.yaml (single file for everything).
"""

from pathlib import Path
import json
import yaml
import logging
import stat
import csv
from typing import Optional, Dict, Any, List

logger = logging.getLogger(__name__)

_CONFIG_FILENAME = "bids7t.yaml"


class Session:
    """
    Represents a single subject/session combination in a BIDS study.
    When session is None, paths and prefixes omit the ses- level.
    """
    
    def __init__(self, studydir: Path, subject: str,
                 session: Optional[str] = None, dicom_dir: Optional[Path] = None):
        self.studydir = Path(studydir)
        self.subject = subject
        self.session = session
        self.dicom_dir = Path(dicom_dir) if dicom_dir else None
        self.has_session = session is not None
        
        self.sub_prefix = f"sub-{subject}"
        if self.has_session:
            self.ses_prefix = f"ses-{session}"
            self.subses_prefix = f"sub-{subject}_ses-{session}"
        else:
            self.ses_prefix = None
            self.subses_prefix = f"sub-{subject}"
        
        self.paths = self._init_paths()
    
    def _init_paths(self) -> Dict[str, Path]:
        base = self.studydir
        if self.has_session:
            rd = base / "rawdata" / self.sub_prefix / self.ses_prefix
            sd = base / "sourcedata" / self.sub_prefix / self.ses_prefix
            ld = base / "derivatives" / "logs" / self.sub_prefix / self.ses_prefix
        else:
            rd = base / "rawdata" / self.sub_prefix
            sd = base / "sourcedata" / self.sub_prefix
            ld = base / "derivatives" / "logs" / self.sub_prefix
        return {
            "rawdata": rd, "rawdata_subject": base / "rawdata" / self.sub_prefix,
            "rawdata_root": base / "rawdata", "sourcedata": sd,
            "anat": rd / "anat", "func": rd / "func", "fmap": rd / "fmap", "dwi": rd / "dwi",
            "derivatives": base / "derivatives", "logs": ld, "code": base / "code",
            "dicom": self.dicom_dir if self.dicom_dir else base / "dicom",
        }
    
    @property
    def scans_tsv(self) -> Path:
        return self.paths["rawdata"] / f"{self.subses_prefix}_scans.tsv"
    
    def ensure_directories(self, *keys: str) -> None:
        if not keys:
            keys = ("rawdata", "sourcedata", "logs", "code")
        for key in keys:
            if key in self.paths:
                self.paths[key].mkdir(parents=True, exist_ok=True)
    
    # --- file ops ---
    
    def get_json(self, path: Path) -> Dict[str, Any]:
        jp = self._to_json_path(path)
        if jp.exists():
            with open(jp) as f:
                return json.load(f)
        return {}
    
    def write_json(self, path: Path, data: Dict[str, Any]) -> None:
        jp = self._to_json_path(path)
        jp.parent.mkdir(parents=True, exist_ok=True)
        with open(jp, "w") as f:
            json.dump(data, f, indent=4)
    
    def _to_json_path(self, path: Path) -> Path:
        path = Path(path)
        if path.suffix == ".gz":
            return path.with_suffix("").with_suffix(".json")
        elif path.suffix == ".nii":
            return path.with_suffix(".json")
        return path
    
    def make_writable(self, path: Path) -> None:
        path = Path(path)
        if path.exists():
            path.chmod(path.stat().st_mode | stat.S_IWUSR)
    
    def make_readonly(self, path: Path) -> None:
        path = Path(path)
        if path.exists():
            path.chmod(path.stat().st_mode & ~stat.S_IWUSR)
    
    def remove_file(self, path: Path) -> bool:
        path = Path(path)
        if path.exists():
            path.unlink()
            return True
        return False
    
    def rename_file(self, src: Path, dst: Path) -> bool:
        src, dst = Path(src), Path(dst)
        if src.exists():
            dst.parent.mkdir(parents=True, exist_ok=True)
            src.rename(dst)
            return True
        return False
    
    def bids_name(self, suffix: str, **entities) -> str:
        parts = [self.subses_prefix]
        for e in ['task', 'acq', 'ce', 'rec', 'dir', 'run', 'echo', 'part', 'inv']:
            if e in entities:
                v = entities[e]
                if e == 'run' and isinstance(v, int):
                    v = str(v)
                parts.append(f"{e}-{v}")
        parts.append(suffix)
        return "_".join(parts)
    
    def rel_path(self, abs_path: Path) -> str:
        return str(Path(abs_path).relative_to(self.paths["rawdata"]))
    
    # --- scans.tsv ---
    
    def read_scans_tsv(self) -> tuple:
        if not self.scans_tsv.exists():
            return ["filename", "acq_time"], []
        with open(self.scans_tsv, newline="") as f:
            reader = csv.DictReader(f, delimiter="\t")
            fieldnames = reader.fieldnames or ["filename", "acq_time"]
            rows = list(reader)
        return list(fieldnames), rows
    
    def write_scans_tsv(self, fieldnames: list, rows: list) -> None:
        self.scans_tsv.parent.mkdir(parents=True, exist_ok=True)
        with open(self.scans_tsv, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, delimiter="\t",
                                     extrasaction='ignore')
            writer.writeheader()
            writer.writerows(rows)
    
    def add_to_scans_tsv(self, filename: str, acq_time: str = "n/a", **extra) -> None:
        fieldnames, rows = self.read_scans_tsv()
        for key in extra:
            if key not in fieldnames:
                fieldnames.append(key)
        for r in rows:
            if r.get("filename") == filename:
                return
        rows.append({"filename": filename, "acq_time": acq_time, **extra})
        self.write_scans_tsv(fieldnames, rows)
    
    def remove_from_scans_tsv(self, filename: str) -> bool:
        fieldnames, rows = self.read_scans_tsv()
        new_rows = [r for r in rows if r.get("filename") != filename]
        if len(new_rows) < len(rows):
            self.write_scans_tsv(fieldnames, new_rows)
            return True
        return False
    
    def rename_in_scans_tsv(self, old_filename: str, new_filename: str) -> bool:
        fieldnames, rows = self.read_scans_tsv()
        for row in rows:
            if row.get("filename") == old_filename:
                row["filename"] = new_filename
                self.write_scans_tsv(fieldnames, rows)
                return True
        return False
    
    def replace_in_scans_tsv(self, old_filename: str, new_filenames: list) -> bool:
        fieldnames, rows = self.read_scans_tsv()
        old_idx, old_entry = None, None
        for i, row in enumerate(rows):
            if row.get("filename") == old_filename:
                old_entry, old_idx = row.copy(), i
                break
        if old_entry is None:
            return False
        rows.pop(old_idx)
        for fn in new_filenames:
            nr = dict(old_entry)
            nr["filename"] = fn
            rows.insert(old_idx, nr)
            old_idx += 1
        self.write_scans_tsv(fieldnames, rows)
        return True
    
    def get_scans_entry(self, filename: str) -> Optional[Dict]:
        _, rows = self.read_scans_tsv()
        for row in rows:
            if row.get("filename") == filename:
                return row.copy()
        return None
    
    def sync_scans_tsv(self, remove_missing: bool = True, add_new: bool = False) -> dict:
        fieldnames, rows = self.read_scans_tsv()
        rawdata = self.paths["rawdata"]
        removed, added = [], []
        if remove_missing:
            new_rows = []
            for row in rows:
                if (rawdata / row.get("filename", "")).exists():
                    new_rows.append(row)
                else:
                    removed.append(row.get("filename"))
            rows = new_rows
        if add_new:
            existing = {r.get("filename") for r in rows}
            for mod in ["anat", "func", "fmap", "dwi"]:
                md = rawdata / mod
                if not md.exists():
                    continue
                for nii in md.glob("*.nii.gz"):
                    rel = f"{mod}/{nii.name}"
                    if rel not in existing:
                        rows.append({"filename": rel, "acq_time": "n/a"})
                        added.append(rel)
        if removed or added:
            self.write_scans_tsv(fieldnames, rows)
        return {"removed": removed, "added": added}


# ============================================================
# Config loading - single bids7t.yaml for everything
# ============================================================

def load_config(studydir: Path) -> Dict[str, Any]:
    """
    Load the study configuration from code/bids7t.yaml.
    
    This single YAML contains study settings, series mapping,
    and processing options all in one place.
    """
    config_path = Path(studydir) / "code" / _CONFIG_FILENAME
    if not config_path.exists():
        logger.warning(f"No {_CONFIG_FILENAME} found at {config_path}")
        return {}
    with open(config_path) as f:
        return yaml.safe_load(f) or {}


def get_series_mapping(studydir: Path, config: Optional[Dict] = None) -> Optional[List[Dict]]:
    """Get the 'series' list from bids7t.yaml."""
    if config is None:
        config = load_config(studydir)
    series = config.get("series")
    if series is None:
        logger.warning("No 'series' key found in bids7t.yaml")
    return series


def load_mp2rage_params(studydir: Path) -> Optional[Dict[str, Any]]:
    """
    Load MP2RAGE parameters from code/mp2rage.yaml.
    
    Kept separate from bids7t.yaml because these are
    scanner-specific acquisition parameters, not pipeline config.
    """
    mp2rage_path = Path(studydir) / "code" / "mp2rage.yaml"
    if not mp2rage_path.exists():
        logger.warning(f"No mp2rage.yaml found at {mp2rage_path}")
        return None
    try:
        with open(mp2rage_path) as f:
            params = yaml.safe_load(f)
        required = ["RepetitionTimeExcitation", "RepetitionTimePreparation",
                    "InversionTime", "NumberShots", "FlipAngle"]
        missing = [k for k in required if k not in params]
        if missing:
            logger.error(f"mp2rage.yaml missing: {missing}")
            return None
        for key in ["InversionTime", "FlipAngle"]:
            if not isinstance(params[key], list) or len(params[key]) != 2:
                logger.error(f"mp2rage.yaml: '{key}' must be [inv1, inv2]")
                return None
        return params
    except Exception as e:
        logger.error(f"Error loading mp2rage.yaml: {e}")
        return None


def detect_sessions(studydir: Path, subject: str) -> List[Optional[str]]:
    """
    Auto-detect sessions for a subject by examining directory structure.
    
    Checks sourcedata/ first (for dcm2src/src2rawdata), then rawdata/
    (for fix commands that run after conversion).
    
    Returns
    -------
    list
        - [None] if single-session (series dirs directly under sub-X/)
        - ["MR1", "MR2", ...] if multi-session (ses-* subdirs found)
        - [None] if no subject directory found at all (let commands
          handle the error downstream)
    """
    sub_prefix = f"sub-{subject}"
    
    # check sourcedata first, then rawdata
    for data_root in ["sourcedata", "rawdata"]:
        subject_dir = Path(studydir) / data_root / sub_prefix
        
        if not subject_dir.exists():
            continue
        
        # look for ses-* subdirectories
        ses_dirs = sorted([
            d for d in subject_dir.iterdir()
            if d.is_dir() and d.name.startswith("ses-")
        ])
        
        if ses_dirs:
            sessions = [d.name.replace("ses-", "") for d in ses_dirs]
            logger.info(
                f"Detected {len(sessions)} session(s) for {sub_prefix} "
                f"in {data_root}/: {sessions}"
            )
            return sessions
        
        # no ses-* dirs but directory has content — single session
        contents = [d for d in subject_dir.iterdir() if d.is_dir() and not d.name.startswith(".")]
        if contents:
            logger.info(f"Single-session layout detected for {sub_prefix} in {data_root}/")
            return [None]
    
    # nothing found — return [None] and let the command fail with a clear error
    logger.debug(f"No sourcedata or rawdata found for {sub_prefix}")
    return [None]
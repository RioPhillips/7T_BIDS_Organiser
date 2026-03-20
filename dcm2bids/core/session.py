"""
Session class for managing subject/session paths and file operations.
"""

from pathlib import Path
import json
import logging
import stat
import csv
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)


class Session:
    """
    Represents a single subject/session combination in a BIDS study.
    
    Handles path resolution, file I/O, and BIDS naming conventions.
    
    When session is None, paths and prefixes omit the ses- level entirely,
    producing a flat subject-level layout (e.g. rawdata/sub-X/anat/).
    """
    
    def __init__(
        self,
        studydir: Path,
        subject: str,
        session: Optional[str] = None,
        dicom_dir: Optional[Path] = None
    ):
        """
        Initialize a Session.
        
        Parameters
        ----------
        studydir : Path
            Root directory of the BIDS study
        subject : str
            Subject ID (without 'sub-' prefix)
        session : str or None
            Session ID (without 'ses-' prefix). If None, no session level.
        dicom_dir : Path, optional
            Path to source DICOM directory
        """
        self.studydir = Path(studydir)
        self.subject = subject
        self.session = session
        self.dicom_dir = Path(dicom_dir) if dicom_dir else None
        
        self.has_session = session is not None
        
        # BIDS prefixes
        self.sub_prefix = f"sub-{subject}"
        if self.has_session:
            self.ses_prefix = f"ses-{session}"
            self.subses_prefix = f"sub-{subject}_ses-{session}"
        else:
            self.ses_prefix = None
            self.subses_prefix = f"sub-{subject}"
        
        self.paths = self._init_paths()
    
    def _init_paths(self) -> Dict[str, Path]:
        # initializes all relevant paths for this session
        base = self.studydir
        
        if self.has_session:
            rawdata_session = base / "rawdata" / self.sub_prefix / self.ses_prefix
            sourcedata_session = base / "sourcedata" / self.sub_prefix / self.ses_prefix
            logs_session = base / "derivatives" / "logs" / self.sub_prefix / self.ses_prefix
        else:
            rawdata_session = base / "rawdata" / self.sub_prefix
            sourcedata_session = base / "sourcedata" / self.sub_prefix
            logs_session = base / "derivatives" / "logs" / self.sub_prefix
        
        return {
            #  BIDS directories
            "rawdata": rawdata_session,
            "rawdata_subject": base / "rawdata" / self.sub_prefix,
            "rawdata_root": base / "rawdata",
            "sourcedata": sourcedata_session,
            
            #  rawdata directories
            "anat": rawdata_session / "anat",
            "func": rawdata_session / "func",
            "fmap": rawdata_session / "fmap",
            "dwi": rawdata_session / "dwi",
            
            "derivatives": base / "derivatives",
            "logs": logs_session,
            
            "code": base / "code",
            
            # DICOM source (if provided)
            "dicom": self.dicom_dir if self.dicom_dir else base / "dicom",
        }
    
    @property
    def scans_tsv(self) -> Path:
        # path to the session's scans.tsv file
        return self.paths["rawdata"] / f"{self.subses_prefix}_scans.tsv"
    
    @property
    def scans_json(self) -> Path:
        # path to the session's scans.json file
        return self.paths["rawdata"] / f"{self.subses_prefix}_scans.json"
    
    def ensure_directories(self, *keys: str) -> None:
        """
        Create directories if they don't exist.
        
        Parameters
        ----------
        *keys : str
            Keys from self.paths to create. If empty, creates all.
        """
        if not keys:
            keys = ("rawdata", "sourcedata", "logs", "code")
        
        for key in keys:
            if key in self.paths:
                self.paths[key].mkdir(parents=True, exist_ok=True)
                logger.debug(f"Ensured directory: {self.paths[key]}")
    
    # file operations
    
    def get_json(self, path: Path) -> Dict[str, Any]:
        """
        Read a JSON sidecar file.
        
        Parameters
        ----------
        path : Path
            Path to JSON file or corresponding NIfTI file
            
        Returns
        -------
        dict
            Parsed JSON content, or empty dict if not found
        """
        json_path = self._to_json_path(path)
        if json_path.exists():
            with open(json_path) as f:
                return json.load(f)
        return {}
    
    def write_json(self, path: Path, data: Dict[str, Any]) -> None:
        """
        Write a JSON sidecar file.
        
        Parameters
        ----------
        path : Path
            Path to JSON file or corresponding NIfTI file
        data : dict
            Data to write
        """
        json_path = self._to_json_path(path)
        json_path.parent.mkdir(parents=True, exist_ok=True)
        with open(json_path, "w") as f:
            json.dump(data, f, indent=4)
        logger.debug(f"Wrote JSON: {json_path}")
    
    def _to_json_path(self, path: Path) -> Path:
        # convert a path to its JSON sidecar path
        path = Path(path)
        if path.suffix == ".gz":
            return path.with_suffix("").with_suffix(".json")
        elif path.suffix == ".nii":
            return path.with_suffix(".json")
        return path
    
    def make_writable(self, path: Path) -> None:
        # makes a file writable
        path = Path(path)
        if path.exists():
            path.chmod(path.stat().st_mode | stat.S_IWUSR)
    
    def make_readonly(self, path: Path) -> None:
        # makes a file read-only."""
        path = Path(path)
        if path.exists():
            path.chmod(path.stat().st_mode & ~stat.S_IWUSR)
    
    def remove_file(self, path: Path) -> bool:
        """
        Remove a file if it exists.
        
        Returns True if file was removed, False if it didn't exist.
        """
        path = Path(path)
        if path.exists():
            path.unlink()
            logger.debug(f"Removed: {path}")
            return True
        return False
    
    def rename_file(self, src: Path, dst: Path) -> bool:
        """
        Rename a file.
        
        Returns True if successful, False if source didn't exist.
        """
        src, dst = Path(src), Path(dst)
        if src.exists():
            dst.parent.mkdir(parents=True, exist_ok=True)
            src.rename(dst)
            logger.debug(f"Renamed: {src} -> {dst}")
            return True
        return False
    
    # BIDS naming helpers
    #
    def bids_name(self, suffix: str, **entities) -> str:
        """
        Generate a BIDS-compliant filename.
        
        Parameters
        ----------
        suffix : str
            BIDS suffix (e.g., 'T1w', 'bold', 'epi')
        **entities : str
            Additional BIDS entities (e.g., acq='mp2rage', run=1)
            
        Returns
        -------
        str
            BIDS filename (without extension)
        """
        parts = [self.subses_prefix]
        
        # entity order
        entity_order = ['task', 'acq', 'ce', 'rec', 'dir', 'run', 'echo', 'part', 'inv']
        
        for entity in entity_order:
            if entity in entities:
                val = entities[entity]
                if entity == 'run' and isinstance(val, int):
                    val = f"{val}"
                parts.append(f"{entity}-{val}")
        
        parts.append(suffix)
        return "_".join(parts)
    
    def rel_path(self, abs_path: Path) -> str:
        """
        Get path relative to rawdata directory (for scans.tsv).
        
        Parameters
        ----------
        abs_path : Path
            Absolute path to a file
            
        Returns
        -------
        str
            Path relative to session's rawdata directory
        """
        return str(Path(abs_path).relative_to(self.paths["rawdata"]))
    
    # Scans.tsv management
    
    def read_scans_tsv(self) -> tuple[list[str], list[dict]]:
        """
        Read the scans.tsv file.
        
        Returns
        -------
        tuple
            (fieldnames, rows) where rows is a list of dicts
        """
        if not self.scans_tsv.exists():
            return ["filename", "acq_time"], []
        
        with open(self.scans_tsv, newline='') as f:
            reader = csv.DictReader(f, delimiter='\t')
            fieldnames = reader.fieldnames or ["filename", "acq_time"]
            rows = list(reader)
        
        return list(fieldnames), rows
    
    def write_scans_tsv(self, fieldnames: list, rows: list) -> None:
        """Write the scans.tsv file."""
        self.make_writable(self.scans_tsv)
        
        with open(self.scans_tsv, 'w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, delimiter='\t',
                                     extrasaction='ignore')
            writer.writeheader()
            writer.writerows(rows)
        
        self.make_readonly(self.scans_tsv)
    
    def add_to_scans_tsv(self, filename: str, acq_time: str = "n/a", **kwargs) -> None:
        """
        Add a file entry to scans.tsv.
        
        Parameters
        ----------
        filename : str
            Relative path to file (e.g., 'anat/sub-X_T1w.nii.gz')
        acq_time : str
            Acquisition time
        **kwargs
            Additional columns
        """
        fieldnames, rows = self.read_scans_tsv()
        
        # add new columns if needed
        for key in kwargs:
            if key not in fieldnames:
                fieldnames.append(key)
        
        # check if already exists
        for row in rows:
            if row.get("filename") == filename:
                row["acq_time"] = acq_time
                row.update(kwargs)
                self.write_scans_tsv(fieldnames, rows)
                return
        
        # add new row
        new_row = {"filename": filename, "acq_time": acq_time}
        new_row.update(kwargs)
        rows.append(new_row)
        
        self.write_scans_tsv(fieldnames, rows)
    
    def remove_from_scans_tsv(self, filename: str) -> bool:
        """
        Remove a file entry from scans.tsv.
        
        Returns True if entry was found and removed.
        """
        fieldnames, rows = self.read_scans_tsv()
        
        new_rows = [r for r in rows if r.get("filename") != filename]
        
        if len(new_rows) < len(rows):
            self.write_scans_tsv(fieldnames, new_rows)
            return True
        return False
    
    def rename_in_scans_tsv(self, old_filename: str, new_filename: str) -> bool:
        """
        Rename a file entry in scans.tsv.
        
        Returns True if entry was found and renamed.
        """
        fieldnames, rows = self.read_scans_tsv()
        
        found = False
        for row in rows:
            if row.get("filename") == old_filename:
                row["filename"] = new_filename
                found = True
                break
        
        if found:
            self.write_scans_tsv(fieldnames, rows)
        return found
    
    def replace_in_scans_tsv(self, old_filename: str, new_filenames: list) -> bool:
        """
        Replace one entry with multiple entries in scans.tsv.
        
        The new entries inherit metadata from the old entry.
        
        Returns True if old entry was found and replaced.
        """
        fieldnames, rows = self.read_scans_tsv()
        
        # find old entry
        old_entry = None
        old_idx = None
        for i, row in enumerate(rows):
            if row.get("filename") == old_filename:
                old_entry = row.copy()
                old_idx = i
                break
        
        if old_entry is None:
            return False
        
        # create new entries inheriting metadata
        new_rows = []
        for new_fn in new_filenames:
            new_row = dict(old_entry)
            new_row["filename"] = new_fn
            new_rows.append(new_row)
        
        # replace
        rows[old_idx:old_idx + 1] = new_rows
        self.write_scans_tsv(fieldnames, rows)
        return True
    
    def get_scans_entry(self, filename: str) -> Optional[Dict]:
        """
        Get a specific entry from scans.tsv.
        
        Parameters
        ----------
        filename : str
            Relative path to file
            
        Returns
        -------
        dict or None
            The row dict if found, None otherwise
        """
        fieldnames, rows = self.read_scans_tsv()
        for row in rows:
            if row.get("filename") == filename:
                return row.copy()
        return None
    
    def sync_scans_tsv(self, remove_missing: bool = True, add_new: bool = False) -> dict:
        """
        Synchronize scans.tsv with actual files on disk.
        
        Parameters
        ----------
        remove_missing : bool
            Remove entries for files that no longer exist
        add_new : bool
            Add entries for new .nii.gz files not in scans.tsv
            
        Returns
        -------
        dict
            Summary with 'removed' and 'added' lists
        """
        fieldnames, rows = self.read_scans_tsv()
        rawdata = self.paths["rawdata"]
        
        removed = []
        added = []
        
        if remove_missing:
            # remove entries for non-existent files
            new_rows = []
            for row in rows:
                filepath = rawdata / row.get("filename", "")
                if filepath.exists():
                    new_rows.append(row)
                else:
                    removed.append(row.get("filename"))
                    logger.debug(f"Removing missing file from scans.tsv: {row.get('filename')}")
            rows = new_rows
        
        if add_new:
            # find .nii.gz files not in scans.tsv
            existing_filenames = {r.get("filename") for r in rows}
            
            for modality in ["anat", "func", "fmap", "dwi"]:
                mod_dir = rawdata / modality
                if not mod_dir.exists():
                    continue
                
                for nii_file in mod_dir.glob("*.nii.gz"):
                    rel_path = f"{modality}/{nii_file.name}"
                    if rel_path not in existing_filenames:
                        rows.append({
                            "filename": rel_path,
                            "acq_time": "n/a"
                        })
                        added.append(rel_path)
                        logger.debug(f"Adding new file to scans.tsv: {rel_path}")
        
        if removed or added:
            self.write_scans_tsv(fieldnames, rows)
        
        return {"removed": removed, "added": added}


def load_config(studydir: Path) -> Dict[str, Any]:
    """
    Load the study configuration from code/config.json.
    
    Parameters
    ----------
    studydir : Path
        Root directory of the BIDS study
        
    Returns
    -------
    dict
        Configuration dictionary
    """
    config_path = Path(studydir) / "code" / "config.json"
    if not config_path.exists():
        logger.warning(f"No config.json found at {config_path}")
        return {}
    
    with open(config_path) as f:
        return json.load(f)


def get_heuristic_path(studydir: Path, config: Optional[Dict] = None) -> Optional[Path]:
    """
    Get the heuristic file path from config.
    
    Parameters
    ----------
    studydir : Path
        Root directory of the BIDS study
    config : dict, optional
        Pre-loaded config dict
        
    Returns
    -------
    Path or None
        Path to heuristic file
    """
    if config is None:
        config = load_config(studydir)
    
    if "heuristic" in config:
        heuristic_path = Path(config["heuristic"])
        if not heuristic_path.is_absolute():
            heuristic_path = Path(studydir) / heuristic_path
        return heuristic_path
    
    # default location
    default_path = Path(studydir) / "code" / "heuristic.py"
    if default_path.exists():
        return default_path
    
    return None
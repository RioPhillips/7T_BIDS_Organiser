"""Core module for bids7t."""

from .session import Session, load_config, get_series_mapping, load_mp2rage_params, detect_sessions
from .utils import setup_logging, run_command, check_outputs_exist, find_files, get_docker_user_args
from .config import (
    resolve_studydir,
    load_study_config,
    get_studydir,
    find_config_from_cwd,
    find_studydir_from_cwd,
)
from .bids_naming import (
    parse_bids_name,
    build_bids_name,
    derive_bids_name,
    classify_dcm2niix_output,
    strip_dcm2niix_suffix,
    has_dcm2niix_suffix,
    entities_match,
    BIDS_ENTITY_ORDER,
    BIDS_SUFFIXES,
)

__all__ = [
    # Session
    "Session",
    "load_config",
    "get_series_mapping",
    "load_mp2rage_params",
    "detect_sessions",
    # Utils
    "setup_logging",
    "run_command",
    "check_outputs_exist",
    "find_files",
    "get_docker_user_args",
    # Config
    "resolve_studydir",
    "load_study_config",
    "get_studydir",
    "find_config_from_cwd",
    "find_studydir_from_cwd",
    # BIDS naming
    "parse_bids_name",
    "build_bids_name",
    "derive_bids_name",
    "classify_dcm2niix_output",
    "strip_dcm2niix_suffix",
    "has_dcm2niix_suffix",
    "entities_match",
    "BIDS_ENTITY_ORDER",
    "BIDS_SUFFIXES",
]
"""
init command - Initialize dcm2bids by registering a study's config.json.

This command reads an existing config.json (created by the user) and registers
it so that all subsequent dcm2bids commands know where to find the study.

Prerequisites (user must create these):
1. A study directory (e.g., /path/to/my_study/)
2. A config file at <studydir>/code/config.json with at minimum:
   {
       "studydir": "/path/to/my_study"
   }
"""

from pathlib import Path
from typing import Optional

from dcm2bids.core import (
    setup_logging,
    set_active_config,
    load_study_config,
    get_studydir,
    SETTINGS_FILE,
)


def run_init(
    config: Optional[Path] = None,
    verbose: bool = False
) -> None:
    """
    Initialize dcm2bids by registering a study's config.json.
    
    This command:
    1. Reads the config.json (from --config or ./code/config.json)
    2. Validates that 'studydir' is defined
    3. Stores the config path in ~/.dcm2bids/settings.json
    
    After this, all commands will automatically use the registered study.
    
    Parameters
    ----------
    config : Path, optional
        Path to config.json. Defaults to ./code/config.json
    verbose : bool
        Enable verbose output
    """
    logger = setup_logging("init", verbose=verbose)
    
    # find config path
    if config is None:
        config = Path.cwd() / "code" / "config.json"
    else:
        config = Path(config)
    
    logger.info(f"Initializing dcm2bids with config: {config}")
    
    # makes sure config exists
    if not config.exists():
        logger.error(f"Config file not found: {config}")
        logger.error("")
        logger.error("Please create your config.json first. Minimum required content:")
        logger.error('  {')
        logger.error('      "studydir": "/path/to/your/study"')
        logger.error('  }')
        logger.error("")
        logger.error("Then run 'dcm2bids init' from the study directory,")
        logger.error("or 'dcm2bids init --config /path/to/config.json'")
        raise FileNotFoundError(f"Config file not found: {config}")
    

    try:
        study_config = load_study_config(config)
    except ValueError as e:
        logger.error(f"Invalid config file: {e}")
        raise
    
    # make sure the given studydir exists
    if "studydir" not in study_config:
        logger.error("'studydir' not found in config.json")
        logger.error("")
        logger.error("Please add the studydir to your config.json:")
        logger.error('  {')
        logger.error('      "studydir": "/path/to/your/study",')
        logger.error('      ...')
        logger.error('  }')
        raise KeyError("'studydir' not found in config.json")
    
    studydir = Path(study_config["studydir"])
    if not studydir.exists():
        logger.error(f"Study directory does not exist: {studydir}")
        logger.error("Please create the directory first.")
        raise FileNotFoundError(f"Study directory does not exist: {studydir}")
    
    # set config as backlog
    set_active_config(config)
    
    logger.info("")
    logger.info("=" * 60)
    logger.info("dcm2bids initialized successfully!")
    logger.info("=" * 60)
    logger.info("")
    logger.info(f"  Config:   {config.resolve()}")
    logger.info(f"  Studydir: {studydir.resolve()}")
    logger.info(f"  Settings: {SETTINGS_FILE}")
    logger.info("")
    logger.info("You can now run commands without --studydir:")
    logger.info("  dcm2bids dcm2src -sub SUBJECT -ses SESSION -d /path/to/dicoms")
    logger.info("  dcm2bids src2rawdata -sub SUBJECT -ses SESSION")
    logger.info("  ...")
    logger.info("")
    

    logger.info("Config summary:")
    for key, value in study_config.items():
        if key != "studydir":
            logger.info(f"  {key}: {value}")
# run-all command. run all conversion steps in sequence

from pathlib import Path
from typing import Optional
from bids7t.core import Session, setup_logging


def run_all_steps(
    studydir: Path, subject: str, session: Optional[str] = None,
    dicom_dir: Path = None, config_path: Optional[Path] = None,
    force: bool = False, verbose: bool = False,
    skip_validate: bool = False, skip_qc: bool = True
) -> None:
    sess = Session(studydir, subject, session, dicom_dir)
    log_file = sess.paths["logs"] / "run_all.log"
    logger = setup_logging("run_all", log_file, verbose)
    
    # resolve dicomdir from config if not provided on command line
    if dicom_dir is None:
        dicom_dir = _resolve_dicomdir(studydir, config_path, logger)
    
    session_label = f"ses-{session}" if session else "(detect from files)"
    
    logger.info("=" * 60)
    logger.info(f"Starting full conversion pipeline")
    logger.info(f"  Subject: sub-{subject}")
    logger.info(f"  Session: {session_label}")
    logger.info(f"  Study:   {studydir}")
    logger.info(f"  DICOMs:  {dicom_dir}")
    if config_path:
        logger.info(f"  Config:  {config_path}")
    logger.info("=" * 60)
    
    # init (once per studydir)
    logger.info("")
    logger.info(">>> Step: init")
    logger.info("-" * 40)
    _run_init(studydir=studydir, verbose=verbose)
    logger.info("init completed")
    
    # dcm2src
    if dicom_dir is not None:
        logger.info("")
        logger.info(">>> Command: dcm2src")
        logger.info("-" * 40)
        _run_dcm2src(studydir=studydir, subject=subject, session=session,
                      dicom_dir=dicom_dir, force=force, verbose=verbose)
        logger.info("dcm2src completed")
    else:
        logger.info("No --dicom-dir and no dicomdir in config, skipping dcm2src")
    
    # re-detect sessions after dcm2src may have created session directories
    from bids7t.core import detect_sessions
    if session is not None:
        sessions = [session]
    else:
        sessions = detect_sessions(studydir, subject)
    
    logger.info(f"Sessions to process: {sessions}")
    
    # commands to run per-session
    per_session_steps = [
        ("src2rawdata", lambda **kw: _run_src2rawdata(config_path=config_path, **kw)),
        ("fixanat", _run_fixanat),
        ("fixfmap", _run_fixfmap),
        ("fixepi", _run_fixepi),
        ("reorient", _run_reorient),
        ("slicetime", _run_slicetime),
    ]
    
    if not skip_validate:
        per_session_steps.append(("validate", _run_validate))
    if not skip_qc:
        per_session_steps.append(("qc", _run_qc))
    
    for ses in sessions:
        ses_label = f"ses-{ses}" if ses else "(no session)"
        logger.info("")
        logger.info(f"{'=' * 40}")
        logger.info(f"Processing {ses_label}")
        logger.info(f"{'=' * 40}")
        
        for step_name, step_func in per_session_steps:
            logger.info("")
            logger.info(f">>> Command: {step_name} [{ses_label}]")
            logger.info("-" * 40)
            try:
                step_func(studydir=studydir, subject=subject, session=ses,
                          force=force, verbose=verbose)
                logger.info(f"{step_name} completed")
            except Exception as e:
                logger.error(f"{step_name} failed: {e}")
                logger.error("Stopping pipeline")
                raise
    
    logger.info("")
    logger.info("=" * 60)
    logger.info("Pipeline completed successfully!")
    logger.info("=" * 60)


def _resolve_dicomdir(studydir, config_path, logger):
    try:
        from bids7t.core import load_config
        config = load_config(studydir, config_path=config_path)
        dicomdir = config.get("dicomdir")
        if dicomdir:
            path = Path(dicomdir)
            if path.exists():
                logger.info(f"Using dicomdir from config: {path}")
                return path
            logger.warning(f"dicomdir in config not found: {path}")
    except Exception:
        pass
    return None


def _run_init(studydir, verbose):
    from bids7t.commands.init import run_init
    run_init(studydir=studydir, verbose=verbose, force=False)

def _run_dcm2src(studydir, subject, session, dicom_dir, force, verbose):
    from bids7t.commands.dcm2src import run_dcm2src
    run_dcm2src(studydir=studydir, subject=subject, session=session,
                dicom_dir=dicom_dir, force=force, verbose=verbose)

def _run_src2rawdata(studydir, subject, session, force, verbose, config_path=None):
    from bids7t.commands.src2rawdata import run_src2rawdata
    run_src2rawdata(studydir=studydir, subject=subject, session=session,
                    config_path=config_path, force=force, verbose=verbose)

def _run_fixanat(studydir, subject, session, force, verbose):
    from bids7t.commands.fixanat import run_fixanat
    run_fixanat(studydir=studydir, subject=subject, session=session, force=force, verbose=verbose)

def _run_fixfmap(studydir, subject, session, force, verbose):
    from bids7t.commands.fixfmap import run_fixfmap
    run_fixfmap(studydir=studydir, subject=subject, session=session, force=force, verbose=verbose)

def _run_fixepi(studydir, subject, session, force, verbose):
    from bids7t.commands.fixepi import run_fixepi
    run_fixepi(studydir=studydir, subject=subject, session=session, force=force, verbose=verbose)

def _run_reorient(studydir, subject, session, force, verbose):
    from bids7t.commands.reorient import run_reorient
    run_reorient(studydir=studydir, subject=subject, session=session, force=force, verbose=verbose)

def _run_slicetime(studydir, subject, session, force, verbose):
    from bids7t.commands.slicetime import run_slicetime
    run_slicetime(studydir=studydir, subject=subject, session=session, force=force, verbose=verbose)

def _run_validate(studydir, subject, session, force, verbose):
    from bids7t.commands.validate import run_validate
    run_validate(studydir=studydir, subject=subject, session=session, force=force, verbose=verbose)

def _run_qc(studydir, subject, session, force, verbose):
    from bids7t.commands.qc import run_qc
    run_qc(studydir=studydir, subject=subject, session=session, force=force, verbose=verbose)
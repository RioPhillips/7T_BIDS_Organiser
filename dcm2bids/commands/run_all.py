"""
run-all command - Run all conversion steps in sequence.

Convenience command that runs dcm2src, src2rawdata, and all fix commands.
"""

from pathlib import Path
from typing import Optional

from dcm2bids.core import Session, setup_logging, get_heuristic_path, load_config


def run_all_steps(
    studydir: Path,
    subject: str,
    session: str,
    dicom_dir: Path,
    heuristic: Optional[Path] = None,
    force: bool = False,
    verbose: bool = False,
    skip_validate: bool = False,
    skip_qc: bool = True
) -> None:
    """
    Run all conversion steps in sequence.
    
    Parameters
    ----------
    studydir : Path
        Path to BIDS study directory
    subject : str
        Subject ID (without sub- prefix)
    session : str
        Session ID (without ses- prefix)
    dicom_dir : Path
        Path to source DICOM directory
    heuristic : Path, optional
        Path to heuristic file
    force : bool
        Force overwrite existing files
    verbose : bool
        Enable verbose output
    skip_validate : bool
        Skip BIDS validation
    skip_qc : bool
        Skip MRIQC (default: True)
    """
    sess = Session(studydir, subject, session, dicom_dir)
    log_file = sess.paths["logs"] / "run_all.log"
    logger = setup_logging("run_all", log_file, verbose)
    
    logger.info("=" * 60)
    logger.info(f"Starting full conversion pipeline")
    logger.info(f"  Subject: sub-{subject}")
    logger.info(f"  Session: ses-{session}")
    logger.info(f"  Study:   {studydir}")
    logger.info(f"  DICOMs:  {dicom_dir}")
    logger.info("=" * 60)
    
    # heuristic path
    if heuristic is None:
        config = load_config(studydir)
        heuristic = get_heuristic_path(studydir, config)
    
    if heuristic:
        logger.info(f"Heuristic: {heuristic}")
    
    steps = [
        ("dcm2src", _run_dcm2src),
        ("src2rawdata", _run_src2rawdata),
        ("b1dcm2rawdata", _run_b1dcm2rawdata),
        ("slicetime", _run_slicetime),
        ("reorient", _run_reorient),
        ("fixanat", _run_fixanat),
        ("fixfmap", _run_fixfmap),
        ("fixepi", _run_fixepi),
    ]
    
    if not skip_validate:
        steps.append(("validate", _run_validate))
    
    if not skip_qc:
        steps.append(("qc", _run_qc))
    
    # runs each step
    for step_name, step_func in steps:
        logger.info("")
        logger.info(f">>> Step: {step_name}")
        logger.info("-" * 40)
        
        try:
            step_func(
                studydir=studydir,
                subject=subject,
                session=session,
                dicom_dir=dicom_dir,
                heuristic=heuristic,
                force=force,
                verbose=verbose
            )
            logger.info(f"✓ {step_name} completed")
        except Exception as e:
            logger.error(f"✗ {step_name} failed: {e}")
            logger.error("Stopping pipeline")
            raise
    
    logger.info("")
    logger.info("=" * 60)
    logger.info("Pipeline completed successfully!")
    logger.info("=" * 60)


def _run_dcm2src(studydir, subject, session, dicom_dir, heuristic, force, verbose):
    from dcm2bids.commands.dcm2src import run_dcm2src
    run_dcm2src(
        studydir=studydir,
        subject=subject,
        session=session,
        dicom_dir=dicom_dir,
        force=force,
        verbose=verbose
    )


def _run_src2rawdata(studydir, subject, session, dicom_dir, heuristic, force, verbose):
    from dcm2bids.commands.src2rawdata import run_src2rawdata
    run_src2rawdata(
        studydir=studydir,
        subject=subject,
        session=session,
        heuristic=heuristic,
        force=force,
        verbose=verbose
    )


def _run_fixanat(studydir, subject, session, dicom_dir, heuristic, force, verbose):
    from dcm2bids.commands.fixanat import run_fixanat
    run_fixanat(
        studydir=studydir,
        subject=subject,
        session=session,
        force=force,
        verbose=verbose
    )


def _run_fixfmap(studydir, subject, session, dicom_dir, heuristic, force, verbose):
    from dcm2bids.commands.fixfmap import run_fixfmap
    run_fixfmap(
        studydir=studydir,
        subject=subject,
        session=session,
        force=force,
        verbose=verbose
    )


def _run_fixepi(studydir, subject, session, dicom_dir, heuristic, force, verbose):
    from dcm2bids.commands.fixepi import run_fixepi
    run_fixepi(
        studydir=studydir,
        subject=subject,
        session=session,
        force=force,
        verbose=verbose
    )


def _run_b1dcm2rawdata(studydir, subject, session, dicom_dir, heuristic, force, verbose):
    from dcm2bids.commands.b1dcm2rawdata import run_b1dcm2rawdata
    run_b1dcm2rawdata(
        studydir=studydir,
        subject=subject,
        session=session,
        force=force,
        verbose=verbose
    )


def _run_reorient(studydir, subject, session, dicom_dir, heuristic, force, verbose):
    from dcm2bids.commands.reorient import run_reorient
    run_reorient(
        studydir=studydir,
        subject=subject,
        session=session,
        force=force,
        verbose=verbose
    )


def _run_slicetime(studydir, subject, session, dicom_dir, heuristic, force, verbose):
    from dcm2bids.commands.slicetime import run_slicetime
    run_slicetime(
        studydir=studydir,
        subject=subject,
        session=session,
        force=force,
        verbose=verbose
    )


def _run_validate(studydir, subject, session, dicom_dir, heuristic, force, verbose):
    from dcm2bids.commands.validate import run_validate
    run_validate(
        studydir=studydir,
        subject=subject,
        session=session,
        force=force,
        verbose=verbose
    )


def _run_qc(studydir, subject, session, dicom_dir, heuristic, force, verbose):
    from dcm2bids.commands.qc import run_qc
    run_qc(
        studydir=studydir,
        subject=subject,
        session=session,
        force=force,
        verbose=verbose
    )

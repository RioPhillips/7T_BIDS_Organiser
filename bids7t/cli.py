"""
Main CLI for the package.

Provides subcommands for each step of the DICOM to BIDS conversion pipeline.
"""

import re
import click
from pathlib import Path
from typing import Optional, List

from bids7t import __version__
from bids7t.core import resolve_studydir, detect_sessions


def _resolve_sessions(studydir: Path, subject: str, session: Optional[str]) -> List[Optional[str]]:
    """
    Resolve which sessions to process.
    
    - If --session provided: run for that session only
    - If --session omitted: auto-detect from sourcedata/rawdata
      - Single-session study (no ses-* dirs) -> [None]
      - Multi-session study (ses-MR1, ses-MR2, ...) -> ["MR1", "MR2", ...]
    """
    if session is not None:
        return [session]
    return detect_sessions(studydir, subject)


class HelpfulGroup(click.Group):
    def invoke(self, ctx):
        if not ctx.protected_args and not ctx.invoked_subcommand:
            click.echo(ctx.get_help())
            ctx.exit(0)
        return super().invoke(ctx)


def common_options(f):
    """Common options for subject/session commands."""
    f = click.option('--studydir', '-s', type=click.Path(exists=True, file_okay=False, path_type=Path),
                     default=None, help='Path to BIDS study directory (default: auto-detect from CWD)')(f)
    f = click.option('--subject', '-sub', type=str, required=True,
                     help='Subject ID (without sub- prefix)')(f)
    f = click.option('--session', '-ses', type=str, required=False, default=None,
                     help='Session ID (without ses- prefix). If omitted, auto-detects: '
                          'runs all sessions for multi-session, or sessionless for single-session.')(f)
    f = click.option('--force', '-f', is_flag=True, default=False,
                     help='Force overwrite existing files')(f)
    f = click.option('--verbose', '-v', is_flag=True, default=False,
                     help='Enable verbose output')(f)
    return f


@click.group(cls=HelpfulGroup, context_settings=dict(help_option_names=['-h', '--help']))
@click.version_option(__version__)
def cli():
    """
    bids7t - DICOM to BIDS conversion tools for 7T MRI data.
    
    Uses dcm2niix directly with configurable series-to-BIDS mapping.
    
    \b
    WORKFLOW:
      0. bids7t init             - Create BIDS top-level files (once per study)
      1. dcm2src                 - Import DICOMs to sourcedata
      2. src2rawdata             - Convert to BIDS with dcm2niix
      3. fixanat                  - Fix anatomical files (MP2RAGE)
      4. fixfmap                  - Fix fieldmap files (B0, B1/DREAM)
      5. fixepi                 - Fix EPI JSON metadata
      6. reorient               - Reorient images
      7. slicetime               - Slice timing correction
      8. bids7t validate         - Run BIDS validator
    
    \b
    SESSION SUPPORT:
      --session/-ses is optional. If omitted, bids7t auto-detects:
        - Multi-session (ses-* dirs found) -> processes ALL sessions
        - Single-session (no ses-* dirs) -> runs without session level
    
    \b
    Use 'bids7t COMMAND --help' for command-specific help.
    """
    pass


# init

@cli.command(context_settings=dict(help_option_names=['-h', '--help']))
@click.option('--studydir', '-s', type=click.Path(exists=True, file_okay=False, path_type=Path),
              default=None, help='Path to BIDS study directory (default: auto-detect from CWD)')
@click.option('--force', '-f', is_flag=True, default=False, help='Overwrite existing BIDS top-level files')
@click.option('--verbose', '-v', is_flag=True, default=False, help='Enable verbose output')
def init(studydir, force, verbose):
    """
    Initialize BIDS study top-level files.
    
    \b
    Creates top-level BIDS files in rawdata/ with TODO placeholders:
      - dataset_description.json
      - README, CHANGES
      - participants.json, participants.tsv
      - .bidsignore
    
    Run once when setting up a new study. Safe to re-run (skips existing files).
    """
    studydir = resolve_studydir(studydir)
    from bids7t.commands.init import run_init
    run_init(studydir=studydir, verbose=verbose, force=force)


# dcm2src 

@cli.command(context_settings=dict(help_option_names=['-h', '--help']))
@common_options
@click.option('--dicom-dir', '-d', type=click.Path(exists=True, path_type=Path),
              required=False, default=None,
              help='Path to DICOM source (default: uses dicomdir in bids7t.yaml)')
@click.option('--zip-input', is_flag=True, default=False,
              help='Explicitly specify that input is/contains a zip file')
def dcm2src(studydir, subject, session, force, verbose, dicom_dir, zip_input):
    """
    Import DICOMs to sourcedata directory.
    
    \b
    If --dicom-dir is omitted, reads 'dicomdir' from code/bids7t.yaml.
    Skips subjects/sessions that already exist in sourcedata (use --force to reimport).
    """
    studydir = resolve_studydir(studydir)
    from bids7t.commands.dcm2src import run_dcm2src
    run_dcm2src(studydir=studydir, subject=subject, session=session,
                dicom_dir=dicom_dir, force=force, verbose=verbose, zip_input=zip_input)


# src2rawdata

@cli.command(context_settings=dict(help_option_names=['-h', '--help']))
@common_options
def src2rawdata(studydir, subject, session, force, verbose):
    """
    Convert sourcedata to BIDS rawdata using dcm2niix.
    
    \b
    Reads series mapping rules from code/bids7t.yaml to determine
    how each DICOM series maps to BIDS output. Calls dcm2niix
    directly per series with full control over flags.
    
    If --session is omitted, auto-detects sessions from sourcedata.
    """
    studydir = resolve_studydir(studydir)
    from bids7t.commands.src2rawdata import run_src2rawdata
    for ses in _resolve_sessions(studydir, subject, session):
        run_src2rawdata(studydir=studydir, subject=subject, session=ses,
                        force=force, verbose=verbose)


# fixanat 

@cli.command(context_settings=dict(help_option_names=['-h', '--help']))
@common_options
def fixanat(studydir, subject, session, force, verbose):
    # fixes anatomical files
    studydir = resolve_studydir(studydir)
    from bids7t.commands.fixanat import run_fixanat
    for ses in _resolve_sessions(studydir, subject, session):
        run_fixanat(studydir=studydir, subject=subject, session=ses, force=force, verbose=verbose)


# fixfmap 

@cli.command(context_settings=dict(help_option_names=['-h', '--help']))
@common_options
def fixfmap(studydir, subject, session, force, verbose):
    # fixes fieldmap files (B0/B1/GRE naming, Units)
    studydir = resolve_studydir(studydir)
    from bids7t.commands.fixfmap import run_fixfmap
    for ses in _resolve_sessions(studydir, subject, session):
        run_fixfmap(studydir=studydir, subject=subject, session=ses, force=force, verbose=verbose)


# fixepi 

@cli.command(context_settings=dict(help_option_names=['-h', '--help']))
@common_options
@click.option('--ap-phase-enc', type=str, default='j-',
              help='Phase encoding direction for AP scans (default: j-)')
def fixepi(studydir, subject, session, force, verbose, ap_phase_enc):
    # EPI JSON metadata (PhaseEncodingDirection, TotalReadoutTime, etc)
    studydir = resolve_studydir(studydir)
    from bids7t.commands.fixepi import run_fixepi
    for ses in _resolve_sessions(studydir, subject, session):
        run_fixepi(studydir=studydir, subject=subject, session=ses,
                   ap_phase_enc=ap_phase_enc, force=force, verbose=verbose)


# reorient 

@cli.command(context_settings=dict(help_option_names=['-h', '--help']))
@common_options
@click.option('--orientation', type=str, default='LPI', help='Target orientation (default: LPI)')
@click.option('--modality', type=click.Choice(['all', 'anat', 'func', 'fmap', 'dwi']),
              default='all', help='Which modality to process')
def reorient(studydir, subject, session, force, verbose, orientation, modality):
    # reorient images to standard orientation
    studydir = resolve_studydir(studydir)
    from bids7t.commands.reorient import run_reorient
    for ses in _resolve_sessions(studydir, subject, session):
        run_reorient(studydir=studydir, subject=subject, session=ses,
                     orientation=orientation, modality=modality, force=force, verbose=verbose)


# slicetime 

@cli.command(context_settings=dict(help_option_names=['-h', '--help']))
@common_options
@click.option('--slice-order', type=click.Choice(['up', 'down', 'odd', 'even']), default='down')
@click.option('--slice-direction', type=int, default=3)
def slicetime(studydir, subject, session, force, verbose, slice_order, slice_direction):
    # slice timing correction using FSL slicetimer
    studydir = resolve_studydir(studydir)
    from bids7t.commands.slicetime import run_slicetime
    for ses in _resolve_sessions(studydir, subject, session):
        run_slicetime(studydir=studydir, subject=subject, session=ses,
                      slice_order=slice_order, slice_direction=slice_direction, force=force, verbose=verbose)


# validate 

@cli.command(context_settings=dict(help_option_names=['-h', '--help']))
@common_options
def validate(studydir, subject, session, force, verbose):
    studydir = resolve_studydir(studydir)
    from bids7t.commands.validate import run_validate
    for ses in _resolve_sessions(studydir, subject, session):
        run_validate(studydir=studydir, subject=subject, session=ses, force=force, verbose=verbose)


# qc 

@cli.command(context_settings=dict(help_option_names=['-h', '--help']))
@common_options
@click.option('--mem-gb', type=int, default=8)
@click.option('--n-procs', type=int, default=4)
@click.option('--modalities', '-mod', type=str, multiple=True, default=None)
def qc(studydir, subject, session, force, verbose, mem_gb, n_procs, modalities):
    studydir = resolve_studydir(studydir)
    from bids7t.commands.qc import run_qc
    for ses in _resolve_sessions(studydir, subject, session):
        run_qc(studydir=studydir, subject=subject, session=ses,
               modalities=list(modalities) if modalities else None,
               mem_gb=mem_gb, n_procs=n_procs, force=force, verbose=verbose)


# --- run-all ---

@cli.command('run-all', context_settings=dict(help_option_names=['-h', '--help']))
@common_options
@click.option('--dicom-dir', '-d', type=click.Path(exists=True, file_okay=False, path_type=Path),
              required=False, default=None,
              help='Path to source DICOM directory (default: uses dicomdir in bids7t.yaml)')
@click.option('--skip-validate', is_flag=True, default=False)
@click.option('--skip-qc', is_flag=True, default=True)
def run_all(studydir, subject, session, force, verbose, dicom_dir,
            skip_validate, skip_qc):
    """
    Run all conversion steps in sequence.
    
    \b
    If --dicom-dir is omitted, reads 'dicomdir' from bids7t.yaml.
    If neither is available, skips dcm2src and starts from src2rawdata.
    
    If --session is omitted, auto-detects sessions and processes all.
    """
    studydir = resolve_studydir(studydir)
    from bids7t.commands.run_all import run_all_steps
    for ses in _resolve_sessions(studydir, subject, session):
        run_all_steps(studydir=studydir, subject=subject, session=ses,
                      dicom_dir=dicom_dir, force=force, verbose=verbose,
                      skip_validate=skip_validate, skip_qc=skip_qc)


# --- status ---

@cli.command(context_settings=dict(help_option_names=['-h', '--help']))
@click.option('--studydir', '-s', type=click.Path(exists=True, file_okay=False, path_type=Path),
              default=None, help='Path to BIDS study directory (default: will search in CWD)')
@click.option('--verbose', '-v', is_flag=True, default=False)
def status(studydir, verbose):
    
    # show study status: subjects, BIDS validation, DICOM files not yet imported.
    
    from bids7t.core import find_config_from_cwd, find_studydir_from_cwd, load_study_config
    
    click.echo("bids7t status")
    click.echo("=" * 60)
    
    # resolve studydir
    if studydir is not None:
        studydir = Path(studydir)
        config_path = studydir / "code" / "bids7t.yaml"
    else:
        config_path = find_config_from_cwd()
        studydir = find_studydir_from_cwd()
    
    if config_path is None or not config_path.exists():
        click.echo(f"Current directory: {Path.cwd()}")
        click.echo("No code/bids7t.yaml found.")
        click.echo("Use '--studydir /path/to/study' or run from within study directory.")
        return
    
    try:
        config = load_study_config(config_path)
    except Exception:
        config = {}
    
    dicomdir = config.get("dicomdir")
    
    click.echo(f"Study dir:  {studydir}")
    if dicomdir:
        dd_path = Path(dicomdir)
        dd_exists = dd_path.exists()
        click.echo(f"DICOM dir:  {dicomdir}" + ("" if dd_exists else "  (NOT FOUND)"))
    else:
        click.echo("DICOM dir:  not configured")
    click.echo("")
    
    # study structure checks
    checks = [
        ("code/bids7t.yaml", config_path.exists()),
        ("code/mp2rage.yaml", (studydir / "code" / "mp2rage.yaml").exists()),
        ("rawdata/", (studydir / "rawdata").exists()),
        ("sourcedata/", (studydir / "sourcedata").exists()),
    ]
    
    click.echo("Folders in the studyr directory:")
    for name, exists in checks:
        mark = "OK" if exists else "Not found"
        click.echo(f"  [{mark:7s}] {name}")
    
    # show config details in verbose mode
    if verbose and config:
        click.echo("")
        click.echo("Configuration:")
        for k, v in config.items():
            if k != "series":
                click.echo(f"  {k}: {v}")
        series = config.get("series", [])
        if series:
            click.echo(f"  series: {len(series)} mapping rules")
    
    # subjects in rawdata with BIDS validation status
    rawdata = studydir / "rawdata"
    if rawdata.exists():
        subjects = _scan_rawdata(rawdata)
        if subjects:
            click.echo("")
            click.echo("Subjects in rawdata:")
            for sub_id, sessions in sorted(subjects.items()):
                ses_str = _format_sessions(sessions)
                bids_status = _check_bids_status(studydir, sub_id, sessions)
                click.echo(f"  sub-{sub_id:<20s} {ses_str:<30s} {bids_status}")
    
    # non-imported DICOMs
    if dicomdir and Path(dicomdir).exists():
        pending = _find_pending_imports(studydir, Path(dicomdir))
        if pending:
            click.echo("")
            click.echo("Files in dicomdir not imported:")
            for zip_name in pending:
                click.echo(f"  {zip_name}")
        elif verbose:
            click.echo("")
            click.echo("No pending DICOM imports.")


def _scan_rawdata(rawdata: Path) -> dict:
    # scans rawdata/ for subjects and their sessions
    subjects = {}
    for sub_dir in sorted(rawdata.iterdir()):
        if not sub_dir.is_dir() or not sub_dir.name.startswith("sub-"):
            continue
        sub_id = sub_dir.name[4:]
        ses_dirs = sorted([
            d for d in sub_dir.iterdir()
            if d.is_dir() and d.name.startswith("ses-")
        ])
        if ses_dirs:
            subjects[sub_id] = [d.name[4:] for d in ses_dirs]
        else:
            # single-session: check if there are modality subdirs (anat/, func/, etc.)
            has_data = any(
                d.is_dir() and d.name in ("anat", "func", "fmap", "dwi")
                for d in sub_dir.iterdir()
            )
            if has_data:
                subjects[sub_id] = [None]
    return subjects


def _format_sessions(sessions: list) -> str:
    if sessions == [None]:
        return ""
    return ", ".join(f"ses-{s}" for s in sessions)


def _check_bids_status(studydir: Path, subject: str, sessions: list) -> str:
    # checks BIDS validation status from existing log files
    logs_base = studydir / "derivatives" / "logs" / "bids7t" / f"sub-{subject}"
    
    # all validation logs for the subject
    log_files = []
    if sessions == [None]:
        log_file = logs_base / "validate.log"
        if log_file.exists():
            log_files.append(log_file)
    else:
        for ses in sessions:
            log_file = logs_base / f"ses-{ses}" / "validate.log"
            if log_file.exists():
                log_files.append(log_file)
    
    if not log_files:
        return "BIDS: not validated"
    
    latest = max(log_files, key=lambda f: f.stat().st_mtime)
    try:
        content = latest.read_text()
        if "BIDS Validation PASSED" in content or "BIDS compatible" in content:
            return "BIDS: OK!"
        else:
            return "BIDS: FAIL"
    except Exception:
        return "BIDS: unknown"


def _find_pending_imports(studydir: Path, dicomdir: Path) -> list:
    # finds zip files in dicomdir that don't have matching sourcedata
    sourcedata = studydir / "sourcedata"
    
    # build set of existing (subject, session) pairs from sourcedata
    existing = set()
    if sourcedata.exists():
        for sub_dir in sorted(sourcedata.iterdir()):
            if not sub_dir.is_dir() or not sub_dir.name.startswith("sub-"):
                continue
            subject = sub_dir.name[4:]
            ses_dirs = [d for d in sub_dir.iterdir() if d.is_dir() and d.name.startswith("ses-")]
            if ses_dirs:
                for ses_dir in ses_dirs:
                    existing.add((subject.lower(), ses_dir.name[4:].lower()))
            else:
                # single-session: mark subject as present
                existing.add((subject.lower(), None))
    
    # scan dicomdir for zips and check which are not in sourcedata
    zips = sorted(dicomdir.glob("*.zip"))
    if not zips:
        return []
    
    pending = []
    for z in zips:
        subject, session = _parse_zip_name(z.name)
        if subject is None:
            # can't parse, include it as unknown
            pending.append(z.name)
            continue
        
        key = (subject.lower(), session.lower() if session else None)
        if key not in existing:
            pending.append(z.name)
    
    return pending


def _parse_zip_name(filename: str):
    """
    Extract subject and session from a zip filename.
    
    Handles patterns like:
      7T079C02_ses-MR1_inkl_B1.zip  -> (7T079C02, MR1)
      sub-S01_ses-MR1.zip           -> (S01, MR1)
      7T049S14.zip                  -> (7T049S14, None)
      sub-S01.zip                   -> (S01, None)
    """
    name = filename.replace(".zip", "")
    
    # extract session (ses-XXX anywhere in the name)
    ses_match = re.search(r'ses-([A-Za-z0-9]+)', name)
    session = ses_match.group(1) if ses_match else None
    
    # extract subject (from start, up to first underscore)
    sub_match = re.match(r'(?:sub-)?([A-Za-z0-9]+?)(?:_|$)', name)
    subject = sub_match.group(1) if sub_match else None
    
    return subject, session


def main():
    cli()


#  entry points 
# allows running commands directly without the 'bids7t' prefix:
#   dcm2src --subject S01 ...
#   src2rawdata --subject S01 ...
# the bids7t group command still works too:
#   bids7t dcm2src --subject S01 ...

def dcm2src_main():
    dcm2src(standalone_mode=True)

# def init_main():
#     init(standalone_mode=True)

def src2rawdata_main():
    src2rawdata(standalone_mode=True)

def fixanat_main():
    fixanat(standalone_mode=True)

def fixfmap_main():
    fixfmap(standalone_mode=True)

def fixepi_main():
    fixepi(standalone_mode=True)

def reorient_main():
    reorient(standalone_mode=True)

def slicetime_main():
    slicetime(standalone_mode=True)

def run_all_main():
    run_all(standalone_mode=True)


if __name__ == '__main__':
    main()
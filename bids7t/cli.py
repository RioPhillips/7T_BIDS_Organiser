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
                     help='Session ID (without ses- prefix). If omitted, auto-detects.')(f)
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
      0. bids7t init       - Create BIDS top-level files (once per study)
      1. dcm2src           - Import DICOMs to sourcedata
      2. src2rawdata       - Convert to BIDS with dcm2niix
      3. fixanat           - Fix anatomical files (MP2RAGE)
      4. fixfmap           - Fix fieldmap files (B0, B1/DREAM)
      5. fixepi            - Fix EPI JSON metadata
      6. reorient          - Reorient images
      7. slicetime         - Slice timing correction
      8. bids7t validate   - Run BIDS validator
    
    \b
    Use 'bids7t COMMAND --help' for command-specific help.
    """
    pass


# --- init ---

@cli.command(context_settings=dict(help_option_names=['-h', '--help']))
@click.option('--studydir', '-s', type=click.Path(exists=True, file_okay=False, path_type=Path),
              default=None, help='Path to BIDS study directory (default: auto-detect from CWD)')
@click.option('--force', '-f', is_flag=True, default=False, help='Overwrite existing BIDS top-level files')
@click.option('--verbose', '-v', is_flag=True, default=False, help='Enable verbose output')
def init(studydir, force, verbose):
    """Initialize BIDS study top-level files."""
    studydir = resolve_studydir(studydir)
    from bids7t.commands.init import run_init
    run_init(studydir=studydir, verbose=verbose, force=force)


# --- dcm2src ---

@cli.command(context_settings=dict(help_option_names=['-h', '--help']))
@common_options
@click.option('--dicom-dir', '-d', type=click.Path(exists=True, path_type=Path),
              required=False, default=None,
              help='Path to DICOM source (default: uses dicomdir in bids7t.yaml)')
@click.option('--zip-input', is_flag=True, default=False,
              help='Explicitly specify that input is/contains a zip file')
def dcm2src(studydir, subject, session, force, verbose, dicom_dir, zip_input):
    """Import DICOMs to sourcedata directory."""
    studydir = resolve_studydir(studydir)
    from bids7t.commands.dcm2src import run_dcm2src
    run_dcm2src(studydir=studydir, subject=subject, session=session,
                dicom_dir=dicom_dir, force=force, verbose=verbose, zip_input=zip_input)


# --- src2rawdata ---

@cli.command(context_settings=dict(help_option_names=['-h', '--help']))
@common_options
@click.option('--config', '-c', type=click.Path(exists=True, path_type=Path),
              default=None,
              help='Path to bids7t config file (default: code/bids7t.yaml). '
                   'Use for pilot sessions with different scan protocols.')
def src2rawdata(studydir, subject, session, force, verbose, config):
    """
    Convert sourcedata to BIDS rawdata using dcm2niix.
    
    \b
    Reads series mapping rules from code/bids7t.yaml (or --config).
    
    For pilot sessions with different scan protocols, use --config
    to point to a session-specific config file:
    
        src2rawdata --subject S01 --session MR1 \\
                    --config code/bids7t_ses-MR1.yaml
    """
    studydir = resolve_studydir(studydir)
    from bids7t.commands.src2rawdata import run_src2rawdata
    for ses in _resolve_sessions(studydir, subject, session):
        run_src2rawdata(studydir=studydir, subject=subject, session=ses,
                        config_path=config, force=force, verbose=verbose)


# --- fixanat ---

@cli.command(context_settings=dict(help_option_names=['-h', '--help']))
@common_options
def fixanat(studydir, subject, session, force, verbose):
    """Fix anatomical files (MP2RAGE processing)."""
    studydir = resolve_studydir(studydir)
    from bids7t.commands.fixanat import run_fixanat
    for ses in _resolve_sessions(studydir, subject, session):
        run_fixanat(studydir=studydir, subject=subject, session=ses, force=force, verbose=verbose)


# --- fixfmap ---

@cli.command(context_settings=dict(help_option_names=['-h', '--help']))
@common_options
def fixfmap(studydir, subject, session, force, verbose):
    """Fix fieldmap files (B0/B1/GRE naming, Units)."""
    studydir = resolve_studydir(studydir)
    from bids7t.commands.fixfmap import run_fixfmap
    for ses in _resolve_sessions(studydir, subject, session):
        run_fixfmap(studydir=studydir, subject=subject, session=ses, force=force, verbose=verbose)


# --- fixepi ---

@cli.command(context_settings=dict(help_option_names=['-h', '--help']))
@common_options
@click.option('--ap-phase-enc', type=str, default='j-',
              help='Phase encoding direction for AP scans (default: j-)')
def fixepi(studydir, subject, session, force, verbose, ap_phase_enc):
    """Fix EPI JSON metadata (PhaseEncodingDirection, TotalReadoutTime)."""
    studydir = resolve_studydir(studydir)
    from bids7t.commands.fixepi import run_fixepi
    for ses in _resolve_sessions(studydir, subject, session):
        run_fixepi(studydir=studydir, subject=subject, session=ses,
                   ap_phase_enc=ap_phase_enc, force=force, verbose=verbose)


# --- reorient ---

@cli.command(context_settings=dict(help_option_names=['-h', '--help']))
@common_options
@click.option('--orientation', type=str, default='LPI', help='Target orientation (default: LPI)')
@click.option('--modality', type=click.Choice(['all', 'anat', 'func', 'fmap', 'dwi']),
              default='all', help='Which modality to process')
def reorient(studydir, subject, session, force, verbose, orientation, modality):
    """Reorient images to standard orientation."""
    studydir = resolve_studydir(studydir)
    from bids7t.commands.reorient import run_reorient
    for ses in _resolve_sessions(studydir, subject, session):
        run_reorient(studydir=studydir, subject=subject, session=ses,
                     orientation=orientation, modality=modality, force=force, verbose=verbose)


# --- slicetime ---

@cli.command(context_settings=dict(help_option_names=['-h', '--help']))
@common_options
@click.option('--slice-order', type=click.Choice(['up', 'down', 'odd', 'even']), default='down')
@click.option('--slice-direction', type=int, default=3)
def slicetime(studydir, subject, session, force, verbose, slice_order, slice_direction):
    """Slice timing correction using FSL slicetimer."""
    studydir = resolve_studydir(studydir)
    from bids7t.commands.slicetime import run_slicetime
    for ses in _resolve_sessions(studydir, subject, session):
        run_slicetime(studydir=studydir, subject=subject, session=ses,
                      slice_order=slice_order, slice_direction=slice_direction, force=force, verbose=verbose)


# --- validate ---

@cli.command(context_settings=dict(help_option_names=['-h', '--help']))
@common_options
def validate(studydir, subject, session, force, verbose):
    """Run BIDS validator (Docker)."""
    studydir = resolve_studydir(studydir)
    from bids7t.commands.validate import run_validate
    for ses in _resolve_sessions(studydir, subject, session):
        run_validate(studydir=studydir, subject=subject, session=ses, force=force, verbose=verbose)


# --- qc ---

@cli.command(context_settings=dict(help_option_names=['-h', '--help']))
@common_options
@click.option('--mem-gb', type=int, default=8)
@click.option('--n-procs', type=int, default=4)
@click.option('--modalities', '-mod', type=str, multiple=True, default=None)
def qc(studydir, subject, session, force, verbose, mem_gb, n_procs, modalities):
    """Run MRIQC quality control (Docker)."""
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
              help='Path to source DICOM directory (default: uses dicomdir in config)')
@click.option('--config', '-c', type=click.Path(exists=True, path_type=Path),
              default=None,
              help='Path to bids7t config file (default: code/bids7t.yaml). '
                   'Use for pilot sessions with different scan protocols.')
@click.option('--skip-validate', is_flag=True, default=False)
@click.option('--skip-qc', is_flag=True, default=True)
def run_all(studydir, subject, session, force, verbose, dicom_dir, config,
            skip_validate, skip_qc):
    """
    Run all conversion steps in sequence.
    
    \b
    For pilot sessions with different scan protocols, use --config
    to point to a session-specific config file:
    
        run-all --subject 7T079C02 --session MR1 \\
                --config code/bids7t_sub-7T079C02_ses-MR1.yaml
    
    If --session is omitted, auto-detects sessions and processes all.
    """
    studydir = resolve_studydir(studydir)
    from bids7t.commands.run_all import run_all_steps
    for ses in _resolve_sessions(studydir, subject, session):
        run_all_steps(studydir=studydir, subject=subject, session=ses,
                      dicom_dir=dicom_dir, config_path=config,
                      force=force, verbose=verbose,
                      skip_validate=skip_validate, skip_qc=skip_qc)


# --- status ---

@cli.command(context_settings=dict(help_option_names=['-h', '--help']))
@click.option('--studydir', '-s', type=click.Path(exists=True, file_okay=False, path_type=Path),
              default=None, help='Path to BIDS study directory')
@click.option('--verbose', '-v', is_flag=True, default=False)
def status(studydir, verbose):
    """Show study status."""
    from bids7t.core import find_config_from_cwd, find_studydir_from_cwd, load_study_config
    
    click.echo("bids7t status")
    click.echo("=" * 60)
    
    if studydir is not None:
        studydir = Path(studydir)
        config_path = studydir / "code" / "bids7t.yaml"
    else:
        config_path = find_config_from_cwd()
        studydir = find_studydir_from_cwd()
    
    if config_path is None or not config_path.exists():
        click.echo(f"Current directory: {Path.cwd()}")
        click.echo("No code/bids7t.yaml found.")
        return
    
    try:
        config = load_study_config(config_path)
    except Exception:
        config = {}
    
    dicomdir = config.get("dicomdir")
    click.echo(f"Study dir:  {studydir}")
    if dicomdir:
        dd_path = Path(dicomdir)
        click.echo(f"DICOM dir:  {dicomdir}" + ("" if dd_path.exists() else "  (NOT FOUND)"))
    else:
        click.echo("DICOM dir:  not configured")
    click.echo("")
    
    checks = [
        ("code/bids7t.yaml", config_path.exists()),
        ("code/mp2rage.yaml", (studydir / "code" / "mp2rage.yaml").exists()),
        ("rawdata/", (studydir / "rawdata").exists()),
        ("sourcedata/", (studydir / "sourcedata").exists()),
    ]
    click.echo("Study directory structure:")
    for name, exists in checks:
        mark = "OK" if exists else "Not found"
        click.echo(f"  [{mark:7s}] {name}")
    
    if verbose and config:
        click.echo("")
        click.echo("Configuration:")
        for k, v in config.items():
            if k != "series":
                click.echo(f"  {k}: {v}")
        series = config.get("series", [])
        if series:
            click.echo(f"  series: {len(series)} mapping rules")
    
    rawdata = studydir / "rawdata"
    if rawdata.exists():
        subjects = {}
        for sub_dir in sorted(rawdata.iterdir()):
            if not sub_dir.is_dir() or not sub_dir.name.startswith("sub-"):
                continue
            sub_id = sub_dir.name[4:]
            ses_dirs = sorted([d for d in sub_dir.iterdir() if d.is_dir() and d.name.startswith("ses-")])
            if ses_dirs:
                subjects[sub_id] = [d.name[4:] for d in ses_dirs]
            elif any(d.is_dir() and d.name in ("anat", "func", "fmap", "dwi") for d in sub_dir.iterdir()):
                subjects[sub_id] = [None]
        if subjects:
            click.echo("")
            click.echo("Subjects in rawdata:")
            for sub_id, sessions in sorted(subjects.items()):
                ses_str = ", ".join(f"ses-{s}" for s in sessions if s) if sessions != [None] else ""
                click.echo(f"  sub-{sub_id:<20s} {ses_str}")


def main():
    cli()


# direct entry points
def dcm2src_main():
    dcm2src(standalone_mode=True)

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
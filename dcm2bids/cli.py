"""
Main CLI for dcm2bids package.

Provides subcommands for each step of the DICOM to BIDS conversion pipeline.
"""

import click
from pathlib import Path
from typing import Optional

from dcm2bids import __version__
from dcm2bids.core import resolve_studydir



class HelpfulGroup(click.Group):
    """Custom group that shows help when no command is given."""
    
    def invoke(self, ctx):
        if not ctx.protected_args and not ctx.invoked_subcommand:
            click.echo(ctx.get_help())
            ctx.exit(0)
        return super().invoke(ctx)


class HelpfulCommand(click.Command):
    """Custom command that shows help when required args are missing."""
    
    def invoke(self, ctx):
        # If no arguments were provided at all, show help
        if not ctx.params or all(v is None for v in ctx.params.values() if v is not None):
            # Check if we have all required params
            missing = []
            for param in self.params:
                if param.required and ctx.params.get(param.name) is None:
                    missing.append(param.name)
            if missing:
                click.echo(ctx.get_help())
                ctx.exit(0)
        return super().invoke(ctx)



# studydir resolution callback


def resolve_studydir_callback(ctx, param, value):
    """Callback to resolve studydir from config if not provided."""
    if value is not None:
        return Path(value)
    
    # allows commands to show help before failing
    return None



# options decorator


def common_options(f):
    """Common options for subject/session commands."""
    f = click.option(
        '--studydir', '-s',
        type=click.Path(exists=True, file_okay=False, path_type=Path),
        default=None,
        help='Path to BIDS study directory (default: auto-detect from CWD)'
    )(f)
    f = click.option(
        '--subject', '-sub',
        type=str,
        required=True,
        help='Subject ID (without sub- prefix)'
    )(f)
    f = click.option(
        '--session', '-ses',
        type=str,
        required=True,
        help='Session ID (without ses- prefix, e.g., MR1)'
    )(f)
    f = click.option(
        '--force', '-f',
        is_flag=True,
        default=False,
        help='Force overwrite existing files'
    )(f)
    f = click.option(
        '--verbose', '-v',
        is_flag=True,
        default=False,
        help='Enable verbose output'
    )(f)
    return f






@click.group(cls=HelpfulGroup, context_settings=dict(help_option_names=['-h', '--help']))
@click.version_option(__version__)
def cli():
    """
    dcm2bids - DICOM to BIDS conversion tools for 7T MRI data.
    
    A modular CLI toolkit for converting raw DICOM files from 7T MRI scanners
    to BIDS-compliant directory structures.
    
    \b
    SETUP:
      1. Create your study directory with code/config.json
      2. Run commands from within the study directory tree
    
    \b
    WORKFLOW:
      1. dcm2bids dcm2src           - Import DICOMs to sourcedata
      2. dcm2bids src2rawdata       - Convert to BIDS with heudiconv
      3. dcm2bids fixanat           - Fix anatomical files (MP2RAGE)
      4. dcm2bids fixfmap           - Fix fieldmap files
      5. dcm2bids fixepi            - Fix EPI JSON metadata
      6. dcm2bids b1src2rawdata     - Fix B1 map files
      7. dcm2bids reorient          - Reorient images
      8. dcm2bids slicetime         - Slice timing correction
      9. dcm2bids validate          - Run BIDS validator
    
    \b
    CONFIG DISCOVERY:
      The package automatically searches for code/config.json starting from
      your current directory and looking in parent directories. This means
      you can run commands from anywhere within your study directory tree.
    
    \b
    Use 'dcm2bids COMMAND --help' for command-specific help.
    """
    pass



# dcm2src command


@cli.command(context_settings=dict(help_option_names=['-h', '--help']))
@common_options
@click.option(
    '--dicom-dir', '-d',
    type=click.Path(exists=True, path_type=Path),
    required=True,
    help='Path to DICOM source: zip file, directory with zip, or DICOM directory'
)
@click.option(
    '--zip-input',
    is_flag=True,
    default=False,
    help='Explicitly specify that input is/contains a zip file'
)
def dcm2src(studydir, subject, session, force, verbose, dicom_dir, zip_input):
    """
    Import DICOMs to sourcedata directory.
    
    \b
    Accepts multiple input formats:
      - Zip file directly: /path/to/S01_ses-MR1.zip
      - Directory containing zip: /path/to/zips/ (auto-finds matching zip)
      - Directory with DICOMs: /path/to/dicoms/
    
    \b
    Output structure:
      sourcedata/sub-{subject}/ses-{session}/<series>/*.dcm
    """
    studydir = resolve_studydir(studydir)
    from dcm2bids.commands.dcm2src import run_dcm2src
    run_dcm2src(
        studydir=studydir,
        subject=subject,
        session=session,
        dicom_dir=dicom_dir,
        force=force,
        verbose=verbose,
        zip_input=zip_input
    )



# src2rawdata command


@cli.command(context_settings=dict(help_option_names=['-h', '--help']))
@common_options
@click.option(
    '--heuristic', '-H',
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    default=None,
    help='Path to heuristic file (default: from config.json)'
)
@click.option(
    '--use-docker',
    is_flag=True,
    default=False,
    help='Run heudiconv via Docker'
)
@click.option(
    '--notop',
    is_flag=True,
    default=False,
    help='Skip creating top-level BIDS files (for batch processing)'
)
def src2rawdata(studydir, subject, session, force, verbose, heuristic, use_docker, notop):
    """
    Convert sourcedata to BIDS rawdata using heudiconv.
    
    \b
    IMPORTANT: Your heuristic file MUST include {session} in templates:
      CORRECT:   'sub-{subject}/{session}/anat/sub-{subject}_{session}_T1w'
      INCORRECT: 'sub-{subject}/anat/sub-{subject}_T1w'
    
    \b
    For batch processing, use --notop to avoid race conditions,
    then run 'dcm2bids populate-templates' once after all subjects.
    """
    studydir = resolve_studydir(studydir)
    from dcm2bids.commands.src2rawdata import run_src2rawdata
    run_src2rawdata(
        studydir=studydir,
        subject=subject,
        session=session,
        heuristic=heuristic,
        force=force,
        verbose=verbose,
        use_docker=use_docker,
        notop=notop
    )



# fixanat command


@cli.command(context_settings=dict(help_option_names=['-h', '--help']))
@common_options
def fixanat(studydir, subject, session, force, verbose):
    """
    Fix anatomical files (MP2RAGE processing).
    
    \b
    This command:
      - Splits combined inv-1and2 files into separate inv1/inv2 files
      - Computes magnitude and phase from real/imag pairs
      - Reshapes UNIT1 (T1w) files if they have dummy dimensions
    """
    studydir = resolve_studydir(studydir)
    from dcm2bids.commands.fixanat import run_fixanat
    run_fixanat(
        studydir=studydir,
        subject=subject,
        session=session,
        force=force,
        verbose=verbose
    )



# fixfmap command


@cli.command(context_settings=dict(help_option_names=['-h', '--help']))
@common_options
def fixfmap(studydir, subject, session, force, verbose):
    """
    Fix fieldmap files.
    
    \b
    This command:
      - Renames GRE fieldmap/magnitude files to BIDS convention
      - Adds Units field to GRE fieldmap JSON
      - Adds IntendedFor field to SE-EPI JSON files
    """
    studydir = resolve_studydir(studydir)
    from dcm2bids.commands.fixfmap import run_fixfmap
    run_fixfmap(
        studydir=studydir,
        subject=subject,
        session=session,
        force=force,
        verbose=verbose
    )



# fixepi command


@cli.command(context_settings=dict(help_option_names=['-h', '--help']))
@common_options
@click.option(
    '--ap-phase-enc',
    type=str,
    default='j-',
    help='Phase encoding direction for AP scans (default: j-)'
)
def fixepi(studydir, subject, session, force, verbose, ap_phase_enc):
    """
    Fix EPI JSON metadata.
    
    \b
    This command:
      - Updates PhaseEncodingDirection in SE-EPI JSON files
      - Calculates and adds TotalReadoutTime from DICOM metadata
    """
    studydir = resolve_studydir(studydir)
    from dcm2bids.commands.fixepi import run_fixepi
    run_fixepi(
        studydir=studydir,
        subject=subject,
        session=session,
        ap_phase_enc=ap_phase_enc,
        force=force,
        verbose=verbose
    )



# b1src2rawdata command


@cli.command(context_settings=dict(help_option_names=['-h', '--help']))
@common_options
def b1src2rawdata(studydir, subject, session, force, verbose):
    """
    Import B1 map files.
    
    Converts B1 DICOMs using dcm2niix directly (workaround for
    heudiconv issues with B1 maps that cause incorrect naming).
    """
    studydir = resolve_studydir(studydir)
    from dcm2bids.commands.b1src2rawdata import run_b1src2rawdata
    run_b1src2rawdata(
        studydir=studydir,
        subject=subject,
        session=session,
        force=force,
        verbose=verbose
    )



# reorient command


@cli.command(context_settings=dict(help_option_names=['-h', '--help']))
@common_options
@click.option(
    '--orientation',
    type=str,
    default='LPI',
    help='Target orientation code (default: LPI)'
)
@click.option(
    '--modality',
    type=click.Choice(['all', 'anat', 'func', 'fmap', 'dwi']),
    default='all',
    help='Which modality to process (default: all)'
)
def reorient(studydir, subject, session, force, verbose, orientation, modality):
    """
    Reorient images to standard orientation.
    
    Uses FSL fslswapdim to reorient NIfTI images to the specified
    orientation code (e.g., LPI, RAS).
    """
    studydir = resolve_studydir(studydir)
    from dcm2bids.commands.reorient import run_reorient
    run_reorient(
        studydir=studydir,
        subject=subject,
        session=session,
        orientation=orientation,
        modality=modality,
        force=force,
        verbose=verbose
    )



# slicetime command


@cli.command(context_settings=dict(help_option_names=['-h', '--help']))
@common_options
@click.option(
    '--slice-order',
    type=click.Choice(['up', 'down', 'odd', 'even']),
    default='down',
    help='Slice acquisition order (default: down)'
)
@click.option(
    '--slice-direction',
    type=int,
    default=3,
    help='Slice direction axis: 1=x, 2=y, 3=z (default: 3)'
)
def slicetime(studydir, subject, session, force, verbose, slice_order, slice_direction):
    """
    Perform slice timing correction on functional data.
    
    Uses FSL slicetimer to correct for slice acquisition timing
    differences in functional images.
    """
    studydir = resolve_studydir(studydir)
    from dcm2bids.commands.slicetime import run_slicetime
    run_slicetime(
        studydir=studydir,
        subject=subject,
        session=session,
        slice_order=slice_order,
        slice_direction=slice_direction,
        force=force,
        verbose=verbose
    )



# validate command


@cli.command(context_settings=dict(help_option_names=['-h', '--help']))
@common_options
def validate(studydir, subject, session, force, verbose):
    """
    Run BIDS validator on the dataset.
    
    Uses the bids-validator Docker container to check BIDS compliance.
    """
    studydir = resolve_studydir(studydir)
    from dcm2bids.commands.validate import run_validate
    run_validate(
        studydir=studydir,
        subject=subject,
        session=session,
        force=force,
        verbose=verbose
    )



# qc command (MRIQC)


@cli.command(context_settings=dict(help_option_names=['-h', '--help']))
@common_options
@click.option(
    '--mem-gb',
    type=int,
    default=6,
    help='Memory limit in GB for MRIQC (default: 6)'
)
def qc(studydir, subject, session, force, verbose, mem_gb):
    """
    Run MRIQC quality control.
    
    Uses the MRIQC Docker container to generate quality control reports.
    """
    studydir = resolve_studydir(studydir)
    from dcm2bids.commands.qc import run_qc
    run_qc(
        studydir=studydir,
        subject=subject,
        session=session,
        mem_gb=mem_gb,
        force=force,
        verbose=verbose
    )



# run-all command


@cli.command('run-all', context_settings=dict(help_option_names=['-h', '--help']))
@common_options
@click.option(
    '--dicom-dir', '-d',
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    required=True,
    help='Path to source DICOM directory'
)
@click.option(
    '--heuristic', '-H',
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    default=None,
    help='Path to heuristic file (default: from config.json)'
)
@click.option(
    '--skip-validate',
    is_flag=True,
    default=False,
    help='Skip BIDS validation step'
)
@click.option(
    '--skip-qc',
    is_flag=True,
    default=True,
    help='Skip MRIQC step (default: skip)'
)
def run_all(studydir, subject, session, force, verbose, dicom_dir, heuristic, 
            skip_validate, skip_qc):
    """
    Run all conversion steps in sequence.
    
    Convenience command that runs dcm2src, src2rawdata, and all fix commands.
    """
    studydir = resolve_studydir(studydir)
    from dcm2bids.commands.run_all import run_all_steps
    run_all_steps(
        studydir=studydir,
        subject=subject,
        session=session,
        dicom_dir=dicom_dir,
        heuristic=heuristic,
        force=force,
        verbose=verbose,
        skip_validate=skip_validate,
        skip_qc=skip_qc
    )



# populate-templates command


@cli.command('populate-templates', context_settings=dict(help_option_names=['-h', '--help']))
@click.option(
    '--studydir', '-s',
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    default=None,
    help='Path to BIDS study directory (default: auto-detect from CWD)'
)
@click.option(
    '--heuristic', '-H',
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    default=None,
    help='Path to heuristic file (default: from config.json)'
)
@click.option(
    '--use-docker',
    is_flag=True,
    default=False,
    help='Run heudiconv via Docker'
)
@click.option(
    '--verbose', '-v',
    is_flag=True,
    default=False,
    help='Enable verbose output'
)
def populate_templates(studydir, heuristic, use_docker, verbose):
    """
    Create top-level BIDS files after batch processing.
    
    \b
    Use after running 'src2rawdata --notop' for multiple subjects.
    Creates:
      - dataset_description.json
      - README
      - CHANGES
      - .bidsignore
      
    Note: participants.tsv must be created/updated manually.
    """
    studydir = resolve_studydir(studydir)
    from dcm2bids.commands.populate_templates import run_populate_templates
    run_populate_templates(
        studydir=studydir,
        heuristic=heuristic,
        use_docker=use_docker,
        verbose=verbose
    )




@cli.command(context_settings=dict(help_option_names=['-h', '--help']))
@click.option(
    '--verbose', '-v',
    is_flag=True,
    default=False,
    help='Show detailed configuration'
)
def status(verbose):
    """
    Show current dcm2bids configuration status.
    
    Displays the detected study directory and configuration based on
    the current working directory.
    """
    from dcm2bids.core import (
        find_config_from_cwd,
        find_studydir_from_cwd,
        load_study_config,
    )
    
    click.echo("dcm2bids status")
    click.echo("=" * 100)
    click.echo(f"Current directory: {Path.cwd()}")
    click.echo("")
    
    config_path = find_config_from_cwd()
    
    if config_path is None:
        click.echo("No code/config.json found in current directory or parents.")
        click.echo("")
        click.echo("To use dcm2bids:")
        click.echo("  1. Create your study directory (e.g., /path/to/my_study/)")
        click.echo("  2. Create code/config.json with your settings")
        click.echo("  3. Run commands from within the study directory tree")
        click.echo("")
        click.echo("Or use '--studydir /path/to/study' with any command.")
        return
    
    studydir = find_studydir_from_cwd()
    
    click.echo(f"Config found:  {config_path}")
    click.echo(f"Study dir:     {studydir}")
    click.echo("")
    
    try:
        config = load_study_config(config_path)
    except Exception as e:
        config = {}
        if verbose:
            click.echo(f"Warning: Could not load config: {e}")
            click.echo("")
    
    if verbose and config:
        click.echo("Configuration contents:")
        click.echo("-" * 50)
        for key, value in config.items():
            click.echo(f"  {key}: {value}")
        click.echo("")
    

    heuristic_path = None
    heuristic_display = "code/heuristic.py (not configured)"
    
    if "heuristic" in config:
        heuristic_rel = config["heuristic"]
        heuristic_path = studydir / heuristic_rel if studydir else None
        heuristic_display = heuristic_rel
    elif studydir:
        code_dir = studydir / "code"
        if code_dir.exists():
            patterns = ["*heuristic*.py", "*_heuristic.py", "heuristic_*.py", "heuristic.py"]
            for pattern in patterns:
                matches = list(code_dir.glob(pattern))
                if matches:
                    heuristic_path = matches[0]
                    heuristic_display = f"code/{heuristic_path.name} (auto-detected)"
                    break
    
    click.echo("Study structure:")
    click.echo("-" * 50)
    
    checks = [
        ("code/config.json", config_path.exists() if config_path else False),
        (heuristic_display, heuristic_path.exists() if heuristic_path else False),
        ("code/mp2rage.json", (studydir / "code" / "mp2rage.json").exists() if studydir else False),
        ("rawdata/", (studydir / "rawdata").exists() if studydir else False),
        ("sourcedata/", (studydir / "sourcedata").exists() if studydir else False),
        ("derivatives/", (studydir / "derivatives").exists() if studydir else False)
    ]
    
    for name, exists in checks:
        status_mark = "OK!: " if exists else "NOT FOUND: "
        click.echo(f"  {status_mark} {name}")


# entry point for the CLI


def main():
    cli()


if __name__ == '__main__':
    main()
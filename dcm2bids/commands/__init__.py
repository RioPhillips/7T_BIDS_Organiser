"""Command modules for dcm2bids CLI."""

from .dcm2src import run_dcm2src
from .src2rawdata import run_src2rawdata
from .fixanat import run_fixanat
from .b1dcm2rawdata import run_b1dcm2rawdata
from .fixfmap import run_fixfmap
from .fixepi import run_fixepi
from .reorient import run_reorient
from .slicetime import run_slicetime
from .validate import run_validate
from .qc import run_qc
from .run_all import run_all_steps
from .init_study import run_init
from .populate_templates import run_populate_templates

__all__ = [
    "run_dcm2src",
    "run_src2rawdata",
    "run_fixanat",
    "run_b1dcm2rawdata",
    "run_fixfmap",
    "run_fixepi",
    "run_reorient",
    "run_slicetime",
    "run_validate",
    "run_qc",
    "run_all_steps",
    "run_init",
    "run_populate_templates"
]
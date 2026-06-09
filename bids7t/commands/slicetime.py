"""
slicetime - populate the SliceTiming field in BOLD JSON sidecars.

Timings use a multiband- and interleave-aware model :
  - slices are split into `mb_factor` simultaneously-excited bands
  - within a band: ascending/descending, optionally interleaved
  - per-band time grid is i * TR / slices_per_band

If dcm2niix already wrote SliceTiming (from the scanner's per-slice
timestamps) it is treated as ground truth and preserved. Use --force
to recompute and overwrite — the script then logs how far the computed
values fall from the scanner values, for comparison.

Settings are read from code/bids7t.yaml:
  mb_factor          multiband factor fallback (used if absent from JSON)
  slice_order        ascending | descending  (default ascending)
  slice_interleaved  true | false            (default true, per spinoza)
"""

import math
from pathlib import Path
from typing import Optional, List

import nibabel as nib

from bids7t.core import Session, setup_logging, find_files, load_config


def compute_slice_timings(nr_slices: int, tr: float, mb_factor: int = 1,
                          order: str = "ascending",
                          interleaved: bool = True) -> List[float]:
    """
    Per-slice acquisition times for a (multiband) 2D EPI sequence.

    Slices are divided into `mb_factor` simultaneously-excited bands;
    within a band acquisition is ascending/descending, optionally
    interleaved with a sqrt(slices_per_band) step. Returns a list of
    length nr_slices, each value in [0, tr).
    """
    if order not in ("ascending", "descending"):
        raise ValueError("order must be 'ascending' or 'descending'")
    if mb_factor < 1 or nr_slices % mb_factor != 0:
        raise ValueError(
            f"nr_slices ({nr_slices}) must be divisible by mb_factor ({mb_factor})"
        )

    per_band = nr_slices // mb_factor
    base_times = [i * tr / per_band for i in range(per_band)]

    if interleaved:
        step = max(int(round(math.sqrt(per_band))), 1)
        band_order = [i for off in range(step) for i in range(off, per_band, step)]
    else:
        band_order = list(range(per_band))

    if order == "descending":
        band_order = band_order[::-1]

    slice_times = [0.0] * nr_slices
    for band in range(mb_factor):
        for k, idx in enumerate(band_order):
            slice_times[idx + band * per_band] = base_times[k]
    return slice_times


def _resolve_mb_factor(meta: dict, config_mb) -> int:
    if "MultibandAccelerationFactor" in meta:
        try:
            return int(meta["MultibandAccelerationFactor"])
        except (TypeError, ValueError):
            pass
    if config_mb is not None:
        return int(config_mb)
    return 1


def run_slicetime(studydir: Path, subject: str, session: Optional[str] = None,
                  force: bool = False, verbose: bool = False) -> None:
    sess = Session(studydir, subject, session)
    log_file = sess.paths["logs"] / "slicetime.log"
    logger = setup_logging("slicetime", log_file, verbose)

    func_dir = sess.paths["func"]
    if not func_dir.exists():
        logger.warning("func directory not found"); return

    # study-level settings from bids7t.yaml
    config = {}
    try:
        config = load_config(studydir) or {}
    except Exception:
        pass
    raw_order = config.get("slice_order", "ascending")
    order = {"up": "ascending", "down": "descending"}.get(raw_order, raw_order)
    if order not in ("ascending", "descending"):
        logger.warning(f"Unknown slice_order '{raw_order}', using ascending")
        order = "ascending"
    interleaved = bool(config.get("slice_interleaved", True))
    config_mb = config.get("mb_factor")

    session_label = f"_ses-{session}" if session else ""
    logger.info(
        f"Slice timing for sub-{subject}{session_label} "
        f"(order={order}, interleaved={interleaved})"
    )

    bolds = find_files(func_dir, "*_bold.nii.gz")
    if not bolds:
        logger.warning("No BOLD files found"); return

    processed = 0
    for bold in bolds:
        meta = sess.get_json(bold)

        if "RepetitionTime" not in meta:
            logger.warning(f"  {bold.name}: no RepetitionTime, skipping"); continue
        tr = float(meta["RepetitionTime"])

        mb = _resolve_mb_factor(meta, config_mb)

        # multiband (mb>1) should be 2D
        # a single-band 3D scan has no timing
        if mb == 1 and str(meta.get("MRAcquisitionType", "")).upper() == "3D":
            logger.info(f"  {bold.name}: 3D acquisition, SliceTiming not applicable")
            continue

        existing = meta.get("SliceTiming")
        if existing and not force:
            logger.info(
                f"  {bold.name}: scanner SliceTiming present, keeping it "
                f"(use --force to recompute/compare)"
            )
            continue

        try:
            n_slices = nib.load(bold).shape[2]
        except Exception as e:
            logger.error(f"  {bold.name}: cannot read shape: {e}"); continue

        if n_slices % mb != 0:
            logger.error(
                f"  {bold.name}: {n_slices} slices not divisible by mb={mb}, skipping"
            )
            continue

        st = compute_slice_timings(n_slices, tr, mb, order, interleaved)

        if existing and force:
            try:
                max_diff_ms = max(abs(a - b) for a, b in zip(existing, st)) * 1000
                logger.info(
                    f"  {bold.name}: overwriting scanner SliceTiming "
                    f"(max diff {max_diff_ms:.1f} ms vs computed)"
                )
            except Exception:
                pass

        json_f = bold.with_suffix("").with_suffix(".json")
        sess.make_writable(json_f)
        meta["SliceTiming"] = st
        sess.write_json(bold, meta)
        sess.make_readonly(json_f)
        logger.info(
            f"  {bold.name}: SliceTiming set (slices={n_slices}, TR={tr}s, mb={mb})"
        )
        processed += 1

    logger.info(f"Processed {processed} file(s).")
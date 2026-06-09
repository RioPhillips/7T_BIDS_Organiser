"""
linkfmap command. Associate fieldmaps with BOLD runs for fMRIPrep SDC.

Uses the BIDS B0FieldIdentifier / B0FieldSource scheme (the modern
replacement for IntendedFor):
  - each fieldmap-providing file gets a B0FieldIdentifier (a label)
  - each BOLD to be corrected gets a matching B0FieldSource

Targets opposite-PE SE-EPI fieldmaps (PEPOLAR): the dir-AP and dir-PA
epi files of one acquisition share a single B0FieldIdentifier, and the
BOLD points to it. Also populates PhaseEncodingDirection and
TotalReadoutTime on the BOLD JSONs, which fMRIPrep needs for SDC.

TotalReadoutTime is taken from the BOLD's own metadata: dcm2niix's EstimatedTotalReadoutTime is used when
present, falling back to a Philips WFS computation from the BOLD's own
DICOM.

Matching strategy (run-based):
  - one epi field for all BOLDs -> every BOLD references it
  - one epi field per BOLD run  -> matched 1:1 by run number
  - anything else               -> warns and links all BOLDs to the
                                   first field (verify manually)

PhaseEncodingDirection comes from epi_ap_phase_enc_dir in bids7t.yaml
(default 'j-'), kept consistent with fixepi so BOLD and fieldmap
polarities agree.

The GRE B0 fieldmap (suffix 'fieldmap') is left untouched; PEPOLAR is
the default SDC source.
"""

from pathlib import Path
from typing import Optional, Dict, List

import pydicom

from bids7t.core import Session, setup_logging, load_config
from bids7t.core.bids_naming import parse_bids_name


def _phase_map(ap_phase_enc: str) -> Dict[str, str]:
    """{'AP': ped, 'PA': ped} from the configured AP phase-encoding dir."""
    if len(ap_phase_enc) == 2 and ap_phase_enc[1] == '-':
        return {"AP": ap_phase_enc, "PA": ap_phase_enc[0]}
    if len(ap_phase_enc) == 1:
        return {"AP": ap_phase_enc, "PA": ap_phase_enc + "-"}
    return {}


def _run_of(path: Path) -> Optional[str]:
    return parse_bids_name(path.name)['entities'].get('run')


def _dir_of(path: Path) -> Optional[str]:
    return parse_bids_name(path.name)['entities'].get('dir')


def run_linkfmap(studydir: Path, subject: str, session: Optional[str] = None,
                 force: bool = False, verbose: bool = False) -> None:
    sess = Session(studydir, subject, session)
    log_file = sess.paths["logs"] / "linkfmap.log"
    logger = setup_logging("linkfmap", log_file, verbose)

    fmap_dir = sess.paths["fmap"]
    func_dir = sess.paths["func"]
    if not func_dir.exists():
        logger.info("func directory not found, skipping"); return
    if not fmap_dir.exists():
        logger.info("fmap directory not found, skipping"); return

    try:
        config = load_config(studydir) or {}
    except Exception:
        config = {}
    ped_map = _phase_map(config.get("epi_ap_phase_enc_dir", "j-"))
    if not ped_map:
        logger.error("Invalid epi_ap_phase_enc_dir in config"); return

    session_label = f"_ses-{session}" if session else ""
    logger.info(f"Linking fieldmaps to BOLD for sub-{subject}{session_label}")

    bolds = sess.find_by_suffix("func", "bold", include_dcm2niix=False)
    epis = sess.find_by_suffix("fmap", "epi", include_dcm2niix=False)
    if not bolds:
        logger.info("No BOLD files found, nothing to link"); return
    if not epis:
        logger.warning("No SE-EPI (epi) fieldmaps found; cannot set up PEPOLAR")
        return

    # group epi files into PEPOLAR fields by run number (AP+PA of a run)
    fields: Dict[str, List[Path]] = {}
    for f in epis:
        fields.setdefault(_run_of(f) or "1", []).append(f)
    field_runs = sorted(fields.keys())
    bold_runs = sorted({_run_of(b) or "1" for b in bolds})

    field_identifier: Dict[str, str] = {}
    bold_identifier: Dict[str, str] = {}

    if len(field_runs) == 1:
        ident = "pepolar"
        field_identifier[field_runs[0]] = ident
        bold_identifier = {r: ident for r in bold_runs}
        logger.info(f"One PEPOLAR field for all BOLDs -> '{ident}'")
    elif set(field_runs) == set(bold_runs):
        for r in field_runs:
            field_identifier[r] = f"pepolar{r}"
        bold_identifier = {r: f"pepolar{r}" for r in bold_runs}
        logger.info(f"Matched {len(field_runs)} PEPOLAR fields 1:1 to BOLD runs")
    else:
        ident = "pepolar"
        field_identifier[field_runs[0]] = ident
        bold_identifier = {r: ident for r in bold_runs}
        logger.warning(
            f"Ambiguous fmap/BOLD ratio ({len(field_runs)} epi fields, "
            f"{len(bold_runs)} BOLD runs); linking all BOLDs to field run-"
            f"{field_runs[0]}. Verify this is correct."
        )

    # 1) tag epi fieldmaps with B0FieldIdentifier
    for run, files in fields.items():
        ident = field_identifier.get(run)
        if ident is None:
            continue
        for epi in files:
            _set_keys(sess, epi, {"B0FieldIdentifier": ident}, force, logger)

    # 2) tag BOLDs with B0FieldSource + PhaseEncodingDirection + TotalReadoutTime
    for bold in bolds:
        r = _run_of(bold) or "1"
        updates: Dict = {}

        ident = bold_identifier.get(r)
        if ident is not None:
            updates["B0FieldSource"] = ident

        bdir = _dir_of(bold)
        if bdir in ped_map:
            updates["PhaseEncodingDirection"] = ped_map[bdir]
        else:
            logger.warning(f"  {bold.name}: no recognizable dir- entity, PED not set")

        trt = _resolve_bold_trt(sess, bold, logger)
        if trt is not None:
            updates["TotalReadoutTime"] = trt
        else:
            logger.warning(
                f"  {bold.name}: could not determine TotalReadoutTime "
                f"(no EstimatedTotalReadoutTime in JSON, no DICOM match); left unset"
            )

        _set_keys(sess, bold, updates, force, logger)

    logger.info("Fieldmap linking complete")


def _resolve_bold_trt(sess, bold: Path, logger) -> Optional[float]:
    """
    Determine the BOLD's own TotalReadoutTime.

    Priority:
      1. dcm2niix's EstimatedTotalReadoutTime in the BOLD JSON (ground truth)
      2. an existing TotalReadoutTime in the BOLD JSON
      3. computed from the BOLD's own sourcedata DICOM (Philips WFS formula)
    """
    meta = sess.get_json(bold)
    if "EstimatedTotalReadoutTime" in meta:
        try:
            return float(meta["EstimatedTotalReadoutTime"])
        except (TypeError, ValueError):
            pass
    if "TotalReadoutTime" in meta:
        try:
            return float(meta["TotalReadoutTime"])
        except (TypeError, ValueError):
            pass
    return _trt_from_bold_dicom(sess, bold, logger)


def _trt_from_bold_dicom(sess, bold: Path, logger) -> Optional[float]:
    # Compute TRT from the BOLD's own sourcedata DICOM (Philips WFS formula)
    sourcedata = sess.paths["sourcedata"]
    if not sourcedata.exists():
        return None

    ents = parse_bids_name(bold.name)['entities']
    task = ents.get('task')
    bdir = ents.get('dir')

    # find a func series dir matching this BOLD's task (and dir if present);
    # all runs of a protocol share the readout, so the first match is fine
    candidate = None
    for p in sorted(sourcedata.iterdir()):
        if not p.is_dir():
            continue
        name = p.name.lower()
        if task and task.lower() not in name:
            continue
        if bdir and f"dir-{bdir}".lower() not in name and bdir.lower() not in name:
            continue
        candidate = p
        break

    if candidate is None:
        return None
    dcms = list(candidate.glob("*.dcm")) + list(candidate.glob("*.DCM"))
    if not dcms:
        return None

    try:
        ds = pydicom.dcmread(str(sorted(dcms)[0]), stop_before_pixels=True)
        wfs = ds[0x2001, 0x1022].value   # Water Fat Shift (Philips)
        imf = ds[0x0018, 0x0084].value   # Imaging Frequency
        epf = ds[0x2001, 0x1013].value   # EPI Factor (Philips)
        return (wfs / (imf * 3.4 * (epf + 1))) * epf
    except Exception as e:
        logger.debug(f"Could not compute TRT from DICOM for {bold.name}: {e}")
        return None


def _set_keys(sess, nii_path: Path, updates: Dict, force: bool, logger) -> None:
    if not updates:
        return
    json_f = nii_path.with_suffix("").with_suffix(".json")
    meta = sess.get_json(nii_path)
    if not force and all(meta.get(k) == v for k, v in updates.items()):
        return
    sess.make_writable(json_f)
    meta.update(updates)
    sess.write_json(nii_path, meta)
    sess.make_readonly(json_f)
    kv = ", ".join(f"{k}={v}" for k, v in updates.items())
    logger.info(f"  {nii_path.name}: {kv}")
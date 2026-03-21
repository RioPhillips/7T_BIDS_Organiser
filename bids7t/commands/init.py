"""
init command to initialize BIDS top-level files.

Creates the following files in rawdata/:
  - dataset_description.json
  - README
  - CHANGES
  - participants.json (column descriptions)
  - participants.tsv (header only, populated by src2rawdata)
  - .bidsignore

Also creates per-session scans.json template.
Run once when setting up a new study directory.
"""

import json
from pathlib import Path
from typing import Optional

from bids7t.core import Session, setup_logging


def run_init(
    studydir: Path,
    verbose: bool = False,
    force: bool = False
) -> None:
    """    
    Creates template files in rawdata/ with TODO placeholders.
    Safe to re-run since it only creates files that don't exist,
    unless --force is used.
    """
    studydir = Path(studydir)
    rawdata_root = studydir / "rawdata"
    rawdata_root.mkdir(parents=True, exist_ok=True)
    
    log_dir = studydir / "derivatives" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "init.log"
    logger = setup_logging("init", log_file, verbose)
    
    logger.info(f"Initializing BIDS files in {rawdata_root}")
    
    created = []
    
    # dataset_description.json 
    desc_file = rawdata_root / "dataset_description.json"
    if not desc_file.exists() or force:
        desc = {
            "Name": "TODO: name of the dataset",
            "BIDSVersion": "1.9.0",
            "DatasetDOI": "TODO: eventually a DOI for the dataset",
            "License": "TODO: choose a license, e.g. PDDL (http://opendatacommons.org/licenses/pddl/)",
            "Authors": [
                "TODO:",
                "First1 Last1",
                "First2 Last2",
                "..."
            ],
            "Acknowledgements": "TODO: whom you want to acknowledge",
            "HowToAcknowledge": "TODO: describe how to acknowledge -- either cite a corresponding paper, or just in acknowledgement section",
            "Funding": [
                "TODO",
                "GRANT #1",
                "GRANT #2"
            ],
            "ReferencesAndLinks": [
                "TODO",
                "List of papers or websites"
            ],
            "GeneratedBy": [{
                "Name": "bids7t",
                "Description": "DICOM to BIDS conversion for 7T MRI data"
            }]
        }
        with open(desc_file, "w") as f:
            json.dump(desc, f, indent=2)
        created.append(desc_file.name)
        logger.info(f"  Created {desc_file.name}")
    
    # README 
    readme_file = rawdata_root / "README"
    if not readme_file.exists() or force:
        readme_file.write_text(
            "TODO: Provide description for the dataset -- basic details about the study, "
            "possibly pointing to pre-registration (if public or embargoed)\n"
        )
        created.append(readme_file.name)
        logger.info(f"  Created {readme_file.name}")
    
    # CHANGES 
    changes_file = rawdata_root / "CHANGES"
    if not changes_file.exists() or force:
        changes_file.write_text(
            "0.0.1  Initial data acquired\n"
            "TODOs:\n"
            "\t- verify and possibly extend information in participants.tsv "
            "(see for example http://datasets.datalad.org/?dir=/openfmri/ds000208)\n"
            "\t- fill out dataset_description.json, README, sourcedata/README (if present)\n"
            "\t- provide _events.tsv file for each _bold.nii.gz with onsets of events "
            "(see  '8.5 Task events'  of BIDS specification)\n"
        )
        created.append(changes_file.name)
        logger.info(f"  Created {changes_file.name}")
    
    # .bidsignore 
    ignore_file = rawdata_root / ".bidsignore"
    if not ignore_file.exists() or force:
        ignore_file.write_text("")
        created.append(ignore_file.name)
        logger.info(f"  Created {ignore_file.name}")
    
    # participants.json (column descriptions) 
    pjson_file = rawdata_root / "participants.json"
    if not pjson_file.exists() or force:
        pjson = {
            "participant_id": {
                "Description": "Participant identifier"
            },
            "age": {
                "Description": "Age in years (TODO - verify) as in the initial session, "
                               "might not be correct for other sessions"
            },
            "sex": {
                "Description": "self-rated by participant, M for male/F for female (TODO: verify)"
            },
            "group": {
                "Description": "(TODO: adjust - by default everyone is in control group)"
            }
        }
        with open(pjson_file, "w") as f:
            json.dump(pjson, f, indent=2)
        created.append(pjson_file.name)
        logger.info(f"  Created {pjson_file.name}")
    
    # participants.tsv (header only if new) 
    ptsv_file = rawdata_root / "participants.tsv"
    if not ptsv_file.exists() or force:
        ptsv_file.write_text("participant_id\tage\tsex\tgroup\n")
        created.append(ptsv_file.name)
        logger.info(f"  Created {ptsv_file.name}")
    
    if created:
        logger.info(f"Created {len(created)} BIDS files")
    else:
        logger.info("All BIDS files already exist (use --force to overwrite)")


# scans.json template 
# this is created per-session by src2rawdata, but we define the template here

SCANS_JSON_TEMPLATE = {
    "filename": {
        "Description": "Name of the nifti file"
    },
    "acq_time": {
        "LongName": "Acquisition time",
        "Description": "Acquisition time of the particular scan"
    },
    "operator": {
        "Description": "Name of the operator"
    },
    "randstr": {
        "LongName": "Random string",
        "Description": "md5 hash of UIDs"
    }
}
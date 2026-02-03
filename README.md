# dcm2bids

DICOM to BIDS conversion tools for 7T MRI data.

A CLI toolkit for converting raw DICOM files from 7T MRI scanners to BIDS-compliant directory structures.


## Installation setup

Create a new conda environment

```
conda create -n "dcm2bids" python=3.11
conda install -c conda-forge heudiconv=1.3.3 (if using local heudiconv)
conda install -c conda-forge dcm2niix=1.0.20220720
```


```bash
# from source
conda activate dcm2bids
git clone https://github.com/RioPhillips/7T_BIDS_Organiser.git
pip install -e .

# or with dev dependencies
pip install -e ".[dev]"
```

### Other dependencies
- [FSL](https://fsl.fmrib.ox.ac.uk/fsl/) (for reorientation and slice timing)
- Docker (for BIDS validator and MRIQC)

## Quick Start

### Initialize and configure a new study

- In your target studydirectory create a code/ directory with the following files

#### code/config.json
```bash

{
    "studydir": "/path/to/studydir",
    "heuristic": "/path/to/your/heuristic",
    "epi_ap_phase_enc_dir": "j-",
    "orientation": "LPI",
    "slice_order": "down",
    "slice_direction": 3

}
```
The "orientation" flag uses FreeSurfer LPI, see https://github.com/tknapen/tknapen.github.io/wiki/Anatomical-workflows#coordinate-systems-across-software-packages for more in-depth about this. 

#### code/mp2rage.json
```bash
{
    "RepetitionTimeExcitation": 0.006,     # BIDS flag for TR
    "RepetitionTimePreparation": 5,        # BIDS flag for TRPrep
    "InversionTime": [0.9, 2.0],           # this is the TI-list
    "NumberShots": 128,                    # this is the "SegLength"
    "FlipAngle": [6, 8]                    # this is the FA-list
}

```
This file with BIDS-required metadata for the MP2RAGE-files. When setting up, make sure to change these parameters to fit with the specific protocol used in your study. 

#### Heuristic file

Create `code/heuristic.py` (or use an old one) to match your scanning protocol. See the [heudiconv documentation](https://heudiconv.readthedocs.io/en/latest/heuristics.html) for details.

### Convert a single subject/session

```bash
# Step 1: Import DICOMs to sourcedata
dcm2bids dcm2src \
    --subject S01 \
    --session MR1 \
    --dicom-dir /path/to/dicoms \
    --studydir /path/to/study

# Step 2: Convert to BIDS with heudiconv
dcm2bids src2rawdata \
    --subject S01 \
    --session MR1 \
    --studydir /path/to/study

# Step 3: Fix B1 maps (if applicable)
dcm2bids b1src2rawdata \
    --subject S01 \
    --session MR1 \
    --studydir /path/to/study

# Step 4: Fix anatomical files (MP2RAGE)
dcm2bids fixanat \
    --subject S01 \
    --session MR1 \
    --studydir /path/to/study

# Step 5: Fix fieldmaps
dcm2bids fixfmap \
    --subject S01 \
    --session MR1 \
    --studydir /path/to/study

# Step 6: Fix EPI metadata
dcm2bids fixepi \
    --subject S01 \
    --session MR1 \
    --studydir /path/to/study


# Step 7: Reorient images
dcm2bids reorient \
    --subject S01 \
    --session MR1 \
    --studydir /path/to/study

# Step 8: Slice timing correction
dcm2bids slicetime \
    --subject S01 \
    --session MR1 \
    --studydir /path/to/study

# Step 9: Validate BIDS compliance
dcm2bids validate \
    --subject S01 \
    --session MR1 \
    --studydir /path/to/study
```

### Or run all steps at once

```bash
dcm2bids run-all \
    --subject S01 \
    --session MR1 \
    --dicom-dir /path/to/dicoms \
    --studydir /path/to/study
```

## Directory Structure

```
studydir/
├── code/
│   ├── config.json          # Study configuration
|   ├── mp2rage.json         # MP2RAGE metadata file
│   └── heuristic.py         # Heudiconv heuristic file
├── sourcedata/
│   └── sub-S01/
│       └── ses-MR1/
│           └── <series_name>/*.dcm
├── rawdata/
│   ├── dataset_description.json
│   ├── participants.tsv
│   └── sub-S01/
│       └── ses-MR1/
│           ├── anat/
│           ├── func/
│           ├── fmap/
│           ├── dwi/
│           └── sub-S01_ses-MR1_scans.tsv
└── derivatives/
    ├── logs/
    │   └── sub-S01/
    │       └── ses-MR1/
    │           ├── dcm2src.log
    │           ├── src2rawdata.log
    │           └── ...
    └── mriqc/
```


## Commands

| Command | Description |
|---------|-------------|
| `dcm2src` | Import DICOMs to sourcedata directory |
| `src2rawdata` | Convert sourcedata to BIDS rawdata using heudiconv |
| `fixanat` | Fix anatomical files (MP2RAGE processing) |
| `fixfmap` | Fix fieldmap files |
| `fixepi` | Fix EPI JSON metadata |
| `b1src2rawdata` | Import B1 map files |
| `reorient` | Reorient images to standard orientation |
| `slicetime` | Slice timing correction |
| `validate` | Run BIDS validator |
| `qc` | Run MRIQC quality control |
| `run-all` | Run all conversion steps in sequence |

## Common Options

All commands support these options:

| Option | Description |
|--------|-------------|
| `--studydir`, `-s` | Path to the BIDS study directory |
| `--subject`, `-sub` | Subject ID (without sub- prefix) |
| `--session`, `-ses` | Session ID (without ses- prefix) |
| `--force`, `-f` | Force overwrite existing files |
| `--verbose`, `-v` | Enable verbose output |

## Batch Processing

Create a bash script to process multiple subjects:

```bash
#!/bin/bash

STUDYDIR=/path/to/study
DICOM_ROOT=/path/to/dicoms

# List of subjects
SUBJECTS=(S01 S02 S03)
SESSIONS=(MR1 MR2)

for SUB in "${SUBJECTS[@]}"; do
    for SES in "${SESSIONS[@]}"; do
        echo "Processing sub-${SUB}_ses-${SES}"
        
        dcm2bids run-all \
            --subject ${SUB} \
            --session ${SES} \
            --dicom-dir ${DICOM_ROOT}/${SUB}/${SES} \
            --studydir ${STUDYDIR}
    done
done
```

## Troubleshooting

### BIDS validation fails

Check the validation log at `derivatives/logs/sub-*/ses-*/validate.log` for details.

### Heudiconv fails

1. Check that your heuristic file matches your protocol
2. Look at the log: `derivatives/logs/sub-*/ses-*/heudiconv.log`
3. Run heudiconv with `-c none` first to inspect the dicominfo.tsv


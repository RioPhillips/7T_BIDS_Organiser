# dcm2bids

DICOM to BIDS conversion tools for 7T MRI data.

A CLI toolkit for converting raw DICOM files from 7T MRI scanners to BIDS-compliant directory structures.


## Installation setup

Create a new conda environment

```
conda create -n "dcm2bids" python=3.11
conda install -c conda-forge heudiconv (if using local heudiconv)
conda install dcm2niix
```


```bash
# from source
pip install -e .

# or with dev dependencies
pip install -e ".[dev]"
```

### Dependencies

- Python 3.9+
- [heudiconv](https://heudiconv.readthedocs.io/)
- [dcm2niix](https://github.com/rordenlab/dcm2niix)
- [FSL](https://fsl.fmrib.ox.ac.uk/fsl/) (for reorientation and slice timing)
- Docker (for BIDS validator and MRIQC) (optional, you can also use local versions)

## Quick Start

### Initialize a new study

```bash
dcm2bids init --studydir /path/to/study --name "My 7T Study"
```

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

# Step 3: Fix anatomical files (MP2RAGE)
dcm2bids fixanat \
    --subject S01 \
    --session MR1 \
    --studydir /path/to/study

# Step 4: Fix fieldmaps
dcm2bids fixfmap \
    --subject S01 \
    --session MR1 \
    --studydir /path/to/study

# Step 5: Fix EPI metadata
dcm2bids fixepi \
    --subject S01 \
    --session MR1 \
    --studydir /path/to/study

# Step 6: Fix B1 maps (if applicable)
dcm2bids b1dcm2rawdata \
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

## Configuration

### code/config.json

```json
{
    "heuristic": "code/heuristic.py",
    "epi_ap_phase_enc_dir": "j-",
    "orientation": "LPI",
    "slice_order": "down",
    "slice_direction": 3
}
```

### Heuristic file

Edit `code/heuristic.py` to match your scanning protocol. See the [heudiconv documentation](https://heudiconv.readthedocs.io/en/latest/heuristics.html) for details.

## Commands

| Command | Description |
|---------|-------------|
| `init` | Initialize a new BIDS study directory |
| `dcm2src` | Import DICOMs to sourcedata directory |
| `src2rawdata` | Convert sourcedata to BIDS rawdata using heudiconv |
| `fixanat` | Fix anatomical files (MP2RAGE processing) |
| `fixfmap` | Fix fieldmap files |
| `fixepi` | Fix EPI JSON metadata |
| `b1dcm2rawdata` | Import B1 map files |
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


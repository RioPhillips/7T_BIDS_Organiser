# bids7t

DICOM to BIDS conversion tools for 7T MRI data.

Converts raw DICOM files from Philips 7T MRI scanners to BIDS-compliant
directory structures using dcm2niix directly. 

## Installation

### Standalone install 

```bash
# 1. Create environment with dcm2niix
conda create -n bids7t python=3.11
conda activate bids7t
conda install -c conda-forge dcm2niix

# 2. Install bids7t
pip install git+https://github.com/RioPhillips/7T_BIDS_Organiser.git
```

Or in one step using the environment file from the repo:

```bash
conda env create -f https://raw.githubusercontent.com/RioPhillips/7T_BIDS_Organiser/main/environment.yml
conda activate bids7t
```

### Dev install

```bash
git clone https://github.com/RioPhillips/7T_BIDS_Organiser.git
cd 7T_BIDS_Organiser
conda create -n bids7t python=3.11
conda activate bids7t
conda install -c conda-forge dcm2niix
pip install -e ".[dev]"
```

### Dependencies

**Included in package:**

| Dependency |
|---------|
| clickCLI framework |
| nibabel |
| numpy |
| pydicom |
| pyyaml |

**Other:**

| Dependency | 
|-----------|
| dcm2niix |
| FSL |
| Docker (For BIDS validator and MRIQC containers)|

The pipeline works without FSL and Docker. The minimum viable setup is just dcm2niix + the Python packages.

## Quick Start

### 1. Set up study directory

```bash
mkdir -p my_study/code
cd my_study
```

### 2. Create `code/bids7t.yaml`

This single file contains study settings and series-to-BIDS mapping rules.
Copy one of the templates below and adjust the `dir_pattern` regexes to
match your sourcedata directory names.

<details>
<summary>Template for single-session Philips 7T study</summary>

```yaml
studydir: /path/to/my_study

epi_ap_phase_enc_dir: "j-"
orientation: LPI
slice_order: down
slice_direction: 3

series:
  - name: MP2RAGE real
    match: {dir_pattern: '\d+_real$', exclude_derived: true}
    target: anat
    suffix: MP2RAGE
    entities: {inv: 1and2, part: real}

  - name: MP2RAGE imag
    match: {dir_pattern: '\d+_imag$', exclude_derived: true}
    target: anat
    suffix: MP2RAGE
    entities: {inv: 1and2, part: imag}

  - name: MP2RAGE magnitude
    match: {dir_pattern: T1w_acq-mp2rage}
    target: anat
    suffix: MP2RAGE
    entities: {inv: 1and2}

  - name: FLAIR
    match: {dir_pattern: FLAIR}
    target: anat
    suffix: FLAIR

  - name: B1 map (dual TR)
    match: {dir_pattern: B1map_dual_TR}
    target: fmap
    suffix: TB1map
    entities: {acq: b1}
    dcm2niix_flags: ["-p", "n"]

  - name: fMRI task
    match: {dir_pattern: fmri_8bars_dir-AP}
    target: func
    suffix: bold
    entities: {task: 8bars, dir: AP}

  - name: DWI AP
    match: {dir_pattern: 'dmri.*dir-AP', exclude_derived: true}
    target: dwi
    suffix: dwi
    entities: {dir: AP}

  - name: DWI PA
    match: {dir_pattern: 'dmri.*dir-PA', exclude_derived: true}
    target: dwi
    suffix: dwi
    entities: {dir: PA}
```
</details>

Full example configs for both 7T049 and 7T079 studies are in the
[examples/](https://github.com/RioPhillips/7T_BIDS_Organiser/tree/main/examples)
directory of the repository.

### 3. Create `code/mp2rage.yaml` (if using MP2RAGE)

```yaml
RepetitionTimeExcitation: 0.006
RepetitionTimePreparation: 5
InversionTime: [0.9, 2.0]
NumberShots: 128
FlipAngle: [6, 8]
```

### 4. Run

```bash
cd /path/to/my_study

# Initialize BIDS scaffolding
bids7t init

# Process a subject
run-all --subject 7T049S14 --dicom-dir /path/to/dicoms

# Process a subjects specific session
run-all --subject S01 --session MR1 --dicom-dir /path/to/dicoms
```

Or step by step:

```bash
dcm2src --subject S01 --dicom-dir /path/to/S01.zip
src2rawdata --subject S01
fixanat --subject S01
fixfmap --subject S01
fixepi --subject S01
reorient --subject S01
slicetime --subject S01
```

## Commands

All commands can be called directly (no prefix needed) or via the `bids7t` group:

| Command | Description |
|---------|-------------|
| `bids7t init` | Create BIDS top-level files (once per study) |
| `dcm2src` | Import DICOMs to sourcedata  |
| `src2rawdata` | Convert sourcedata to BIDS rawdata using dcm2niix |
| `fixanat` | Fix MP2RAGE files (split, mag/phase, metadata) |
| `fixfmap` | Fix fieldmap files (B0, B1/DREAM, GRE naming) |
| `fixepi` | Fix EPI metadata (PhaseEncodingDirection, TotalReadoutTime) |
| `reorient` | Reorient images to a specific orientation |
| `slicetime` | Slice timing correction |
| `run-all` | Run all steps in sequence |
| `bids7t validate` | Run BIDS validator (Docker) |
| `bids7t qc` | Run MRIQC quality control (Docker) |
| `bids7t status` | Show study configuration |

## Common Options

| Option | Description |
|--------|-------------|
| `--studydir`, `-s` | Path to study directory |
| `--subject`, `-sub` | Subject ID (without sub- prefix) |
| `--session`, `-ses` | Session ID (optional, for multi-session studies) |
| `--force`, `-f` | Force overwrite existing files |
| `--verbose`, `-v` | Enable verbose output |

## Session Support

`--session` is optional. Omit it for single-session studies or to do the conversion for all session present in sourcedata/.

**With session:** `src2rawdata --subject S01 --session MR1`
```
rawdata/sub-S01/ses-MR1/anat/sub-S01_ses-MR1_run-1_T1w.nii.gz
```

**Without session:** `src2rawdata --subject 7T049S14`
```
rawdata/sub-7T049S14/anat/sub-7T049S14_run-1_T1w.nii.gz
```

## Series Mapping Reference

Each rule in the `series:` section of `bids7t.yaml` has:

| Field | Required | Description |
|-------|----------|-------------|
| `name` | No | Human-readable label (for logs) |
| `match.dir_pattern` | Yes | Regex matched against sourcedata directory name |
| `match.exclude_derived` | No | Skip if DICOM ImageType contains DERIVED |
| `match.require_derived` | No | Only match if DICOM ImageType contains DERIVED |
| `match.dicom_field` | No | Dict of DICOM field name → regex to check |
| `target` | Yes | BIDS directory: `anat`, `func`, `fmap`, `dwi` |
| `suffix` | Yes | BIDS suffix: `T1w`, `bold`, `TB1map`, `dwi`, etc. |
| `entities` | No | BIDS entities: `{task: 8bars, dir: AP, acq: b1}` |
| `dcm2niix_flags` | No | Extra dcm2niix flags: `["-p", "n"]` |

Run numbers are assigned automatically per unique target+suffix+entities combination.

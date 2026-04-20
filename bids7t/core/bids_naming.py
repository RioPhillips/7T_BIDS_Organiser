"""
BIDS filename parsing and construction utilities.

Provides tools to parse, modify, and construct BIDS-compliant filenames
while preserving user-specified entities from bids7t.yaml.

This solves the problem of fix commands hardcoding entity combinations
instead of respecting what the user configured in their series mapping.

Usage
-----
Parse an existing filename::

    >>> parsed = parse_bids_name('sub-S01_run-1_inv-1and2_desc-EP_MP2RAGE_real.nii.gz')
    >>> parsed['entities']
    {'run': '1', 'inv': '1and2', 'desc': 'EP'}
    >>> parsed['suffix']
    'MP2RAGE'
    >>> parsed['dcm2niix_extra']
    ['real']

Derive a new filename preserving user entities::

    >>> derive_bids_name(
    ...     'sub-S01_run-1_inv-1and2_desc-EP_MP2RAGE.nii.gz',
    ...     inv='1', part='mag')
    'sub-S01_run-1_inv-1_part-mag_desc-EP_MP2RAGE.nii.gz'

Classify dcm2niix multi-output suffixes::

    >>> classify_dcm2niix_output('sub-S01_acq-b1_run-1_TB1map_e1a.nii.gz')
    'b1_map'
"""

from typing import Dict, List, Optional, Set


# ============================================================
# BIDS entity keys in canonical order (BIDS spec appendix)
# ============================================================

BIDS_ENTITY_ORDER: List[str] = [
    'task', 'acq', 'ce', 'trc', 'stain', 'rec', 'dir', 'run',
    'mod', 'echo', 'flip', 'inv', 'mt', 'part', 'proc', 'hemi',
    'space', 'split', 'recording', 'chunk', 'atlas', 'res', 'den',
    'label', 'desc',
]

BIDS_ENTITY_SET: Set[str] = set(BIDS_ENTITY_ORDER)


# ============================================================
# Known BIDS suffixes (covers 7T and general neuroimaging)
# ============================================================

BIDS_SUFFIXES: Set[str] = {
    # Anatomical
    'T1w', 'T2w', 'T1map', 'T2map', 'T2star', 'T2starw',
    'FLAIR', 'UNIT1', 'inplaneT1', 'inplaneT2', 'PDw', 'PDT2',
    'angio', 'defacemask',
    # Quantitative MRI
    'MP2RAGE', 'MPM', 'MTS', 'MTR', 'MEGRE', 'IRT1',
    # Functional
    'bold', 'cbv', 'sbref', 'events', 'physio', 'stim',
    # Diffusion
    'dwi',
    # Fieldmaps
    'epi', 'fieldmap', 'magnitude', 'magnitude1', 'magnitude2',
    'phasediff', 'phase1', 'phase2',
    # B1 maps
    'TB1map', 'TB1SRGE', 'RB1map', 'TB1TFL', 'TB1EPI', 'TB1DAM',
    # Metadata
    'scans', 'sessions',
}


# ============================================================
# Parsing
# ============================================================

def parse_bids_name(filename: str) -> Dict:
    """
    Parse a BIDS filename into its structural components.

    Handles both clean BIDS names and names with dcm2niix-appended
    suffixes (like _real, _e1a, _imaginary).

    Parameters
    ----------
    filename : str
        A BIDS filename (with or without path components).
        Examples:
        - 'sub-S01_ses-MR1_run-1_inv-1and2_desc-EP_MP2RAGE.nii.gz'
        - 'sub-S01_acq-b1_run-1_TB1map_e1a.nii.gz'
        - 'sub-S01_run-1_inv-1and2_part-real_MP2RAGE_real.nii.gz'

    Returns
    -------
    dict
        prefix : str
            'sub-{id}' or 'sub-{id}_ses-{id}'
        entities : dict
            Parsed entity key-value pairs (e.g. {'run': '1', 'inv': '1and2'}).
            Only includes parts with a hyphen that appear before the suffix.
        suffix : str
            The BIDS suffix (e.g. 'MP2RAGE', 'TB1map', 'bold')
        extension : str
            File extension including dot (e.g. '.nii.gz', '.json')
        dcm2niix_extra : list of str
            Parts appended by dcm2niix after the suffix (e.g. ['real'], ['e1', 'ph'])
        non_entity_parts : list of str
            Parts between prefix and suffix that are not entity key-value
            pairs (e.g. ['temp'] from intermediate files)
        filename : str
            The original filename passed in
    """
    # handle Path objects
    filename = str(filename)

    # strip directory components if present
    if '/' in filename:
        filename = filename.rsplit('/', 1)[-1]

    # strip extension
    name = filename
    if name.endswith('.nii.gz'):
        ext = '.nii.gz'
        name = name[:-7]
    elif '.' in name:
        dot_idx = name.rfind('.')
        ext = name[dot_idx:]
        name = name[:dot_idx]
    else:
        ext = ''

    parts = name.split('_')

    # extract prefix: sub-X and optionally ses-Y
    prefix_parts = []
    idx = 0
    if idx < len(parts) and parts[idx].startswith('sub-'):
        prefix_parts.append(parts[idx])
        idx += 1
        if idx < len(parts) and parts[idx].startswith('ses-'):
            prefix_parts.append(parts[idx])
            idx += 1

    prefix = '_'.join(prefix_parts) if prefix_parts else ''
    remaining = parts[idx:]

    # find BIDS suffix: first known suffix scanning left-to-right
    suffix = None
    suffix_idx = None
    for i, part in enumerate(remaining):
        if part in BIDS_SUFFIXES:
            suffix_idx = i
            suffix = part
            break

    # fallback: last part without a hyphen
    if suffix_idx is None:
        for i in range(len(remaining) - 1, -1, -1):
            if '-' not in remaining[i]:
                suffix_idx = i
                suffix = remaining[i]
                break

    # final fallback
    if suffix is None and remaining:
        suffix_idx = len(remaining) - 1
        suffix = remaining[-1]

    # parse entities (parts before suffix with key-value pattern)
    entities = {}
    non_entity_parts = []
    before_suffix = remaining[:suffix_idx] if suffix_idx is not None else remaining
    for part in before_suffix:
        if '-' in part:
            key, _, val = part.partition('-')
            entities[key] = val
        else:
            non_entity_parts.append(part)

    # dcm2niix extras (parts after suffix)
    dcm2niix_extra = []
    if suffix_idx is not None:
        dcm2niix_extra = remaining[suffix_idx + 1:]

    return {
        'prefix': prefix,
        'entities': entities,
        'suffix': suffix or '',
        'extension': ext,
        'dcm2niix_extra': dcm2niix_extra,
        'non_entity_parts': non_entity_parts,
        'filename': filename,
    }


# ============================================================
# Building
# ============================================================

def build_bids_name(prefix: str, entities: Dict[str, str], suffix: str,
                    extension: str = '.nii.gz') -> str:
    """
    Build a BIDS filename from components using canonical entity order.

    Parameters
    ----------
    prefix : str
        Subject/session prefix, e.g. 'sub-S01' or 'sub-S01_ses-MR1'
    entities : dict
        Entity key-value pairs. Keys in BIDS_ENTITY_ORDER are placed
        in canonical order; others are appended alphabetically.
    suffix : str
        BIDS suffix, e.g. 'MP2RAGE', 'TB1map', 'bold'
    extension : str
        File extension including dot (default '.nii.gz')

    Returns
    -------
    str
        Fully constructed BIDS filename.

    Examples
    --------
    >>> build_bids_name('sub-S01', {'run': '1', 'inv': '1', 'desc': 'EP'}, 'MP2RAGE')
    'sub-S01_run-1_inv-1_desc-EP_MP2RAGE.nii.gz'
    """
    parts = [prefix] if prefix else []

    # entities in canonical order first
    added = set()
    for entity_key in BIDS_ENTITY_ORDER:
        if entity_key in entities:
            parts.append(f"{entity_key}-{entities[entity_key]}")
            added.add(entity_key)

    # then any non-standard entities alphabetically
    for key in sorted(entities.keys()):
        if key not in added:
            parts.append(f"{key}-{entities[key]}")

    parts.append(suffix)
    return '_'.join(parts) + extension


# ============================================================
# Deriving new names from existing ones
# ============================================================

def derive_bids_name(source_filename: str,
                     extension: Optional[str] = None,
                     remove_entities: Optional[List[str]] = None,
                     **overrides) -> str:
    """
    Create a new BIDS filename from a source, preserving user entities.

    This is the key function for fix commands: it lets you change
    specific entities (like splitting inv-1and2 -> inv-1) while
    preserving everything the user specified (like desc-EP, acq-custom).

    Parameters
    ----------
    source_filename : str
        Source BIDS filename to derive from.
    extension : str, optional
        Override file extension. If None, keeps source extension.
    remove_entities : list of str, optional
        Entity keys to remove from the derived name.
    **overrides
        Entity or suffix overrides:
        - suffix='magnitude' changes the BIDS suffix
        - Any other key sets/overrides that entity value

    Returns
    -------
    str
        New BIDS filename with user entities preserved.

    Examples
    --------
    Split inv-1and2 while preserving desc::

        >>> derive_bids_name(
        ...     'sub-S01_run-1_inv-1and2_desc-EP_MP2RAGE.nii.gz',
        ...     inv='1', part='mag')
        'sub-S01_run-1_inv-1_part-mag_desc-EP_MP2RAGE.nii.gz'

    Change suffix (TB1map -> magnitude companion)::

        >>> derive_bids_name(
        ...     'sub-S01_acq-dream_run-1_TB1map.nii.gz',
        ...     suffix='magnitude')
        'sub-S01_acq-dream_run-1_magnitude.nii.gz'

    Get the JSON sidecar path for any file::

        >>> derive_bids_name(
        ...     'sub-S01_run-1_MP2RAGE.nii.gz',
        ...     extension='.json')
        'sub-S01_run-1_MP2RAGE.json'

    Remove an entity::

        >>> derive_bids_name(
        ...     'sub-S01_dir-AP_run-1_fieldmap.nii.gz',
        ...     remove_entities=['dir'])
        'sub-S01_run-1_fieldmap.nii.gz'
    """
    parsed = parse_bids_name(source_filename)

    new_entities = dict(parsed['entities'])
    new_suffix = parsed['suffix']
    new_ext = extension if extension is not None else parsed['extension']

    # apply overrides
    for key, val in overrides.items():
        if key == 'suffix':
            new_suffix = str(val)
        else:
            new_entities[key] = str(val)

    # remove specified entities
    if remove_entities:
        for key in remove_entities:
            new_entities.pop(key, None)

    return build_bids_name(parsed['prefix'], new_entities, new_suffix, new_ext)


# ============================================================
# dcm2niix output classification
# ============================================================

def classify_dcm2niix_output(filename: str) -> Optional[str]:
    """
    Classify a dcm2niix output file by its appended suffix.

    dcm2niix appends suffixes like _real, _e1a, _r100 to distinguish
    multi-output series. This function classifies what each output
    represents so fix commands can handle them generically.

    Parameters
    ----------
    filename : str
        BIDS filename possibly with dcm2niix-appended suffixes.

    Returns
    -------
    str or None
        Classification string:

        For TB1map (B1 DREAM) outputs:
        - 'b1_map': The actual B1 field map (_e1a, _r100)
        - 'b1_magnitude': FID/anatomical reference (_e1)
        - 'b1_phase': Phase image (_e1_ph, _ph, etc.)
        - 'b1_intermediate': Other intermediate (_e2, _r20)

        For fieldmap/epi outputs:
        - 'fieldmap_magnitude': Anatomical echo (_e1a)
        - 'fieldmap_main': The fieldmap itself (_e1)
        - 'fieldmap_intermediate': Phase/extra echoes (_e1_ph, _e2)

        For MP2RAGE / general outputs:
        - 'real': Real component (_real)
        - 'imaginary': Imaginary component (_imaginary)
        - 'magnitude': Magnitude image (_magnitude)
        - 'phase': Phase image (_phase)

        - 'unknown': Has dcm2niix extra parts but unrecognized pattern
        - None: No dcm2niix suffix (clean BIDS name)
    """
    parsed = parse_bids_name(filename)
    extra = parsed.get('dcm2niix_extra', [])

    if not extra:
        return None

    # rejoin extras for matching (e.g. ['e1', 'ph'] -> 'e1_ph')
    extra_str = '_'.join(extra)
    suffix = parsed.get('suffix', '')

    # B1-specific patterns
    if suffix == 'TB1map':
        if extra_str in ('e1a', 'r100'):
            return 'b1_map'
        elif extra_str == 'e1':
            return 'b1_magnitude'
        elif extra_str in ('e1_ph', 'e1_pha', 'ph', 'r100_ph', 'r20_ph'):
            return 'b1_phase'
        elif extra_str in ('e2', 'r20'):
            return 'b1_intermediate'

    # fieldmap echo-based patterns
    if suffix in ('fieldmap', 'epi'):
        if extra_str == 'e1a':
            return 'fieldmap_magnitude'
        elif extra_str == 'e1':
            return 'fieldmap_main'
        elif extra_str in ('e1_ph', 'e2', 'e2_ph', 'e1b', 'e1c',
                           'e2a', 'e2b', 'e2c'):
            return 'fieldmap_intermediate'
        # catch any remaining echo variants (e3, e1d, etc.)
        elif extra_str.startswith('e') and extra_str[1:2].isdigit():
            return 'fieldmap_intermediate'

    # general dcm2niix suffixes (any BIDS suffix)
    if extra_str == 'real':
        return 'real'
    elif extra_str == 'imaginary':
        return 'imaginary'
    elif extra_str == 'magnitude':
        return 'magnitude'
    elif extra_str == 'phase':
        return 'phase'

    return 'unknown'


def strip_dcm2niix_suffix(filename: str) -> str:
    """
    Return the clean BIDS filename with dcm2niix extras removed.

    Parameters
    ----------
    filename : str
        Filename possibly with dcm2niix suffixes.

    Returns
    -------
    str
        Clean BIDS filename.

    Examples
    --------
    >>> strip_dcm2niix_suffix('sub-S01_acq-b1_run-1_TB1map_e1a.nii.gz')
    'sub-S01_acq-b1_run-1_TB1map.nii.gz'

    >>> strip_dcm2niix_suffix('sub-S01_run-1_MP2RAGE_real.nii.gz')
    'sub-S01_run-1_MP2RAGE.nii.gz'
    """
    parsed = parse_bids_name(filename)
    return build_bids_name(
        parsed['prefix'], parsed['entities'],
        parsed['suffix'], parsed['extension']
    )


def has_dcm2niix_suffix(filename: str) -> bool:
    """Check if a filename has dcm2niix-appended suffixes."""
    parsed = parse_bids_name(filename)
    return len(parsed.get('dcm2niix_extra', [])) > 0


def entities_match(filename: str, required: Dict[str, str]) -> bool:
    """
    Check if a filename contains all required entity values.

    Parameters
    ----------
    filename : str
        BIDS filename to check.
    required : dict
        Entity key-value pairs that must all be present.
        Use key 'suffix' to also match the BIDS suffix.

    Returns
    -------
    bool
        True if all required entities match.

    Examples
    --------
    >>> entities_match('sub-S01_run-1_inv-1and2_desc-EP_MP2RAGE.nii.gz',
    ...               {'inv': '1and2', 'suffix': 'MP2RAGE'})
    True
    """
    parsed = parse_bids_name(filename)
    for key, val in required.items():
        if key == 'suffix':
            if parsed['suffix'] != val:
                return False
        elif parsed['entities'].get(key) != str(val):
            return False
    return True
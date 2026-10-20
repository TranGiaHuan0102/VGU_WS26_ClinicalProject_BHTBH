# Tropical Disease Dataset Context

## Overview

This demo dataset is located in `Demos/tropical_diseases_dataset`. It contains eight disease-specific subsets derived from MultiCaRe using keyword and case-text filters.

## Structure and contents

Each disease folder contains these six files:

- `cases.csv`: case records with `case_id`, `pmcid`, `gender`, `age`, and `case_text`.
- `cases_with_image.csv` and `cases_without_image.csv`: case subsets divided by image availability.
- `image_metadata.json`: one JSON object per line, with image identifiers, case linkage, caption, image type/subtype, labels, license, and a relative image path.
- `article_metadata.json`: article-level data such as PMCID, DOI, PMID, title, year, authors, journal, link, and license.
- `case_report_citations.json`: citation and indexing data, including keywords and MeSH terms.
- `readme.txt`: filter settings, subset name, creation date, and MultiCaRe version information.

The main linkage is `case_id`: it appears in case rows and image metadata, allowing multiple images to be associated with a case. `pmcid` links cases to article and citation metadata.

## Subset sizes

| Disease | Cases | Cases with image | Cases without image | Image metadata records |
|---|---:|---:|---:|---:|
| Dengue | 83 | 26 | 55 | 97 |
| Leptospirosis | 19 | 5 | 14 | 22 |
| Malaria | 47 | 19 | 26 | 76 |
| Melioidosis | 12 | 10 | 2 | 26 |
| Neurocysticercosis | 18 | 12 | 6 | 54 |
| Scrub typhus | 19 | 7 | 12 | 20 |
| Typhoid | 64 | 17 | 42 | 58 |
| Zika | 12 | 2 | 10 | 4 |
| **Total** | **274** | **98** | **167** | **357** |

The with-image and without-image case counts do not sum to the `cases.csv` count for dengue, malaria, and typhoid. This leaves nine cases unaccounted for in those two split files, so their membership should be checked before relying on them as a complete partition. Image record counts differ from case counts because a case can have multiple images.

## Data available for future agent design

- **Clinical information:** `case_text` provides narrative case details; `gender` and `age` are separate fields.
- **Visual information:** image metadata provides captions and preassigned image labels/types, and points to the corresponding image file.
- **Evidence and provenance:** article and citation metadata provide source references, publication details, keywords, and MeSH terms.
- **Disease subset labels:** folder names identify the filter used to create each subset. They are useful dataset labels, but should not automatically be treated as a definitive diagnosis for every case, especially where case text mentions coinfections or differential diagnoses.

## Data caveats

- Image files are not stored in these disease folders. The metadata paths point to `medical_datasets/<disease>/images/...`; confirm where those files are stored before specifying an image agent's runtime input.
- These are retrospective cases from published reports, not a consistent live-patient intake format.
- Folder disease names describe subset filters; case text may include coinfections, complications, or differential diagnoses.

This document inventories available data for later assignment of agent inputs, outputs, and responsibilities. It does not define an agent workflow or output contract.

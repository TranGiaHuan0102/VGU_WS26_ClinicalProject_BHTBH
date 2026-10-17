import pandas as pd

# Load the target dataset
df = pd.read_csv('cases.csv')

# Cases manually verified to focus on a different condition (e.g., CNS TB, Glioblastoma)
non_ncc_cases = {
    'PMC3579054_01', 'PMC10408627_01', 'PMC12743525_02',
    'PMC12743525_03', 'PMC12743525_04', 'PMC12743525_05',
    'PMC12743525_06', 'PMC3361783_01'
}

failed_ids = set()
passed_ids = set()

for i, row in df.iterrows():
    cid = row['case_id']
    g = str(row['gender']).lower().strip()
    a = str(row['age']).lower().strip()

    # Condition 1: Check for null, unknown, or unspecified demographics
    if g in ['nan', 'unknown', 'unspecified', 'null', ''] or a in ['nan', 'unknown', 'unspecified', 'null', '']:
        failed_ids.add(cid)
        continue

    # Condition 2: Explicitly ruled out, mentioned in passing, or different condition entirely
    if cid in non_ncc_cases:
        failed_ids.add(cid)
        continue

    # Case meets all valid criteria
    passed_ids.add(cid)

# Segregate the dataframe
df_passed = df[df['case_id'].isin(passed_ids)]
df_failed = df[df['case_id'].isin(failed_ids)]

# Generate the two mutually exclusive output CSV files
df_passed.to_csv('neurocysticercosis_passed.csv', index=False)
df_failed.to_csv('neurocysticercosis_failed.csv', index=False)

print(f"Successfully generated 'neurocysticercosis_passed.csv' with {len(df_passed)} cases.")
print(f"Successfully generated 'neurocysticercosis_failed.csv' with {len(df_failed)} cases.")
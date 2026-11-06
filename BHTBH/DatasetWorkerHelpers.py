from pathlib import Path, PurePosixPath
from datasets import Dataset, DatasetDict, List, Image, Value
import pandas as pd
import json
import math
import os

# ======================================================================
# WORKER HELPERS (module-level functions, decoupled from worker)
# ======================================================================
def read_csv(csv_path: Path):
    """Reads a cases CSV (all columns) into a DataFrame."""
    try:
        return pd.read_csv(csv_path)
    except FileNotFoundError:
        return None

def read_case_ids(csv_path: Path) -> list:
    """Reads only the case_id column of a cases CSV and returns it as a list."""
    return pd.read_csv(csv_path, usecols=["case_id"])["case_id"].tolist()

def read_json(json_path: Path):
    try:
        json_df = pd.read_json(json_path, lines=True)
    except FileNotFoundError:
        return None
    except Exception:
        with open(json_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        json_df = pd.DataFrame.from_dict(data, orient='index') if isinstance(data, dict) else pd.DataFrame(data)
    return json_df

def iter_image_metadata(metadata_path: Path):
    with open(metadata_path, 'r') as file:
        for line in file:
            line_str = line.strip()
            if not line_str:
                continue

            record = json.loads(line_str)
            case_id = record.get("case_id")
            original_path = record.get("file_path", "")

            # Drop the first 2 prefixes of original_path ("medical_dataset/{disease}")
            resolved_path = None
            if original_path:
                relative_parts = PurePosixPath(original_path).parts[2:]
                resolved_path = "/".join(relative_parts)

            yield line_str, case_id, resolved_path

def process_subtractions(target: list, amount: list[list]) -> list:
    """Subtracts multiple lists of items from a target list."""
    result_set = set(target)
    for sub_list in amount:
        result_set -= set(sub_list)
    return list(result_set)

def process_intersections(lists_to_intersect: list[list]) -> list:
    """Intersects a list of items"""
    if not lists_to_intersect:
        return []

    common_elements = set(lists_to_intersect[0])
    for lst in lists_to_intersect[1:]:
        common_elements &= set(lst)
    return list(common_elements)

def delete_trash(disease_path: Path, excluded_file: Path) -> None:
    """Deletes all .csv and .txt files that is not excluded_file."""
    for file in disease_path.iterdir():
        if file.is_file():
            # Target .csv, .txt, and .text files
            if file.suffix.lower() in [".csv", ".txt", ".text"]:
                if file.name.lower() != excluded_file.name.lower():
                    try:
                        file.unlink()
                        print(f"Deleted: {file.name}")
                    except Exception as e:
                        print(f"Failed to delete {file.name}: {e}")

def write_query(text_path: Path, cases_df: pd.DataFrame, disease: str) -> None:
    with open(text_path, 'w', encoding='utf-8') as txt_file:
        for i, row in enumerate(cases_df.itertuples(), start=1):
            case_id = getattr(row, 'case_id', 'Unknown ID')
            case_text = getattr(row, 'case_text', 'No text available')

            block = (
                f"Example {i}:\n"
                f"Case ID: {case_id}\n"
                f"Case Report: {case_text}\n"
                f'Question: "Does this patient have {disease}?"\n'
                "\n"
            )
            txt_file.write(block)

def floor_sqrt_block_algorithm(disease_df: pd.DataFrame):
    """
    Sorted-block method:
      1. sort the cases by average_score (ties broken by case_id)
      2. k = floor(sqrt(n)) test cases
      3. cut the sorted list into k consecutive blocks of nearly equal size
      4. the middle case of each block is a test case (the lower one when the
         block has an even size); every other case is a train case
    """
    total_cases = len(disease_df)
    test_cases = math.isqrt(total_cases)  # floor(sqrt(total_cases))
    block_size, extra = divmod(total_cases, test_cases)  # (number of blocks, extras)

    test_ids, start = [], 0

    for i in range(test_cases):  # Every loop yields 1 test_case
        size = block_size + 1 if i < extra else block_size  # the first `extra` blocks get one more
        block = disease_df[start:start + size]
        test_ids.append(block[(size - 1) // 2])
        start += size

    return test_ids


# ======================================================================
# MISCELLANEOUS
# ======================================================================
def get_secret(secret_name: str, env_file: str = "public.env", set_env_var: bool = True) -> str:
    """
    Retrieves a secret/API key by attempting:
    1. Google Colab Secrets (google.colab.userdata)
    2. A local .env file (via python-dotenv)

    Args:
        secret_name: The key name (e.g., 'HF_TOKEN', 'OPENAI_API_KEY').
        env_file: Path to the .env file fallback (default: 'public.env').
        set_env_var: If True, automatically sets os.environ[secret_name] = secret.

    Returns:
        The secret value as a stripped string.

    Raises:
        KeyError: If secret cannot be retrieved from any source.
    """
    # 1. Try Google Colab Secrets
    try:
        from google.colab import userdata
        val = userdata.get(secret_name)
        if val and val.strip():
            secret = val.strip()
            if set_env_var:
                os.environ[secret_name] = secret
            return secret
    except Exception:
        pass  # Not in Colab, secret missing, or permission denied

    # 2. Fall back to .env file
    env_path = Path.cwd() / env_file
    if env_path.is_file():
        try:
            from dotenv import dotenv_values
            val = dotenv_values(env_path).get(secret_name)
            if val and val.strip():
                secret = val.strip()
                if set_env_var:
                    os.environ[secret_name] = secret
                return secret
        except ImportError:
            raise ImportError("python-dotenv is required to read .env files. Run: pip install python-dotenv")

    # Raise clear error if both methods fail
    raise KeyError(
        f"Could not load '{secret_name}' from Colab Secrets or '{env_file}'. "
        "Ensure the secret exists and is populated."
    )

def build_hf_dataset(train_df: pd.DataFrame, test_df : pd.DataFrame) -> DatasetDict:
    """
    Converts a pandas DataFrame into an HF Dataset.

    Requires a train set and a test set. Combines them into a DatasetDict object.
    """
    train_ds = Dataset.from_pandas(train_df.reset_index(drop=True))
    test_ds = Dataset.from_pandas(test_df.reset_index(drop=True))

    return DatasetDict({
        "train": train_ds,
        "test": test_ds
    })

    # ds = ds.cast_column(
    #     "images",
    #     List({"image_path": Image(), "image_id": Value("string")}),
    # )
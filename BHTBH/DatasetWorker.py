from dataclasses import dataclass
from pathlib import Path

import pandas as pd
import os
import DatasetWorkerHelpers
import requests

# ======================================================================
# METADATA (only contains metadata of disease folder)
# ======================================================================
@dataclass(frozen=True)
class DiseasePaths:
    """
    Metadata of one disease folder: knows where everything lives, nothing else.
    Constructed by DatasetWorker, which validates the disease name.
    """
    dataset_path: Path
    disease_name: str

    @property
    def disease_folder(self) -> Path:
        return self.dataset_path / self.disease_name

    @property
    def cases_csv(self) -> Path:
        return self.disease_folder / f"{self.disease_name}_cases.csv"

    @property
    def image_metadata(self) -> Path:
        return self.disease_folder / "image_metadata.json"

    @property
    def result_json(self) -> Path:
        return self.disease_folder / f"{self.disease_name}_result.json"


# ======================================================================
# WORKER (Singleton, mounted on exactly 1 folder at a time, contains porcelain functions)
# ======================================================================
class DatasetWorker:
    """
    Singleton worker that operates on one dataset at a time.

    Do not instantiate directly; use mount_worker(dataset_name).

    A successful mount guarantees that every disease folder contains
    <disease>_cases.csv (a plain cases.csv is renamed during the mount).

    Attributes:
        DATASET_PATH: Path to the currently mounted dataset folder.
        DISEASES: Sorted list of disease folder names in the mounted dataset.
    """
    ROOT = Path(__file__).resolve().parent  # datasets live next to this file

    def __init__(self, dataset_name: str):
        self.DATASET_PATH = None
        self.DISEASES = []
        self.mount(dataset_name)


    # ======================================================================
    # PLUMBING (not meant to be called by notebook)
    # ======================================================================

    # ==================================
    # MOUNTING
    # ==================================
    @classmethod
    def _resolve(cls, dataset_name: str) -> Path:
        """Validates a bare dataset name and returns its path under ROOT."""
        if (
            not isinstance(dataset_name, str)
            or not dataset_name
            or dataset_name in (".", "..")
            or "\\" in dataset_name
            or Path(dataset_name).name != dataset_name
        ):
            raise ValueError(
                f"Invalid dataset name {dataset_name!r}: "
                "only a bare dataset name (no paths) is allowed."
            )

        path = cls.ROOT / dataset_name
        if not path.is_dir():
            raise FileNotFoundError(
                f"Dataset '{dataset_name}' not found. Looked in: {path}"
            )
        return path

    @staticmethod
    def _plan_cases_renames(dataset_path: Path, diseases: list[str]) -> list[tuple[Path, Path]]:
        """
        Phase 1 (read-only): decides which cases.csv files need renaming.
        Raises RuntimeError listing every problem folder if any folder is unusable.
        """
        renames, problems = [], []

        for disease in diseases:
            old_file = dataset_path / disease / "cases.csv"
            new_file = dataset_path / disease / f"{disease}_cases.csv"

            if old_file.exists() and new_file.exists():
                problems.append(f"{disease}: both cases.csv and {new_file.name} exist")
            elif new_file.exists():
                continue  # already normalized
            elif old_file.exists():
                renames.append((old_file, new_file))
            else:
                problems.append(f"{disease}: neither cases.csv nor {new_file.name} found")

        if problems:
            raise RuntimeError(
                "Cannot mount, fix these folders first:\n  " + "\n  ".join(problems)
            )
        return renames

    @staticmethod
    def _apply_cases_renames(renames: list[tuple[Path, Path]]) -> None:
        """Phase 2: performs the renames; on failure, rolls back the finished ones."""
        done = []
        try:
            for old_file, new_file in renames:
                old_file.rename(new_file)
                done.append((old_file, new_file))
        except Exception:
            for old_file, new_file in reversed(done):
                try:
                    new_file.rename(old_file)
                except OSError as e:
                    print(f"Rollback failed for {new_file}: {e}")
            raise

    # ==================================
    # DATA PREPROCESSING
    # ==================================
    def _disease_paths(self, disease_name: str) -> DiseasePaths:
        """Validates the disease name against DISEASES and returns its paths."""
        if disease_name not in self.DISEASES:
            raise ValueError(
                f"Unknown disease {disease_name!r}. "
                f"Dataset '{self.DATASET_PATH.name}' has: {self.DISEASES}"
            )
        return DiseasePaths(self.DATASET_PATH, disease_name)

    def _delete_cases(self, case_ids_to_delete: list | str, disease: str) -> None:
        """
        Deletes cases from the one disease folder described by `paths`.

        Crash-safe and resumable: if the process dies at any point, running the same deletion again finishes the job. The order is:
          1. delete the images
          2. swap in the new image_metadata.json (temp file + os.replace)
          3. swap in the new cases CSV last - the commit point, because the CSV is also where a re-run rediscovers which cases are still to be deleted

        Skips cases whose images cannot be deleted.

        Drops metadata lines of deleted cases when their image was deleted, was already missing, or has no path.
        """

        # Helper function to ensure crash-safety and resumability
        def write_via_temp_and_replace(target: Path, write, encoding: str | None = None) -> None:
            """
            Crash-safe replacement of a file.
            `write(file)` fills <target>.tmp, which is flushed to disk and then swapped
            over `target` in one atomic step (os.replace). A crash leaves either the old
            file or the new one, never a half-written file.
            """
            tmp_path = target.with_name(target.name + ".tmp")
            try:
                with open(tmp_path, 'w', newline='', encoding=encoding) as file:
                    write(file)
                    file.flush()
                    os.fsync(file.fileno())
                os.replace(tmp_path, target)
            except BaseException:  # includes KeyboardInterrupt (e.g. a stopped notebook cell)
                try:
                    tmp_path.unlink(missing_ok=True)  # best-effort cleanup
                except OSError:
                    pass
                raise

        if not isinstance(case_ids_to_delete, list):
            case_ids_to_delete = [case_ids_to_delete]

        if not case_ids_to_delete:
            return

        delete_set = set(case_ids_to_delete)

        # Retrieve all the sauces
        paths = self._disease_paths(disease)
        cases_path =  paths.cases_csv
        image_metadata_path = paths.image_metadata

        cases_df = DatasetWorkerHelpers.read_csv(cases_path)
        case_ids = DatasetWorkerHelpers.read_case_ids(cases_path)
        records = list(DatasetWorkerHelpers.iter_image_metadata(image_metadata_path))  # parses the whole file now

        # ==========================================
        # STEP 1: Delete the images (idempotent)
        # ==========================================
        lines_to_keep = []
        skipped_ids = set()  # cases with an image that could not be deleted

        for raw_line, case_id, relative_img_path in records:
            if case_id in delete_set:
                if relative_img_path:
                    img_path = paths.disease_folder / relative_img_path
                    try:
                        if img_path.is_file():
                            img_path.unlink()
                            print(f"Successfully deleted image: {img_path}")
                        else:
                            print(f"Image not found at: {img_path}. Metadata line dropped.")
                    except Exception as e:
                        print(f"Error deleting image {img_path}: {e}. Case {case_id} is skipped.")
                        skipped_ids.add(case_id)
                        lines_to_keep.append(raw_line + "\n")
                else:
                    print(f"No image path for case {case_id}. Metadata line dropped.")
                continue  # line of a deleted case is not kept (unless retained above)

            # Not a deleted case: keep the exact original line
            lines_to_keep.append(raw_line + "\n")

        # ==========================================
        # STEP 2: Swap in the new image_metadata.json
        # ==========================================
        if len(lines_to_keep) < len(records):
            write_via_temp_and_replace(
                image_metadata_path, lambda file: file.writelines(lines_to_keep)
            )

        # ==========================================
        # STEP 3: Swap in the new cases CSV (commit point)
        # ==========================================
        ids_to_remove = delete_set - skipped_ids

        initial_row_count = len(cases_df)

        # Use the process_subtractions helper to filter the IDs
        ids_to_keep = DatasetWorkerHelpers.process_subtractions(target=case_ids, amount=[list(ids_to_remove)])

        # Filter the dataframe to only include the kept IDs
        df_filtered = cases_df[cases_df['case_id'].isin(ids_to_keep)]

        final_row_count = len(df_filtered)

        if initial_row_count > final_row_count:
            write_via_temp_and_replace(
                cases_path,
                lambda file: df_filtered.to_csv(file, index=False),
                encoding="utf-8",
            )
            print(
                f"Successfully deleted {initial_row_count - final_row_count} case record(s) from CSV for: {disease}")
        else:
            print(f"No matching CSV entries found to delete for: {disease}")

        if skipped_ids:
            print(
                f"{len(skipped_ids)} case(s) skipped in {disease} because an image "
                f"could not be deleted: {list(skipped_ids)}. Run the deletion again to retry."
            )

    @staticmethod
    def _pick_test_cases(disease_df: pd.DataFrame, algorithm) -> list:
        """
        Picks the test case_ids of ONE disease using specified algorithm.

        All supported algorithms can be found in DatasetWorkerHelpers.py
        """

        if disease_df['case_id'].duplicated().any():
            raise ValueError("Duplicate case_id values in one disease.")

        # Sort cases by average score
        ordered_disease_df = (
            disease_df.sort_values(['average_score', 'case_id'])['case_id'].tolist()
        )

        test_ids = algorithm(ordered_disease_df)
        return test_ids

    # ==================================
    # DISEASE ONTOLOGY
    # ==================================
    @staticmethod
    def _find_standardized_disease_name(disease : str, api_key : str):
        # Base URL of UMLS REST API search endpoint
        url = "https://uts-ws.nlm.nih.gov/rest/search/current"

        params = {
            "string" : disease,
            "apiKey" : api_key,
            "page_number" : 1,
        }

        try:
            response = requests.get(url, params=params)
            response.raise_for_status()  # Raise an exception for bad status codes

            data = response.json()

            # Extract the results from the JSON response
            results = data.get("result", {}).get("results", [])

            if not results:
                return None
            return results[0]['name']

        except requests.exceptions.RequestException as e:
            print(f"Error communicating with the UMLS API: {e}")
            return None

    # ==================================================================
    # PORCELAIN (operate on every disease folder of the mounted dataset)
    # ==================================================================
    def mount(self, dataset_name: str) -> None:
        """
        Moves the worker onto a dataset.
        Atomic: if anything fails, the old mount stays and no file is renamed.
        """
        new_path = self._resolve(dataset_name)
        new_diseases = sorted(
            item.name
            for item in new_path.iterdir()
            if item.is_dir() and not item.name.startswith(".")
        )

        renames = self._plan_cases_renames(new_path, new_diseases)   # phase 1
        self._apply_cases_renames(renames)                           # phase 2

        old_path = self.DATASET_PATH
        self.DATASET_PATH = new_path
        self.DISEASES = new_diseases

        summary = (
            f"renamed {len(renames)} cases.csv, "
            f"{len(new_diseases) - len(renames)} already normalized"
        )
        if old_path is None:
            print(f"Worker mounted on: {new_path.name} ({summary})")
        elif old_path == new_path:
            print(f"Worker re-mounted on: {new_path.name} ({summary}; disease list refreshed)")
        else:
            print(f"Worker moved: {old_path.name} -> {new_path.name} ({summary})")

    def delete_unknown_demographics(self) -> dict[str, list]:
        """
        In every disease of the mounted dataset, deletes the cases whose age is NaN or whose gender is NaN/'Unknown' (including their images).

        Returns {disease: [case_id, ...]} with the cases that were really deleted.

        Nothing is deleted unless every disease passes the read-only checks first.
        After that it is resumable: a disease that fails is reported at the end,
        and running the method again retries it (and skips finished ones, whose
        flagged rows are already gone from the CSV).
        """
        def _flag_unknown_demographics(df: pd.DataFrame) -> list:
            """Returns the case_ids where age is NaN or gender is NaN/'Unknown'."""
            mask = (
                    df['age'].isna() |
                    df['gender'].isna() |
                    (df['gender'].astype(str).str.strip().str.lower() == 'unknown')
            )
            return df.loc[mask, 'case_id'].tolist()


        required_columns = {'case_id', 'age', 'gender'}

        # ==========================================
        # PLAN (read-only): nothing is deleted unless every disease checks out
        # ==========================================
        plan, problems = {}, []

        for disease in self.DISEASES:
            paths = self._disease_paths(disease)
            try:
                df = DatasetWorkerHelpers.read_csv(paths.cases_csv)
                for _ in DatasetWorkerHelpers.iter_image_metadata(paths.image_metadata):  # parse check only
                    pass
            except Exception as e:
                problems.append(f"{disease}: {e}")
                continue

            missing = required_columns - set(df.columns)
            if missing:
                problems.append(f"{disease}: missing column(s) {sorted(missing)}")
                continue

            plan[disease] = (paths, _flag_unknown_demographics(df))

        if problems:
            raise RuntimeError(
                "Cannot delete, fix these diseases first:\n  " + "\n  ".join(problems)
            )

        # ==========================================
        # EXECUTE: disease by disease
        # ==========================================
        deleted, skipped, failed = {}, {}, {}

        for disease, (paths, case_ids) in plan.items():
            deleted[disease] = []
            if not case_ids:
                continue

            try:
                self._delete_cases(case_ids, disease=disease)
            except Exception as e:
                failed[disease] = e
                print(f"An error occurred while processing '{disease}': {e}")
                continue

            # Verify against what is really on disk: a flagged case that is
            # still in the CSV was skipped (an image could not be deleted).
            still_there = set(DatasetWorkerHelpers.read_case_ids(paths.cases_csv)) & set(case_ids)
            deleted[disease] = [case_id for case_id in case_ids if case_id not in still_there]
            if still_there:
                skipped[disease] = still_there

        # ==========================================
        # REPORT
        # ==========================================
        total = sum(len(case_ids) for case_ids in deleted.values())
        print(f"\nDeleted {total} case(s) with unknown demographics ")
        for disease, ids in skipped.items():
            print(f"Skipped in {disease} (an image could not be deleted): {list(ids)}")
        if failed:
            print("Failed diseases (run again to retry): " + ", ".join(failed))

        return deleted

    def clean_dataset(self) -> None:
        """Deletes junk files in every disease folder. Can be run safely at the start of each new session."""
        for disease in self.DISEASES:
            paths = self._disease_paths(disease)

            # Never delete cases.csv
            DatasetWorkerHelpers.delete_trash(paths.disease_folder, paths.cases_csv)

    def generate_case_queries(self) -> None:
        """Generates queries.txt for every disease folder. This .txt can then be fed to LLMs for distillation."""
        for disease in self.DISEASES:
            paths = self._disease_paths(disease)

            cases_df = DatasetWorkerHelpers.read_csv(paths.cases_csv)

            txt_path = paths.disease_folder / f"{paths.cases_csv.stem}.txt"

            DatasetWorkerHelpers.write_query(text_path=txt_path, cases_df=cases_df, disease=disease)

            print(f"Successfully formatted {len(cases_df)} queries into {txt_path.name}")

    def attach_scores(self) -> None:
        """ONLY USABLE AFTER PROMPT 3 HAS BEEN USED AND result.json AVAILABLE

        Creates cases_evaluated.csv in every disease folder, by attaching the scores from result.json to cases.csv.
        """
        required_cols = ['case_id', 'case_presentation_score', 'integrative_reasoning_score', 'transparency_score', 'average_score']

        def preprocess_scores(scores_df : pd.DataFrame, metrics):
            # Check if all cols are present
            if not all(col in scores_df.columns for col in metrics):
                return None

            scores_df = scores_df.drop_duplicates(subset=['case_id'])

            # Convert sub-scores to numeric values
            for metric in metrics:
                scores_df[metric] = scores_df[metric].apply(pd.to_numeric, errors='coerce')

            return scores_df


        for disease in self.DISEASES:
            paths = self._disease_paths(disease)

            # Read result.json and normalize scores
            json_df = DatasetWorkerHelpers.read_json(paths.result_json)

            if json_df is None:
                print(f"{paths.result_json.stem} does not exist!")
                continue

            scores_df = preprocess_scores(json_df, metrics=required_cols[1:])

            if scores_df is None:
                print(f"Broken {paths.result_json.stem} because some metrics are missing.")
                continue


            # Load original cases.csv
            cases_df = DatasetWorkerHelpers.read_csv(paths.cases_csv)

            if 'average_score' in cases_df.columns:
                cases_df = cases_df.drop(columns=['average_score'])

            # Merge scores into cases.csv
            merged_df = cases_df.merge(scores_df[required_cols], on='case_id', how='left')
            merged_df = merged_df.dropna()

            merged_df.to_csv(paths.disease_folder / f"{disease}_cases_evaluated.csv", index=False)

            print(f"Successfully attached scores into {paths.cases_csv.stem}. Eval stored in {disease}_cases_evaluated.csv")

    def display_metrics(self) -> pd.DataFrame:
        """ONLY USABLE AFTER PROMPT 3 HAS BEEN USED AND result.json AVAILABLE

        Displays metrics found in cases_evaluated.csv for every disease folder.
        """

        metrics = ['case_presentation_score', 'integrative_reasoning_score', 'transparency_score', 'average_score']

        def get_metrics(eval_df : pd.DataFrame, base_df: pd.DataFrame):
            if not all(col in eval_df.columns for col in metrics):
                return None

            return {
                "avg_presentation": eval_df['case_presentation_score'].mean(),
                "avg_reasoning": eval_df['integrative_reasoning_score'].mean(),
                "avg_transparency": eval_df['transparency_score'].mean(),
                "overall_avg": eval_df['average_score'].mean(),
                "total_cases": len(base_df),
                "rated_cases": len(eval_df)
            }

        def pretty_print_metrics(all_metrics : dict):
            # Convert dictionary to DataFrame
            df = pd.DataFrame.from_dict(all_metrics, orient='index')

            # Rename columns for clarity
            df = df.rename(columns={
                "overall_avg": "Overall (0-5)",
                "avg_presentation": "Presentation",
                "avg_reasoning": "Reasoning",
                "avg_transparency": "Transparency",
                "rated_cases": "Sampled",
                "total_cases": "Total"
            })

            # Add coverage ratio string (e.g., "10/12")
            df["Sample Ratio"] = df["Sampled"].astype(str) + "/" + df["Total"].astype(str)

            # Reorder and format columns
            cols = ["Overall (0-5)", "Presentation", "Reasoning", "Transparency", "Sample Ratio"]
            df = df[cols].round(2)

            return df


        all_diseases_metrics = {}

        for disease in self.DISEASES:
            paths = self._disease_paths(disease)

            eval_df = DatasetWorkerHelpers.read_csv(paths.disease_folder / f"{disease}_cases_evaluated.csv")
            base_df = DatasetWorkerHelpers.read_csv(paths.cases_csv)

            if eval_df is None:
                print(f"Metrics for {disease} not available. Skipping...")
                continue

            # Get metrics of current disease
            single_disease_metrics = get_metrics(eval_df, base_df)

            if single_disease_metrics is None:
                print(f"Certain metrics missing for {disease}. Skipping...")
                continue

            # If all metrics present, append them to master dict
            all_diseases_metrics[disease] = single_disease_metrics

        return pretty_print_metrics(all_metrics=all_diseases_metrics)

    def build_master_dataset(self, api_key : str) -> None:
        all_rows = []

        """ Iterates over all diseases, extracts cases and images, and builds a massive combined cases.csv at the root of worker"""
        for disease in self.DISEASES:
            paths = self._disease_paths(disease)

            # Check that cases have been evaluated
            evaluated_df = DatasetWorkerHelpers.read_csv(paths.disease_folder / f"{disease}_cases_evaluated.csv")

            if evaluated_df is None:
                print(f"Cases inside {disease} have not yet been evaluated. Skipping...")
                continue

            # Find normalized name of disease
            normalized_disease_name = DatasetWorker._find_standardized_disease_name(disease=disease, api_key=api_key)

            if normalized_disease_name is None:
                continue

            # Format the core dataframe
            evaluated_df = evaluated_df[evaluated_df['average_score'] != 0]

            row = pd.DataFrame({
                'case_id': evaluated_df['case_id'],
                'gender': evaluated_df['gender'],
                'age': evaluated_df['age'],
                'case_text': evaluated_df['case_text'],
                'average_score': evaluated_df['average_score'],
                'disease': normalized_disease_name,
            })

            all_rows.append(row)

        # Combine everything and export to root
        combined_df = pd.concat(all_rows, ignore_index=True)

        output_csv = self.DATASET_PATH / "evaluated_cases.csv"
        combined_df.to_csv(output_csv, index=False)

        print(f"Successfully built massive dataset at {output_csv} with {len(combined_df)} total cases.")

    def assign_splits(self, min_cases: int = 30, split_algorithm=DatasetWorkerHelpers.floor_sqrt_block_algorithm):
        """
        Splits the master dataset (evaluated_cases.csv) into (train_df, test_df).
        """
        master_df = DatasetWorkerHelpers.read_csv(self.DATASET_PATH / "evaluated_cases.csv")

        if master_df is None:
            print("Master dataset not available. Run previous steps in notebook first!")
            return None

        included_index, test_index= [], []

        for disease, group in master_df.groupby('disease'):
            test_ids = DatasetWorker._pick_test_cases(disease_df=group, algorithm=split_algorithm)

            included_index.extend(group.index)  # Store all case_ids of disease in included

            test_index.extend(group.index[group['case_id'].isin(test_ids)]) # Pick out some and put in test

        is_included = master_df.index.isin(included_index)
        is_test = master_df.index.isin(test_index)

        test_df = master_df[is_test]
        train_df = master_df[is_included & ~is_test]

        return train_df.reset_index(drop=True), test_df.reset_index(drop=True)


# ======================================================================
# PUBLIC (call this, to start worker)
# ======================================================================
_worker = None  # the one and only worker
def mount_worker(dataset_name: str) -> DatasetWorker:
    """Public entry point: creates the worker on first call, moves it on later calls."""
    global _worker
    if _worker is None:
        _worker = DatasetWorker(dataset_name)
    else:
        _worker.mount(dataset_name)
    return _worker
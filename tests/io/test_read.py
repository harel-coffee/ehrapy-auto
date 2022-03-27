import os
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from ehrapy.anndata.anndata_ext import ColumnNotFoundError
from ehrapy.core.tool_available import shell_command_accessible
from ehrapy.io._read import read_csv, read_h5ad, read_pdf

CURRENT_DIR = Path(__file__).parent
_TEST_PATH = f"{CURRENT_DIR}/test_data_io"
_TEST_PATH_H5AD = f"{CURRENT_DIR}/test_data_io/h5ad"
_TEST_PATH_MULTIPLE = f"{CURRENT_DIR}/test_data_io_multiple"


class TestRead:
    def test_read_csv(self):
        adata = read_csv(dataset_path=f"{_TEST_PATH}/dataset_basic.csv")
        matrix = np.array(
            [[12, 14, 500, False], [13, 7, 330, False], [14, 10, 800, True], [15, 11, 765, True], [16, 3, 800, True]]
        )
        assert adata.X.shape == (5, 4)
        assert (adata.X == matrix).all()
        assert adata.var_names.to_list() == ["patient_id", "los_days", "b12_values", "survival"]
        assert (adata.layers["original"] == matrix).all()
        assert id(adata.layers["original"]) != id(adata.X)

    def test_read_tsv(self):
        adata = read_csv(dataset_path=f"{_TEST_PATH}/dataset_tsv.tsv", sep="\t")
        matrix = np.array(
            [
                [12, 54, 185.34, False],
                [13, 25, 175.39, True],
                [14, 36, 183.29, False],
                [15, 44, 173.93, True],
                [16, 27, 190.32, True],
            ]
        )
        assert adata.X.shape == (5, 4)
        assert (adata.X == matrix).all()
        assert adata.var_names.to_list() == ["patient_id", "age", "height", "gamer"]
        assert (adata.layers["original"] == matrix).all()
        assert id(adata.layers["original"]) != id(adata.X)

    def test_read_multiple_csv(self):
        adatas = read_csv(dataset_path=f"{_TEST_PATH_MULTIPLE}")
        adata_ids = set(adatas.keys())
        assert all(adata_id in adata_ids for adata_id in {"dataset_non_num_with_missing", "dataset_num_with_missing"})
        assert set(adatas["dataset_non_num_with_missing"].var_names) == {
            "indexcol",
            "intcol",
            "strcol",
            "boolcol",
            "binary_col",
        }
        assert set(adatas["dataset_num_with_missing"].var_names) == {"col" + str(i) for i in range(1, 4)}

    def test_read_multiple_csv_with_obs_only(self):
        adatas = read_csv(
            dataset_path=f"{_TEST_PATH_MULTIPLE}",
            columns_obs_only={"dataset_non_num_with_missing": ["strcol"], "dataset_num_with_missing": ["col1"]},
        )
        adata_ids = set(adatas.keys())
        assert all(adata_id in adata_ids for adata_id in {"dataset_non_num_with_missing", "dataset_num_with_missing"})
        assert set(adatas["dataset_non_num_with_missing"].var_names) == {"indexcol", "intcol", "boolcol", "binary_col"}
        assert set(adatas["dataset_num_with_missing"].var_names) == {"col" + str(i) for i in range(2, 4)}
        assert all(
            obs_name in set(adatas["dataset_non_num_with_missing"].obs.columns) for obs_name in {"datetime", "strcol"}
        )
        assert "col1" in set(adatas["dataset_num_with_missing"].obs.columns)

    def test_read_h5ad(self):
        adata = read_h5ad(dataset_path=f"{_TEST_PATH_H5AD}/dataset9.h5ad")

        assert adata.X.shape == (4, 3)
        assert set(adata.var_names) == {"col" + str(i) for i in range(1, 4)}
        assert set(adata.obs.columns) == set()

    def test_read_multiple_h5ad(self):
        adatas = read_h5ad(dataset_path=f"{_TEST_PATH_H5AD}")
        adata_ids = set(adatas.keys())

        assert all(adata_id in adata_ids for adata_id in {"dataset8", "dataset9"})
        assert set(adatas["dataset8"].var_names) == {"indexcol", "intcol", "boolcol", "binary_col", "strcol"}
        assert set(adatas["dataset9"].var_names) == {"col" + str(i) for i in range(1, 4)}
        assert all(obs_name in set(adatas["dataset8"].obs.columns) for obs_name in {"datetime"})

    def test_read_csv_without_index_column(self):
        adata = read_csv(dataset_path=f"{_TEST_PATH}/dataset_index.csv")
        matrix = np.array(
            [[1, 14, 500, False], [2, 7, 330, False], [3, 10, 800, True], [4, 11, 765, True], [5, 3, 800, True]]
        )
        assert adata.X.shape == (5, 4)
        assert (adata.X == matrix).all()
        assert adata.var_names.to_list() == ["clinic_id", "los_days", "b12_values", "survival"]
        assert (adata.layers["original"] == matrix).all()
        assert id(adata.layers["original"]) != id(adata.X)
        assert list(adata.obs.index) == ["0", "1", "2", "3", "4"]

    def test_read_csv_with_bools_obs_only(self):
        adata = read_csv(dataset_path=f"{_TEST_PATH}/dataset_basic.csv", columns_obs_only=["survival", "b12_values"])
        matrix = np.array([[12, 14], [13, 7], [14, 10], [15, 11], [16, 3]])
        assert adata.X.shape == (5, 2)
        assert (adata.X == matrix).all()
        assert adata.var_names.to_list() == ["patient_id", "los_days"]
        assert (adata.layers["original"] == matrix).all()
        assert id(adata.layers["original"]) != id(adata.X)
        assert set(adata.obs.columns) == {"b12_values", "survival"}
        assert pd.api.types.is_bool_dtype(adata.obs["survival"].dtype)
        assert pd.api.types.is_numeric_dtype(adata.obs["b12_values"].dtype)

    def test_read_csv_with_bools_and_cats_obs_only(self):
        adata = read_csv(
            dataset_path=f"{_TEST_PATH}/dataset_bools_and_str.csv", columns_obs_only=["b12_values", "name", "survival"]
        )
        matrix = np.array([[1, 14], [2, 7], [3, 10], [4, 11], [5, 3]])
        assert adata.X.shape == (5, 2)
        assert (adata.X == matrix).all()
        assert adata.var_names.to_list() == ["clinic_id", "los_days"]
        assert (adata.layers["original"] == matrix).all()
        assert id(adata.layers["original"]) != id(adata.X)
        assert set(adata.obs.columns) == {"b12_values", "survival", "name"}
        assert pd.api.types.is_bool_dtype(adata.obs["survival"].dtype)
        assert pd.api.types.is_numeric_dtype(adata.obs["b12_values"].dtype)
        assert pd.api.types.is_categorical_dtype(adata.obs["name"].dtype)

    @pytest.mark.skipif(
        (os.name != "nt" and not shell_command_accessible(["gs", "-h"]))
        or (os.name == "nt" and not shell_command_accessible(["gswin64c", " -v"])),
        reason="Requires ghostscript to be installed.",
    )
    def test_read_pdf(self):
        adata = read_pdf(dataset_path=f"{_TEST_PATH}/test_pdf.pdf")["test_pdf_0"]
        assert adata.X.shape == (32, 11)
        assert adata.var_names.to_list() == [
            "mpg",
            "cyl",
            "disp",
            "hp",
            "drat",
            "wt",
            "qsec",
            "vs",
            "am",
            "gear",
            "carb",
        ]
        assert id(adata.layers["original"]) != id(adata.X)

    @pytest.mark.skipif(
        (os.name != "nt" and not shell_command_accessible(["gs", "-h"]))
        or (os.name == "nt" and not shell_command_accessible(["gswin64c", " -v"])),
        reason="Requires ghostscript to be installed.",
    )
    def test_read_pdf_no_index(self):
        adata = read_pdf(dataset_path=f"{_TEST_PATH}/test_pdf.pdf")["test_pdf_1"]
        assert adata.X.shape == (6, 5)
        assert adata.var_names.to_list() == [
            "Sepal.Length",
            "Sepal.Width",
            "Petal.Length",
            "Petal.Width",
            "Species",
        ]
        assert id(adata.layers["original"]) != id(adata.X)

    def test_set_default_index(self):
        adata = read_csv(dataset_path=f"{_TEST_PATH}/dataset_index.csv")
        assert adata.X.shape == (5, 4)
        assert not adata.obs_names.name
        assert list(adata.obs.index.values) == [f"{i}" for i in range(5)]

    def test_set_given_str_index(self):
        adata = read_csv(dataset_path=f"{_TEST_PATH}/dataset_basic.csv", index_column="los_days")
        assert adata.X.shape == (5, 3)
        assert adata.obs_names.name == "los_days"
        assert list(adata.obs.index.values) == ["14", "7", "10", "11", "3"]

    def test_set_given_int_index(self):
        adata = read_csv(dataset_path=f"{_TEST_PATH}/dataset_basic.csv", index_column=1)
        assert adata.X.shape == (5, 3)
        assert adata.obs_names.name == "los_days"
        assert list(adata.obs.index.values) == ["14", "7", "10", "11", "3"]

    def test_move_single_column_misspelled(self):
        with pytest.raises(ColumnNotFoundError):
            _ = read_csv(dataset_path=f"{_TEST_PATH}/dataset_basic.csv", columns_obs_only=["b11_values"])  # noqa: F841

    def test_move_single_column_to_obs(self):
        adata = read_csv(dataset_path=f"{_TEST_PATH}/dataset_basic.csv", columns_obs_only=["b12_values"])
        assert adata.X.shape == (5, 3)
        assert list(adata.obs.columns) == ["b12_values"]
        assert "b12_values" not in list(adata.var_names.values)

    def test_move_multiple_columns_to_obs(self):
        adata = read_csv(dataset_path=f"{_TEST_PATH}/dataset_basic.csv", columns_obs_only=["b12_values", "survival"])
        assert adata.X.shape == (5, 2)
        assert list(adata.obs.columns) == ["b12_values", "survival"]
        assert "b12_values" not in list(adata.var_names.values) and "survival" not in list(adata.var_names.values)

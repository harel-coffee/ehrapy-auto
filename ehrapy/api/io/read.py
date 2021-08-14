import warnings
from pathlib import Path
from typing import Generator, Iterable, Iterator, List, NamedTuple, Optional, Union

import numpy as np
import pandas as pd
from anndata import AnnData
from anndata import read as read_h5ad
from rich import print

from ehrapy.api.data.dataloader import Dataloader
from ehrapy.api.io.utility_io import _slugify, is_float, is_int, is_valid_filename, supported_extensions


class BaseDataframes(NamedTuple):
    obs: pd.DataFrame
    df: pd.DataFrame


class DataReader:
    @staticmethod
    def read(
        filename: Union[Path, str],
        extension: Optional[str] = None,
        delimiter: Optional[str] = None,
        index_column: Union[str, Optional[int]] = None,
        columns_obs_only: Optional[List[Union[str]]] = None,
        cache: bool = False,
        backup_url: Optional[str] = None,
    ) -> AnnData:
        """Read file and return :class:`~anndata.AnnData` object.

        To speed up reading, consider passing ``cache=True``, which creates an hdf5 cache file.

        Args:
            filename: Name of the input file to read
            extension: Extension that indicates the file type. If ``None``, uses extension of filename.
            delimiter: Delimiter that separates data within text file. If ``None``, will split at arbitrary number of white spaces,
                       which is different from enforcing splitting at any single white space ``' '``.
            index_column: Name or Index of the column that should be set as index (obs_names in later :class:`~anndata.AnnData` object)
                         If the a string was passed, the so called column is set as index, if it is an integer, the column at that index is set as index.
                         If None was passed, the column at index 0 will be examined if it is the "patient_id" column. If not, a warning will be raised.
            columns_obs_only: If passed, this list contains the name of columns that should be excluded from X, but stored in obs. This may be useful for columns
                              that contain free text information, which may not be useful to perform some algortihms and tools on.
            cache: If `False`, read from source, if `True`, read from fast 'h5ad' cache.
            backup_url: Retrieve the file from an URL if not present on disk.

        Returns:
            An :class:`~anndata.AnnData` object
        """
        file = Path(filename)
        if not file.exists():
            print("[bold yellow]Path or dataset does not yet exist. Attempting to download...")
            output_file_name = backup_url.split("/")[-1]
            is_zip: bool = output_file_name.endswith(".zip")  # TODO can we generalize this to tar files as well?
            Dataloader.download(backup_url, output_file_name=output_file_name, is_zip=is_zip)

        raw_anndata = DataReader._read(
            file,
            extension=extension,
            delimiter=delimiter,
            index_column=index_column,
            columns_obs_only=columns_obs_only,
            cache=cache,
        )

        return raw_anndata

    @staticmethod
    def _read(
        filename: Path,
        extension=None,
        delimiter=None,
        index_column: Union[str, Optional[int]] = None,
        columns_obs_only: Optional[List[Union[str]]] = None,
        cache: bool = False,
        backup_url: Optional[str] = None,
    ) -> AnnData:
        """Internal interface of the read method."""
        if extension is not None and extension not in supported_extensions:
            raise ValueError("Please provide one of the available extensions.\n" f"{supported_extensions}")
        else:
            extension = is_valid_filename(filename, return_ext=True)
        # read hdf5 files
        if extension in {"h5", "h5ad"}:
            return read_h5ad(filename)

        is_present = DataReader._check_datafile_present_and_download(filename, backup_url=backup_url)
        if not is_present:
            print(f"[bold red]Unable to find original file {filename}")
        # TODO REPLACE WITH SETTINGS cachedir
        path_cache = Path.cwd() / _slugify(filename).replace("." + extension, ".h5ad")  # type: Path
        if path_cache.suffix in {".gz", ".bz2"}:
            path_cache = path_cache.with_suffix("")
        if cache and path_cache.is_file():
            return read_h5ad(path_cache)

        if not is_present:
            raise FileNotFoundError(f"Did not find file {filename}.")

        # do the actual reading
        if extension in {"csv", "tsv"}:
            raw_anndata = DataReader.read_csv(filename, delimiter, index_column, columns_obs_only)
        elif extension in {"txt", "tab", "data"}:
            raw_anndata = DataReader.read_text(filename, delimiter, dtype="object")
        else:
            raise ValueError(f"Unknown extension {extension}.")

        # Caching WIP; not needed for csv/tsv parsing
        if cache and extension not in {"csv", "tsv"}:
            if not path_cache.parent.is_dir():
                path_cache.parent.mkdir(parents=True)
            # write for faster reading when calling the next time
            raw_anndata.write(path_cache)

        return raw_anndata

    @staticmethod
    def read_csv(
        filename: Union[Path, Iterator[str]],
        delimiter: Optional[str] = ",",
        index_column: Union[str, Optional[int]] = None,
        columns_obs_only: Optional[List[Union[str]]] = None,
    ) -> AnnData:
        """Read `.csv` and `.tsv` file.

        Args:
            filename
                Data file.
            delimiter
                Delimiter that separates data within the file.
            index_column
                Index or name of future index column (obs)
            columns_obs_only
                List of column names, that should be stored in the AnnData object, but instead of being stored in X, they go
                into obs (useful for free-text like values)

        Returns:
            An AnnData object
        """
        # read pandas dataframe
        initial_df = pd.read_csv(filename, delimiter=delimiter)
        # return the raw AnnData object
        return DataReader._df_to_anndata(initial_df, index_column, columns_obs_only)

    @staticmethod
    def read_text(
        filename: Union[Path, Iterator[str]],
        delimiter: Optional[str] = None,
        dtype: str = "float32",
    ) -> AnnData:
        """Read `.txt`, `.tab`, `.data` (text) file.

        Same as :func:`~anndata.read_csv` but with default delimiter `None`.

        Args:
            filename
                Data file, filename or stream.
            delimiter
                Delimiter that separates data within text file. If `None`, will split at
                arbitrary number of white spaces, which is different from enforcing
                splitting at single white space `' '`.
            dtype
                Numpy data type.
        Returns:
            An empty AnnData object
        """
        if not isinstance(filename, (Path, str, bytes)):
            return DataReader._read_text(filename, delimiter, dtype)

        filename = Path(filename)
        with filename.open() as f:
            return DataReader._read_text(f, delimiter, dtype)

    @staticmethod
    def iter_lines(file_like: Iterable[str]) -> Generator[str, None, None]:
        """Helper for iterating only nonempty lines without line breaks"""
        for line in file_like:
            line = line.rstrip("\r\n")
            if line:
                yield line

    @staticmethod
    def _read_text(  # noqa:C901
        f: Iterator[str],
        delimiter: Optional[str],
        dtype: str,
    ) -> AnnData:
        comments: List = []
        data: List = []
        lines: Generator = DataReader.iter_lines(f)
        column_names: List = []
        row_names: List = []
        id_column_avail: bool = False
        # read header and column names
        for line in lines:

            if line.startswith("#"):
                comment = line.lstrip("# ")
                if comment:
                    comments.append(comment)
            else:
                if delimiter is not None and delimiter not in line:
                    raise ValueError(f"Did not find delimiter {delimiter!r} in first line.")
                line_list = line.split(delimiter)
                # the first column might be row names, so check the last
                if not is_float(line_list[-1]):
                    column_names = line_list
                    if "patient_id" == column_names[0].lower():
                        id_column_avail = True
                    # logg.msg("    assuming first line in file stores column names", v=4)
                else:
                    if not is_float(line_list[0]):
                        row_names.append(line_list[0])
                        DataReader._cast_vals_to_numeric(line_list[1:])
                        data.append(np.array(line_list[1:], dtype=dtype))
                    else:
                        DataReader._cast_vals_to_numeric(line_list)
                        data.append(np.array(line_list, dtype=dtype))
                break
        if not column_names:
            # try reading col_names from the last comment line
            if len(comments) > 0:
                # logg.msg("    assuming last comment line stores variable names", v=4)
                column_names_arr = np.array(comments[-1].split())
            # just numbers as col_names
            else:
                # logg.msg("    did not find column names in file", v=4)
                column_names_arr = np.arange(len(data[0])).astype(str)
        column_names_arr = np.array(column_names, dtype=str)
        # read another line to check if first column contains row names or not
        for line in lines:
            line_list = line.split(delimiter)
            if id_column_avail:
                # logg.msg("    assuming first column in file stores row names", v=4)
                row_names.append(line_list[0])
                DataReader._cast_vals_to_numeric(line_list[1:])
                data.append(np.array(line_list[1:], dtype=dtype))
            else:
                DataReader._cast_vals_to_numeric(line_list)
                data.append(np.array(line_list, dtype=dtype))
            break
        # if row names are just integers
        if len(data) > 1 and data[0].size != data[1].size:
            # logg.msg(
            #     "    assuming first row stores column names and first column row names",
            #     v=4,
            # )
            column_names_arr = np.array(data[0]).astype(int).astype(str)
            row_names.append(data[1][0].astype(int).astype(str))
            data = [data[1][1:]]
        # parse the file
        for line in lines:
            line_list = line.split(delimiter)
            if id_column_avail:
                row_names.append(line_list[0])
                DataReader._cast_vals_to_numeric(line_list[1:])
                data.append(np.array(line_list[1:], dtype=dtype))
            else:
                DataReader._cast_vals_to_numeric(line_list)
                data.append(np.array(line_list, dtype=dtype))
        # logg.msg("    read data into list of lists", t=True, v=4)
        # transfrom to array, this takes a long time and a lot of memory
        # but it’s actually the same thing as np.genfromtxt does
        # - we don’t use the latter as it would involve another slicing step
        #   in the end, to separate row_names from float data, slicing takes
        #   a lot of memory and CPU time
        if data[0].size != data[-1].size:
            raise ValueError(
                f"Length of first line ({data[0].size}) is different " f"from length of last line ({data[-1].size})."
            )
        data_arr = np.array(data, dtype=dtype)
        # logg.msg("    constructed array from list of list", t=True, v=4)
        # transform row_names
        if not row_names:
            row_names_arr = np.arange(len(data_arr)).astype(str)
            # logg.msg("    did not find row names in file", v=4)
        else:
            row_names_arr = np.array(row_names)
            for iname, name in enumerate(row_names_arr):
                row_names_arr[iname] = name.strip('"')
        # adapt col_names if necessary
        if column_names_arr.size > data_arr.shape[1]:
            column_names_arr = column_names_arr[1:]
        for iname, name in enumerate(column_names_arr):
            column_names_arr[iname] = name.strip('"')
        return AnnData(
            data_arr,
            obs=dict(obs_names=row_names_arr),
            var=dict(var_names=column_names_arr),
            dtype=dtype,
            layers={"original": data_arr.copy()},
        )

    @staticmethod
    def _df_to_anndata(
        df: pd.DataFrame, index_column: Union[str, Optional[int]], columns_obs_only: Optional[List[Union[str]]]
    ) -> AnnData:
        """Create an AnnData object from the initial dataframe"""
        # set index given or default
        df = DataReader._set_index(df, index_column)
        # move columns from the input dataframe to later obs
        dataframes = DataReader.move_columns_to_obs(df, columns_obs_only)
        X = dataframes.df.to_numpy(copy=True)
        return AnnData(
            X,
            obs=dataframes.obs,
            var=pd.DataFrame(index=list(dataframes.df.columns)),
            dtype="object",
            layers={"original": X.copy()},
        )

    @staticmethod
    def _check_datafile_present_and_download(path: Union[str, Path], backup_url=None) -> bool:
        """Check whether the file is present, otherwise download.

        Args:
            path: Path to the file to check
            backup_url: Backup URL if the file cannot be found and has to be downloaded

        Returns:
            True if the file was present. False if not.
        """
        path = Path(path)
        if path.is_file():
            return True
        if backup_url is None:
            return False
        if not path.parent.is_dir():
            path.parent.mkdir(parents=True)

        Dataloader.download(backup_url, output_file_name=str(path))

        return True

    @staticmethod
    def _set_index(df: pd.DataFrame, index_column: Union[str, Optional[int]]) -> pd.DataFrame:
        """Try to set the index, if any given by the index_column parameter."""
        column_names = list(df.columns)
        if isinstance(index_column, str):
            df = df.set_index(index_column)
        elif isinstance(index_column, int):
            df = df.set_index(column_names[index_column])
        else:
            if "patient_id" == column_names[0]:
                df = df.set_index("patient_id")
            else:
                warnings.warn(
                    "Did not found patient_id column at column 0 and no index column was passed. Using default, numerical indices instead!",
                    IndexColumnWarning,
                )
        return df

    @staticmethod
    def move_columns_to_obs(df: pd.DataFrame, columns_obs_only: Optional[List[Union[str]]]) -> BaseDataframes:
        """
        Move the given columns from the original dataframe (and therefore X) to obs. By doing so, those values will not get lost
        and will be stored in obs, but will not appear in X. This may be useful for textual values like free text.
        """
        if columns_obs_only:
            try:
                obs = df[columns_obs_only].copy()
                obs = obs.set_index(df.index.map(str))
                df = df.drop(columns_obs_only, axis=1)
            # TODO Key error traceback still prints, have no idea why
            except KeyError:
                raise ColumnNotFoundError(
                    "One or more column names passed to column_obs_only were not found in the input data. Make sure you spelled the column names "
                    "correctly."
                )
        else:
            obs = pd.DataFrame(index=df.index.map(str))

        return BaseDataframes(obs, df)

    @staticmethod
    def _cast_vals_to_numeric(row: List[Optional[Union[str, int, float]]]) -> List[Optional[Union[str, int, float]]]:
        """Cast values to numerical datatype if possible.

        Args:
            row: List of values to cast

        Returns:
            A new List of values casted into the appropriate data type
        """
        for idx, val in enumerate(row):
            _is_int = is_int(val)
            if val == "0":
                row[idx] = 0
            elif val == "":
                row[idx] = None
            elif _is_int:
                row[idx] = int(val)
            elif is_float(val):
                row[idx] = float(val)

        return row

    @staticmethod
    def homogeneous_type(sequence):
        """Check, whether all elements in an iterable are of the same type.

        Args:
            sequence: Sequence to check

        Returns:
            True if all elements are of the same type, False otherwise.
        """
        iseq = iter(sequence)
        first_type = type(next(iseq))

        return first_type if all((type(x) is first_type) for x in iseq) else False


class IndexColumnWarning(UserWarning):
    pass


class ColumnNotFoundError(Exception):
    pass

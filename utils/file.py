import os
import shutil
import tempfile
from pathlib import Path


def is_ascii(s: str) -> bool:
    """
    Check if the characters in string, s, are in ASCII, U+0 to U+7F.

    Args:
        s (str): The string to check.

    Returns:
        bool: True if all characters in the string are ASCII, False otherwise.
    """
    return len(s) == len(s.encode())


def fix_text_corruption(filename: str) -> None:
    """
    Fixes text corruption in a file by removing any lines that contain non-ASCII characters
    and have more/less than 5 comma-separated values.

    Args:
        filename (str): The name of the file to fix.

    Returns:
        None
    """
    with tempfile.TemporaryDirectory() as tmpdirname:
        tmp_filename = os.path.join(tmpdirname, "tmp.txt")
        with open(tmp_filename, "w") as f1:
            with open(filename, "r") as f2:
                for line in f2:
                    if len(line.split(",")) == 5 and is_ascii(line):
                        f1.write(line)

        shutil.copyfile(tmp_filename, filename)


def fix_data_corruption_of_latest_two_files(data_directory: str) -> None:
    """
    Fixes data corruption in the two most recent energy files in the specified directory.

    Args:
        data_directory (str): The directory containing the energy files.

    Returns:
        None
    """
    paths = [str(path) for path in sorted(Path(data_directory).iterdir(), key=os.path.getmtime)]
    paths.reverse()

    for i in range(min(2, len(paths))):
        fix_text_corruption(paths[i])


def line_count(filename: str) -> int:
    """
    Counts the number of lines in a file.

    Args:
        filename (str): The path to the file to be counted.

    Returns:
        int: The number of lines in the file.
    """

    def _make_gen(reader):
        b = reader(1024 * 1024)
        while b:
            yield b
            b = reader(1024 * 1024)

    with open(filename, "rb") as f:
        count = sum(buf.count(b"\n") for buf in _make_gen(f.raw.read))
    return count


def has_readings(filename):
    """
    Checks if a file has any readings.

    Args:
        filename (str): The name of the file to check.

    Returns:
        bool: True if the file has readings, False otherwise.
    """
    return os.stat(filename).st_size != 0


# Important: import panda3d as the very first library - otherwise it crashes
import panda3d.core  # noqa

import glob
import sys

from shutil import copyfile
from os.path import isfile, isdir, join, relpath, dirname
from os import makedirs
from common import is_windows, get_output_dir, fatal_error, get_script_dir

# The compiled extension is always called "native".
NATIVE_TARGET = "native"


def find_binary():
    """ Returns the path to the generated binary and pdb file """

    source_file = None
    pdb_file = None
    possible_files = []

    if is_windows():

        # Check the different Configurations
        configurations = ["RelWithDebInfo", "Release"]
        target_file = NATIVE_TARGET + ".pyd"

        for config in configurations:
            possible_files.append(join(get_output_dir(), config, NATIVE_TARGET + ".dll"))

    else:
        target_file = NATIVE_TARGET + ".so"
        possible_files.append(join(get_output_dir(), target_file))

    for file in possible_files:
        if isfile(file):
            source_file = file

            pdb_name = file.replace(".so", ".pdb").replace(".dll", ".pdb")
            if isfile(pdb_name):
                pdb_file = pdb_name

    return source_file, pdb_file, target_file

if __name__ == "__main__":

    if len(sys.argv) != 2:
        fatal_error("Usage: finalize.py <module-name>")

    MODULE_NAME = sys.argv[1]
    source_file, pdb_file, target_file = find_binary()
    target_pdb_file = NATIVE_TARGET + ".pdb"

    if not source_file:
        fatal_error("Failed to find generated binary!")

    dest_folder = join(get_script_dir(), "..")
    pkg_folder = join(dest_folder, MODULE_NAME)

    # Create the Python package directory
    if not isdir(pkg_folder):
        makedirs(pkg_folder)

    # Copy the native extension into the package
    copyfile(source_file, join(pkg_folder, target_file))

    # Copy the PDB if it was generated
    if pdb_file:
        copyfile(pdb_file, join(pkg_folder, target_pdb_file))

    # Copy any .py files from source/ into the package
    source_dir = join(dest_folder, "source")
    for py_file in glob.glob(join(source_dir, "**", "*.py"), recursive=True):
        rel = relpath(py_file, source_dir)
        dest_path = join(pkg_folder, rel)
        dest_dir = dirname(dest_path)
        if not isdir(dest_dir):
            makedirs(dest_dir)
        copyfile(py_file, dest_path)

    # Generate __init__.py that re-exports the native extension
    init_path = join(pkg_folder, "__init__.py")
    with open(init_path, "w", encoding="utf-8") as f:
        f.write("from .native import *  # noqa: F401,F403\n")

    sys.exit(0)

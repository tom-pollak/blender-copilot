import os
import sys
import subprocess
import pkg_resources
from pathlib import Path

# The folder containing this file
addon_path = Path(__file__).parent

# Our requirements file
requirements_txt = addon_path / 'requirements.txt'

# Local folder into which we install the packages
deps_path = addon_path / 'deps_public'

# Make sure Python can find deps_path
sys.path.append(os.fspath(deps_path))


class Dependencies:
    _checked = None
    _requirements = None

    @staticmethod
    def install():
        """Installs the dependencies from requirements.txt into deps_public."""
        if Dependencies.check():
            return True

        # Create folder if it doesn't exist
        try:
            deps_path.mkdir(exist_ok=True)
        except Exception as e:
            print(f"[Dependencies] Could not create folder: {deps_path} -> {e}")
            return False

        # Ensure pip is available
        try:
            subprocess.check_call([sys.executable, "-m", "ensurepip", "--upgrade"])
        except subprocess.CalledProcessError as e:
            print(f"[Dependencies] Failed to run ensurepip: {e}")
            return False

        # Install from requirements.txt
        try:
            cmd = [
                sys.executable,
                "-m",
                "pip",
                "install",
                "--target",
                os.fspath(deps_path),
                "-r",
                os.fspath(requirements_txt),
            ]
            print(f"[Dependencies] Installing: {cmd}")
            subprocess.check_call(cmd)
        except subprocess.CalledProcessError as e:
            print(f"[Dependencies] pip install error: {e}")
            return False

        return Dependencies.check(force=True)

    @staticmethod
    def check(*, force=False):
        """Returns True if all required packages are installed in deps_path."""
        if force:
            Dependencies._checked = None
        elif Dependencies._checked is not None:
            return Dependencies._checked

        Dependencies._checked = False
        if deps_path.exists():
            try:
                ws = pkg_resources.WorkingSet(entries=[os.fspath(deps_path)])
                # Make sure each requirement is satisfied
                for dep in Dependencies.requirements(force=force):
                    ws.require(dep)
                Dependencies._checked = True
            except Exception as e:
                print(f"[Dependencies] Missing or incompatible packages: {e}")

        return Dependencies._checked

    @staticmethod
    def requirements(*, force=False):
        """Parses requirements.txt for a list of required libraries."""
        if force:
            Dependencies._requirements = None
        if Dependencies._requirements is not None:
            return Dependencies._requirements

        with requirements_txt.open() as fh:
            deps = pkg_resources.parse_requirements(fh)
            Dependencies._requirements = [str(dep) for dep in deps]

        return Dependencies._requirements

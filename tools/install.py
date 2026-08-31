from pathlib import Path

import json
import shutil
import sys
from importlib.metadata import PackageNotFoundError, distribution

from setup_ocr import ensure_ocr_model
from generate_interface import build_interface


working_dir = Path(__file__).parent.parent.resolve()
install_path = working_dir / Path("install")
version = len(sys.argv) > 1 and sys.argv[1] or "v0.0.1"

# the first parameter is self name
if sys.argv.__len__() < 3:
    print("Usage: python install.py <version> <os>")
    print("Example: python install.py v1.0.0 win")
    sys.exit(1)

os_name = sys.argv[2]



def install_resource():

    ensure_ocr_model()

    shutil.copytree(
        working_dir / "assets" / "resource",
        install_path / "resource",
        dirs_exist_ok=True,
    )
    shutil.copytree(
        working_dir / "assets" / "catalog",
        install_path / "catalog",
        dirs_exist_ok=True,
    )
    shutil.copytree(
        working_dir / "assets" / "battle",
        install_path / "battle",
        dirs_exist_ok=True,
    )
    (install_path / "battle" / "profiles").mkdir(parents=True, exist_ok=True)

    interface = build_interface()
    interface["version"] = version
    runner_suffix = ".exe" if os_name == "win" else ""
    interface["agent"] = {
        "child_exec": f"./runtime/MaaSVWB.Agent{runner_suffix}",
        "child_args": [],
    }

    with open(install_path / "interface.json", "w", encoding="utf-8") as f:
        json.dump(interface, f, ensure_ascii=False, indent=4)
        f.write("\n")


def install_chores():
    shutil.copy2(
        working_dir / "assets" / "icon.png",
        install_path / "icon.png",
    )
    shutil.copy2(
        working_dir / "docs" / "release" / "README.md",
        install_path / "README.md",
    )
    shutil.copy2(
        working_dir / "LICENSE",
        install_path,
    )
    licenses_path = install_path / "licenses"
    licenses_path.mkdir(parents=True, exist_ok=True)
    shutil.copy2(
        working_dir / "docs" / "release" / "THIRD_PARTY_NOTICES.md",
        licenses_path / "THIRD_PARTY_NOTICES.md",
    )
    copy_distribution_license(
        "maafw",
        ".dist-info/licenses/LICENSE.md",
        licenses_path / "MaaFramework-LGPL-3.0.md",
    )
    copy_distribution_license(
        "MaaAgentBinary",
        ".dist-info/LICENSE",
        licenses_path / "MaaAgentBinary-AGPL-3.0.txt",
    )
    copy_distribution_license(
        "Pillow",
        ".dist-info/licenses/LICENSE",
        licenses_path / "Pillow-LICENSE.txt",
    )
    copy_distribution_license(
        "numpy",
        ".dist-info/licenses/LICENSE.txt",
        licenses_path / "NumPy-LICENSE.txt",
    )
    copy_distribution_license(
        "pyinstaller",
        ".dist-info/COPYING.txt",
        licenses_path / "PyInstaller-COPYING.txt",
    )

    python_license = Path(sys.base_prefix) / "LICENSE.txt"
    if python_license.is_file():
        shutil.copy2(python_license, licenses_path / "Python-LICENSE.txt")


def copy_distribution_license(
    package: str,
    expected_path: str,
    destination: Path,
) -> None:
    try:
        package_distribution = distribution(package)
    except PackageNotFoundError as exception:
        raise RuntimeError(
            f"Missing packaged dependency for license collection: {package}"
        ) from exception

    normalized_expected = expected_path.replace("\\", "/").lower()
    source = next(
        (
            package_distribution.locate_file(file)
            for file in package_distribution.files or []
            if str(file).replace("\\", "/").lower().endswith(normalized_expected)
        ),
        None,
    )
    source_path = Path(str(source)) if source is not None else None
    if source_path is None or not source_path.is_file():
        raise RuntimeError(f"License file is missing from {package}: {expected_path}")
    shutil.copy2(source_path, destination)


if __name__ == "__main__":
    install_resource()
    install_chores()

    print(f"Install to {install_path} successfully.")

import shutil
import subprocess
import sys
from pathlib import Path


def run(*args):
    return subprocess.check_output([str(arg) for arg in args], text=True)


brew_prefix, package = map(Path, sys.argv[1:])
libdir = package / "lib"
libdir.mkdir()
pending = {binary: binary for binary in (package / "bin").iterdir()}
bundled = {}

while pending:
    original, binary = pending.popitem()
    dependencies = run("otool", "-L", original).splitlines()[1:]
    ids = run("otool", "-D", original).splitlines()[1:]
    for line in dependencies:
        dependency = line.strip().split(" (", 1)[0]
        if dependency in ids:
            continue

        source = Path(dependency)
        if dependency.startswith("@loader_path/"):
            source = original.parent / dependency.removeprefix("@loader_path/")
        if not source.is_relative_to(brew_prefix):
            if dependency.startswith(("/usr/lib/", "/System/Library/")):
                continue
            raise RuntimeError(f"Cannot bundle {dependency} from {original}")

        target = libdir / source.name
        resolved = source.resolve(strict=True)
        if target not in bundled:
            shutil.copy2(resolved, target)
            target.chmod(0o755)
            bundled[target] = resolved
            pending[source] = target
        elif bundled[target] != resolved:
            raise RuntimeError(f"Conflicting libraries for {target.name}")

        relative = target.relative_to(package) if binary.parent != libdir else Path(target.name)
        prefix = "@loader_path/../" if binary.parent != libdir else "@loader_path/"
        replacement = prefix + relative.as_posix()
        if dependency != replacement:
            run("install_name_tool", "-change", dependency, replacement, binary)

    if binary.parent == libdir:
        run("install_name_tool", "-id", f"@loader_path/{binary.name}", binary)
    run("codesign", "--force", "--sign", "-", binary)
    run("codesign", "--verify", binary)

for formula in sorted({source.parent.parent for source in bundled.values()}):
    for license_file in sorted(set(formula.glob("LICENSE*")) | set(formula.glob("COPYING*"))):
        if license_file.is_file():
            shutil.copy2(license_file, package / "licenses" / f"{formula.parent.name}-{license_file.name}")

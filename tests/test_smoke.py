import json
from pathlib import Path

MANIFEST = Path(__file__).resolve().parent.parent / "driver.json"


def test_package_imports():
    from intg_philips_titanos import __version__
    from intg_philips_titanos.driver import PhilipsDriver

    manifest = json.loads(MANIFEST.read_text())
    # Identifier since 1.1.0 (was `philips_titanos_oled`): distinct from the other integration `philips_titanos`.
    assert manifest["driver_id"] == "philips_titanos_ambilight"
    assert PhilipsDriver().driver_id == manifest["driver_id"]
    assert __version__ == manifest["version"]


def test_build_workflow_matches_code():
    """The release workflow validates the package: its assertions must match the code."""
    import re
    import subprocess

    workflow = (MANIFEST.parent / ".github/workflows/build.yml").read_text()
    match = re.search(r"jq -e --arg v \"\$VERSION\" '(?P<filter>[^']+)' artifacts/driver.json", workflow)
    assert match, "jq manifest validation step not found"
    subprocess.run(
        ["python", "-c", "import json,sys; json.load(open(sys.argv[1]))", str(MANIFEST)], check=True
    )
    manifest = json.loads(MANIFEST.read_text())
    assert '"philips_titanos"' not in match.group("filter") or manifest["driver_id"] == "philips_titanos"
    script = re.search(r"python - <<'PY'\n(?P<body>(?:(?!\n\s*PY\n).)*Entity icon.*?)\n\s*PY\n", workflow, re.S)
    assert script, "source validation script not found"
    body = "\n".join(line[10:] if line.startswith(" " * 10) else line for line in script.group("body").splitlines())
    subprocess.run(["python", "-c", body], check=True, cwd=MANIFEST.parent)


def test_custom_icon_is_packaged():
    """Custom logo of the integration and the remote entity: 90×90 PNG (UC doc) at the archive root."""
    import inspect
    import struct

    from intg_philips_titanos.remote import PhilipsRemote

    root = MANIFEST.parent
    assert json.loads(MANIFEST.read_text())["icon"] == "custom:titanos_entite.png"
    assert "custom:titanos_entite.png" in Path(inspect.getfile(PhilipsRemote)).read_text()
    workflow = (root / ".github/workflows/build.yml").read_text()
    archive = next(line for line in workflow.splitlines() if "tar czf" in line)
    data = (root / "assets/titanos_entite.png").read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    assert struct.unpack(">II", data[16:24]) == (90, 90)
    assert "cp assets/titanos_entite.png artifacts/" in workflow
    assert "./titanos_entite.png" in archive

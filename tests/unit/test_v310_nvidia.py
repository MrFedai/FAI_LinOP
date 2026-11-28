"""v3.1.0 O4b (3.4): NVIDIA nvidia_drm.modeset audit — read-only (UNIT TESTED; NATIVE NOT TESTED)."""

from __future__ import annotations

import pytest

from fai_linop.hardware.linux import (GPU, MODESET_NO_MODULE_NOTE, MODESET_OFF_NOTE, Hardware,
                                      modeset_note, modeset_row, nvidia_modeset)

NV = Hardware(gpus=[GPU("nvidia", 0x2684, "0000:01:00.0")])
INTEL = Hardware(gpus=[GPU("intel", 0x4680, "0000:00:02.0")])


def fake_sys(tmp_path, value):
    if value is not None:
        p = tmp_path / "sys/module/nvidia_drm/parameters/modeset"
        p.parent.mkdir(parents=True)
        p.write_text(value)
    return tmp_path


@pytest.mark.parametrize("value,expected", [("Y\n", True), ("1\n", True), ("N\n", False),
                                            ("0\n", False), (None, None)])
def test_nvidia_modeset(tmp_path, value, expected):
    assert nvidia_modeset(fake_sys(tmp_path, value)) is expected


def test_note_no_nvidia_is_none(tmp_path):
    assert modeset_note(INTEL, fake_sys(tmp_path, "N\n")) is None


def test_note_enabled_is_none(tmp_path):
    assert modeset_note(NV, fake_sys(tmp_path, "Y\n")) is None


def test_note_off_mentions_bootloader(tmp_path):
    note = modeset_note(NV, fake_sys(tmp_path, "N\n"))
    assert note == MODESET_OFF_NOTE and "nvidia_drm.modeset=1" in note and "bootloader" in note


def test_note_module_missing(tmp_path):
    assert modeset_note(NV, fake_sys(tmp_path, None)) == MODESET_NO_MODULE_NOTE


def test_doctor_row(tmp_path):
    on, off, none = tmp_path / "on", tmp_path / "off", tmp_path / "none"
    for d in (on, off, none):
        d.mkdir()
    assert modeset_row(NV, fake_sys(on, "Y\n")) == ("NVIDIA DRM modeset", "on")
    assert modeset_row(NV, fake_sys(off, "0\n"))[1] == "OFF (see note)"
    assert modeset_row(NV, none)[1] == "module not loaded"


def test_doctor_row_absent_without_nvidia(tmp_path):
    assert modeset_row(INTEL, tmp_path) is None

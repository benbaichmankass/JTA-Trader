"""scripts/ops/oci_grow_boot_volume.py + vm_grow_root_fs.sh (no OCI / SSH calls).

Operator decision 2026-11-02 "Free +6 GB only": 47 -> 53 GB, never past 53.
"""
from __future__ import annotations

import importlib.util
import pathlib
import subprocess
from types import SimpleNamespace as NS

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("oci_grow_boot_volume", _ROOT / "scripts/ops/oci_grow_boot_volume.py")
m = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(m)

IMDS = {"id": "i", "displayName": "ict-bot-arm", "availabilityDomain": "ad", "compartmentId": "c"}
BV = "bv1"


class FakeApi:
    def __init__(self, cur=47, others=147, limits=6, backups=0, bstates=("CREATING", "AVAILABLE"),
                 state="AVAILABLE", resize_states=("UPDATING", "AVAILABLE")):
        self.size, self.state = cur, state
        self.others, self.limits, self.nbackups = others, limits, backups
        self.bstates, self.rstates = list(bstates), list(resize_states)
        self.backup_created = False
        self.updated = []

    def compartments(self):
        return ["c"]

    def boot_volume_for_instance(self, imds):
        return NS(id=BV, display_name="bv", size_in_gbs=self.size, lifecycle_state=self.state)

    def list_boot_volumes(self, comps):
        return [NS(id=BV, display_name="bv", size_in_gbs=self.size, lifecycle_state=self.state)]

    def list_block_volumes(self, comps):
        return [NS(id="x", display_name="x", size_in_gbs=self.others, lifecycle_state="AVAILABLE")]

    def list_backups(self, comps):
        return [NS(lifecycle_state="AVAILABLE")] * self.nbackups

    def limits_free_available(self):
        return self.limits

    def create_backup(self, bv_id, name):
        self.backup_created = True
        return NS(id="b1", lifecycle_state="REQUEST_RECEIVED")

    def get_backup(self, bid):
        st = self.bstates.pop(0) if len(self.bstates) > 1 else self.bstates[0]
        return NS(id=bid, lifecycle_state=st)

    def update_size(self, bv_id, gb):
        assert self.backup_created, "resize before backup"
        self.updated.append(gb)

    def get_boot_volume(self, bv_id):
        st = self.rstates.pop(0) if len(self.rstates) > 1 else self.rstates[0]
        return NS(lifecycle_state=st, size_in_gbs=53 if st == "AVAILABLE" else 47)


def _run(api, mode="execute", target=53, imds=IMDS):
    t = {"t": 0.0}
    return m.run(api, imds, mode=mode, target=target, backup_timeout_s=300, resize_timeout_s=60,
                 backup_name="n", sleep=lambda s: t.__setitem__("t", t["t"] + s), now=lambda: t["t"])


def test_happy_path_backup_then_resize():
    api = FakeApi()
    assert _run(api) == 0
    assert api.backup_created and api.updated == [53]


def test_plan_never_mutates():
    api = FakeApi()
    assert _run(api, mode="plan") == 0
    assert not api.backup_created and api.updated == []


@pytest.mark.parametrize("target", [54, 100])
def test_target_past_ceiling_refused(target):
    api = FakeApi()
    with pytest.raises(m.Refused) as e:
        _run(api, target=target)
    assert e.value.code == 2 and not api.backup_created and api.updated == []


def test_headroom_below_delta_refused():
    api = FakeApi(others=150)  # 47+150=197 -> 3 GB < 6
    with pytest.raises(m.Refused):
        _run(api)
    assert not api.backup_created and api.updated == []


def test_limits_api_below_delta_refused():
    api = FakeApi(limits=2)
    with pytest.raises(m.Refused):
        _run(api)
    assert api.updated == []


def test_limits_unreadable_does_not_read_as_zero_or_block():
    assert _run(FakeApi(limits=None)) == 0


def test_backup_count_full_refused():
    api = FakeApi(backups=5)
    with pytest.raises(m.Refused):
        _run(api)
    assert not api.backup_created


@pytest.mark.parametrize("final", ["FAULTY", "TERMINATED"])
def test_backup_failed_no_resize(final):
    api = FakeApi(bstates=("CREATING", final))
    with pytest.raises(m.Refused) as e:
        _run(api)
    assert e.value.code == 4 and api.updated == []


def test_backup_timeout_no_resize():
    api = FakeApi(bstates=("CREATING",))
    with pytest.raises(m.Refused) as e:
        _run(api)
    assert e.value.code == 4 and api.updated == []


def test_already_at_target_is_noop():
    api = FakeApi(cur=53, others=147)
    assert _run(api) == 0
    assert not api.backup_created and api.updated == []


def test_resize_never_available_returns_6():
    api = FakeApi(resize_states=("UPDATING",))
    assert _run(api) == 6


def test_wrong_host_refused():
    with pytest.raises(m.Refused):
        _run(FakeApi(), imds={**IMDS, "displayName": "ict-trainer-vm"})


def test_volume_missing_from_enumeration_refused():
    api = FakeApi()
    api.list_boot_volumes = lambda comps: []
    with pytest.raises(m.Refused):
        _run(api)


def test_no_committed_ocid_or_ip():
    for f in ("scripts/ops/oci_grow_boot_volume.py", "scripts/ops/vm_grow_root_fs.sh",
              ".github/workflows/oci-grow-boot-volume.yml"):
        t = (_ROOT / f).read_text()
        assert "ocid1." not in t.replace("ocid1.volume", "")  # no literal OCIDs
        assert "141.145" not in t


SH = _ROOT / "scripts/ops/vm_grow_root_fs.sh"


def test_vm_script_syntax_and_contract():
    subprocess.run(["bash", "-n", str(SH)], check=True)
    t = SH.read_text()
    for needle in ("growpart", "resize2fs", "xfs_growfs", "oracleoci/oraclevda", "device/rescan",
                   "exit 5", "NOPASSWD", "df -T", "ict-trader-live", "ict-web-api"):
        assert needle in t
    assert "reboot" not in t.replace("No reboot", "") and "systemctl restart" not in t

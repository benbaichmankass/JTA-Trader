"""Audit B7: the printed oci-inventory report (posted on a public issue) carries no full OCID."""
import importlib.util
from pathlib import Path

_P = Path(__file__).resolve().parents[1] / "scripts" / "ops" / "oci_inventory.py"
_spec = importlib.util.spec_from_file_location("oci_inventory_b7", _P)
oi = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(oi)


def test_redact_keeps_type_and_tail_only():
    full = "ocid1.instance.oc1.eu-paris-1.anrwiljrabcdefghijklmnop123456"
    out = oi.redact_ocid(full)
    assert out == "ocid1.instance...123456"
    assert "anrwiljr" not in out


def test_non_ocid_values_pass_through():
    assert oi.redact_ocid(None) is None
    assert oi.redact_ocid("ict-bot-arm") == "ict-bot-arm"


def test_main_report_redacts_instances_and_compartment(monkeypatch, capsys):
    tenancy = "ocid1.tenancy.oc1..aaaaaaaasecretsecretsecretXYZ789"
    live = [{"display_name": "a", "shape": "VM.Standard.A1.Flex", "ocpus": 1, "memory_gb": 6,
             "lifecycle_state": "RUNNING", "availability_domain": "AD-1", "time_created": "t",
             "ocid": "ocid1.instance.oc1.eu-paris-1.aaaaaaaafullfullfullQWE111"}]
    monkeypatch.setattr(oi, "fetch_live", lambda c: [dict(r) for r in live])
    monkeypatch.setattr("sys.argv", ["oci_inventory.py", "--compartment-id", tenancy])
    oi.main()
    out = capsys.readouterr().out
    assert "secretsecret" not in out and "fullfullfull" not in out
    assert "ocid1.instance...QWE111" in out and "ocid1.tenancy...XYZ789" in out

"""Build data/pod/: the organiser sample CSVs plus the Pod's own synthetic units (UNIT-P001..P010).

data/pod/ is a drop-in DATA_DIR (same file names as data/sample/). Every Pod row is synthetic ("(DUMMY)" suppliers).
Ground truth for each Pod unit is written by hand in data/pod/labels.json from the scenario, not from agent output.
Re-run:  python scripts/build_pod_data.py
"""
import csv
import json
import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC, DST = ROOT / "data" / "sample", ROOT / "data" / "pod"
sys.path.insert(0, str(ROOT))

A, B = "org_demo_alpha", "org_demo_bravo"


def rcv(n, org, sku, title, variant, comps, co, cr, uo, uc, qo, qr, ident="yes", cdmg="none", udmg="none", flags="",
        supplier="Supplier Pod (DUMMY)"):
    u = f"UNIT-P{n:03d}"
    return {"record_id": f"RCV-P{n:03d}", "unit_id": u, "org_id": org, "po_number": "PO-POD-01", "po_line": str(n),
            "supplier": supplier, "sku": sku, "asin": f"B0PODDUM{n:02d}", "product_title": title, "spec_colour": "n/a",
            "spec_variant": variant, "spec_components": comps, "cartons_ordered": co, "cartons_received": cr,
            "units_per_carton_ordered": uo, "units_per_carton_counted": uc, "qty_ordered": qo, "qty_received": qr,
            "identity_match": ident, "carton_damage": cdmg, "unit_damage": udmg, "quality_flags": flags,
            "photo_refs": f"fixtures/receiving/{u}_carton.jpg", "operator_id": "op_pod", "captured_at": "2026-09-0%dT10:00:00Z" % (n % 9 + 1)}


def prep(n, org, sku):
    u = f"UNIT-P{n:03d}"
    return {"record_id": f"PRP-P{n:03d}", "unit_id": u, "org_id": org, "work_order_id": "WO-POD-1",
            "fba_shipment_id": "FBA-POD-1", "sku": sku, "asin": f"B0PODDUM{n:02d}", "fnsku": f"X00PODDM{n:02d}",
            "prep_price_usd": "0.40", "wo_polybag": "False", "wo_suffocation_warning": "False", "wo_expiry_date": "False",
            "wo_handling_marks": "", "polybag_present_sealed": "not_required", "suffocation_warning": "not_required",
            "fnsku_label_placement": "flat", "original_barcode_covered": "yes", "expiry_date": "not_required",
            "handling_marks": "not_required", "photo_refs": f"fixtures/prep/{u}_label.jpg", "operator_id": "op_pod",
            "captured_at": "2026-09-12T10:00:00Z"}


def pack(n, org, sku):
    u = f"UNIT-P{n:03d}"
    return {"record_id": f"PCK-P{n:03d}", "unit_id": u, "org_id": org, "order_id": f"ORD-POD-{n:03d}", "channel": "shopify",
            "order_lines": f"{sku}:1", "observed_in_box": f"{sku}:1", "operator_verdict": "seal",
            "photo_refs": f"fixtures/pack/{u}_open_box.jpg", "operator_id": "op_pod", "captured_at": "2026-09-13T10:00:00Z"}


def ret(n, org, sku, parts):
    u = f"UNIT-P{n:03d}"
    return {"record_id": f"RTN-P{n:03d}", "unit_id": u, "org_id": org, "order_id": f"ORD-POD-{n:03d}", "ordered_sku": sku,
            "ordered_asin": f"B0PODDUM{n:02d}", "identity_match": "yes", "parts_list": parts, "parts_missing": "",
            "observed_state": "opened_unused", "amazon_condition": "", "operator_disposition": "restock",
            "photo_refs": f"fixtures/returns/{u}_1.jpg", "operator_id": "op_pod", "captured_at": "2026-09-20T10:00:00Z"}


def fee(n, k, org, sku, charge, amount, report="fee_report"):
    return {"line_id": f"FEE-P{n:03d}-{k}", "report_type": report, "unit_id": f"UNIT-P{n:03d}", "org_id": org, "sku": sku,
            "fnsku": f"X00PODDM{n:02d}", "fba_shipment_id": "FBA-POD-1", "order_id": f"ORD-POD-{n:03d}",
            "charge_type": charge, "quantity": "1", "amount_usd": amount, "posted_date": "2026-09-25"}


RECEIVING = [
    rcv(1, A, "SKU-POD-MUG", "Ceramic Mug", "350ml", "mug", 2, 2, 12, 12, 24, 24),                      # clean FBA
    rcv(2, A, "SKU-POD-LAMP", "Desk Lamp", "white", "lamp;bulb", 1, 1, 6, 6, 6, 6),                    # clean MFN
    rcv(3, A, "SKU-POD-SOCK", "Wool Socks", "M", "pair", 2, 2, 12, 10, 24, 20),                        # supplier short
    rcv(4, B, "SKU-POD-VASE", "Glass Vase", "tall", "vase", 1, 1, 4, 4, 4, 4, cdmg="crushing"),        # damaged carton
    rcv(5, A, "SKU-POD-TEE", "Cotton Tee", "blue L", "tee", 1, 1, 12, 12, 12, 12, ident="no", flags="wrong_colour"),
    rcv(6, A, "SKU-POD-PEN", "Gel Pen 10pk", "black", "pens", 2, 2, 24, 24, 48, 48, ident="uncertain"),  # UNCERTAIN
    rcv(7, A, "SKU-POD-BOWL", "Bamboo Bowl", "small", "bowl", 2, 2, 12, 12, 30, 24),                   # PO inconsistent
    rcv(8, A, "SKU-POD-JAR", "Glass Jar", "500ml", "jar;lid", 2, 3, 12, 8, 24, 24),                    # repacked, total ok
    rcv(9, A, "SKU-POD-SOAP", "Bar Soap 3pk", "lavender", "soap x3", 1, 1, 24, 24, 24, 24),            # claim (Prep PASS)
    rcv(10, B, "SKU-POD-HAT", "Sun Hat", "beige", "hat", 1, 1, 6, 6, 6, 6),                            # returned + claim
]
PREP = [prep(1, A, "SKU-POD-MUG"), prep(3, A, "SKU-POD-SOCK"), prep(5, A, "SKU-POD-TEE"), prep(6, A, "SKU-POD-PEN"),
        prep(8, A, "SKU-POD-JAR"), prep(9, A, "SKU-POD-SOAP")]
PACK = [pack(2, A, "SKU-POD-LAMP"), pack(4, B, "SKU-POD-VASE"), pack(7, A, "SKU-POD-BOWL"), pack(10, B, "SKU-POD-HAT")]
RETURNS = [ret(10, B, "SKU-POD-HAT", "hat")]
FEES = [fee(1, 1, A, "SKU-POD-MUG", "fulfilment_fee_weight_tier", "4.25"),
        fee(3, 1, A, "SKU-POD-SOCK", "lost_inbound", "8.00", "inventory_adjustment"),
        fee(9, 1, A, "SKU-POD-SOAP", "inbound_defect_fee", "3.50"),
        fee(10, 1, B, "SKU-POD-HAT", "refund_issued_item_not_returned", "19.99")]

FILES = {"receiving_sample.csv": RECEIVING, "prep_sample.csv": PREP, "pack_sample.csv": PACK,
         "returns_sample.csv": RETURNS, "fee_report_sample.csv": FEES}


def main():
    DST.mkdir(parents=True, exist_ok=True)
    for name, extra in FILES.items():
        with open(SRC / name, newline="", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            fields, rows = reader.fieldnames, list(reader)
        with open(DST / name, "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=fields, lineterminator="\n")
            w.writeheader()
            w.writerows(rows + extra)
    for name in ("README.md",):
        if (SRC / name).exists() and not (DST / "SAMPLE-README.md").exists():
            shutil.copy(SRC / name, DST / "SAMPLE-README.md")
    os.environ["DATA_DIR"] = str(DST)
    from shared.utils import sample_data
    cases = [{"org_id": r["org_id"], "unit_id": r["unit_id"], "route": sample_data.route(r["unit_id"], r["org_id"]),
              "returned": sample_data.has("returns", r["unit_id"], r["org_id"])}
             for r in sample_data.rows("receiving") if r["unit_id"].startswith("UNIT-P")]
    (DST / "cases.json").write_text(json.dumps(cases, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {len(RECEIVING)} pod units -> {DST}")


if __name__ == "__main__":
    main()

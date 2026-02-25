from flask import Blueprint, request, jsonify, Response
import requests
import pandas as pd
import io
import json
import time

# ─── Config ───────────────────────────────────────────────────────────────────
BASE_URL_SERIAL = "https://aquila-user-api.common.cloud.hpe.com/support-assistant/v1alpha1/activate-devices?limit={limit}&page=0&serial_number={devices}"
BASE_URL_MAC    = "https://aquila-user-api.common.cloud.hpe.com/support-assistant/v1alpha1/activate-devices?limit={limit}&page=0&mac_address={devices}"
BATCH_SIZE = 200
SLEEP_SEC  = 0.5
TIMEOUT    = 10

device_bp = Blueprint('device', __name__)

# ─── Helpers ──────────────────────────────────────────────────────────────────
def sort_priority(row):
    folder     = row["Folder Name"]
    is_default = folder == "default"
    is_aruba   = "Aruba Factory" in folder
    if is_default and is_aruba:
        return 0
    elif is_default:
        return 1
    return 2


def process_devices(device_list, lookup_type, extra_headers):
    """
    Non-streaming version used by /api/export.
    Logic mirrors the original Python script exactly.
    """
    base_url = BASE_URL_SERIAL if lookup_type == "serial" else BASE_URL_MAC
    platform_device_records = []
    missing_devices = []

    for batch_start in range(0, len(device_list), BATCH_SIZE):
        batch       = device_list[batch_start: batch_start + BATCH_SIZE]
        devices_str = ",".join(batch)
        url         = base_url.format(limit=len(batch), devices=devices_str)

        print(f"Processing batch {batch_start // BATCH_SIZE + 1} with {len(batch)} devices...")

        try:
            response = requests.get(url, headers=extra_headers, timeout=TIMEOUT)
            response.raise_for_status()
            data         = response.json()
            devices_data = data.get("devices", [])
            received_devices = set()

            for dev in devices_data:
                serial_number = dev.get("serial_number")
                mac_address   = dev.get("mac_address")
                device_type   = dev.get("device_type")
                device_model  = dev.get("device_model")
                part_number   = dev.get("part_number")
                platform_id   = dev.get("platform_customer_id")
                folder_name   = dev.get("folder", {}).get("folder_name", "")

                tracked = (mac_address if lookup_type == "mac" else serial_number) or ""
                if tracked:
                    received_devices.add(tracked.upper())

                if serial_number and mac_address and platform_id and folder_name:
                    platform_device_records.append({
                        "Serial Number": serial_number,
                        "MAC Address":   mac_address,
                        "Device Type":   device_type,
                        "Device Model":  device_model,
                        "Part Number":   part_number,
                        "Folder Name":   folder_name,
                        "Platform ID":   platform_id,
                    })
                else:
                    missing_id = (mac_address if lookup_type == "mac" else serial_number) or "unknown"
                    missing_devices.append(missing_id)

            for dev in batch:
                if dev.upper() not in received_devices:
                    missing_devices.append(dev)

        except requests.exceptions.RequestException as e:
            print(f"Request error on batch {batch_start // BATCH_SIZE + 1}: {e}")
            for dev in batch:
                missing_devices.append(dev)

        print(f"Finished batch {batch_start // BATCH_SIZE + 1}")
        time.sleep(SLEEP_SEC)

    df = pd.DataFrame(platform_device_records)
    if not df.empty:
        df["sort_order"] = df.apply(sort_priority, axis=1)
        df = df.sort_values(by=["sort_order", "Platform ID"])
        df.drop(columns="sort_order", inplace=True)

    return df, missing_devices


# ─── Routes ───────────────────────────────────────────────────────────────────
@device_bp.route("/api/lookup", methods=["POST"])
def lookup():
    body           = request.get_json(force=True)
    raw_input      = body.get("devices", "")
    lookup_type    = body.get("type", "serial")
    parsed_headers = body.get("parsed_headers", {})

    device_list = [d.strip() for d in raw_input.replace("\n", ",").split(",") if d.strip()]
    if not device_list:
        return jsonify({"error": "No devices provided"}), 400

    extra_headers = parsed_headers if parsed_headers else {}
    df, missing   = process_devices(device_list, lookup_type, extra_headers)
    records       = df.to_dict(orient="records") if not df.empty else []

    total         = len(device_list)
    found         = len(records)
    missing_count = len(missing)

    return jsonify({
        "total":         total,
        "found":         found,
        "missing_count": missing_count,
        "found_pct":     round(found / total * 100, 1) if total else 0,
        "missing_pct":   round(missing_count / total * 100, 1) if total else 0,
        "devices":       records,
        "missing":       missing,
    })


@device_bp.route("/api/export", methods=["POST"])
def export():
    body           = request.get_json(force=True)
    raw_input      = body.get("devices", "")
    lookup_type    = body.get("type", "serial")
    parsed_headers = body.get("parsed_headers", {})
    export_type    = body.get("export", "found")
    columns        = body.get("columns", None)

    device_list   = [d.strip() for d in raw_input.replace("\n", ",").split(",") if d.strip()]
    extra_headers = parsed_headers if parsed_headers else {}

    df, missing = process_devices(device_list, lookup_type, extra_headers)

    COL_ORDER = ['Serial Number', 'MAC Address', 'Device Type', 'Device Model', 'Part Number', 'Folder Name', 'Platform ID']

    if export_type == "missing":
        out_df = pd.DataFrame({"Missing Device": missing})
    else:
        out_df = df if not df.empty else pd.DataFrame()
        if columns and not out_df.empty:
            valid_cols = [c for c in COL_ORDER if c in columns and c in out_df.columns]
            if valid_cols:
                out_df = out_df[valid_cols]

    buf = io.StringIO()
    out_df.to_csv(buf, index=False)

    return Response(
        buf.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename={export_type}_devices.csv"}
    )


@device_bp.route("/api/lookup-stream", methods=["POST"])
def lookup_stream():
    body           = request.get_json(force=True)
    raw_input      = body.get("devices", "")
    lookup_type    = body.get("type", "serial")
    parsed_headers = body.get("parsed_headers", {})

    device_list = [d.strip() for d in raw_input.replace("\n", ",").split(",") if d.strip()]
    if not device_list:
        return jsonify({"error": "No devices provided"}), 400

    extra_headers = parsed_headers if parsed_headers else {}
    base_url      = BASE_URL_SERIAL if lookup_type == "serial" else BASE_URL_MAC
    total_devices = len(device_list)
    total_batches = (total_devices + BATCH_SIZE - 1) // BATCH_SIZE

    def generate():
        platform_device_records = []
        missing_devices         = []

        for batch_idx, batch_start in enumerate(range(0, total_devices, BATCH_SIZE)):
            batch       = device_list[batch_start: batch_start + BATCH_SIZE]
            devices_str = ",".join(batch)
            url         = base_url.format(limit=len(batch), devices=devices_str)
            batch_num   = batch_idx + 1

            pct = round((batch_start / total_devices) * 100)
            yield f"data: {json.dumps({'type':'progress','pct':pct,'queried':batch_start,'total':total_devices,'found':len(platform_device_records),'batch':batch_num,'total_batches':total_batches})}\n\n"

            print(f"Processing batch {batch_num}/{total_batches} with {len(batch)} devices...")

            try:
                response = requests.get(url, headers=extra_headers, timeout=TIMEOUT)
                response.raise_for_status()
                data         = response.json()
                devices_data = data.get("devices", [])
                received_devices = set()

                for dev in devices_data:
                    serial_number = dev.get("serial_number")
                    mac_address   = dev.get("mac_address")
                    device_type   = dev.get("device_type")
                    device_model  = dev.get("device_model")
                    part_number   = dev.get("part_number")
                    platform_id   = dev.get("platform_customer_id")
                    folder_name   = dev.get("folder", {}).get("folder_name", "")

                    tracked = (mac_address if lookup_type == "mac" else serial_number) or ""
                    if tracked:
                        received_devices.add(tracked.upper())

                    if serial_number and mac_address and platform_id and folder_name:
                        platform_device_records.append({
                            "Serial Number": serial_number,
                            "MAC Address":   mac_address,
                            "Device Type":   device_type,
                            "Device Model":  device_model,
                            "Part Number":   part_number,
                            "Folder Name":   folder_name,
                            "Platform ID":   platform_id,
                        })
                    else:
                        missing_id = (mac_address if lookup_type == "mac" else serial_number) or "unknown"
                        missing_devices.append(missing_id)

                for dev in batch:
                    if dev.upper() not in received_devices:
                        missing_devices.append(dev)

            except requests.exceptions.RequestException as e:
                print(f"Request error on batch {batch_num}: {e}")
                status_code = getattr(getattr(e, 'response', None), 'status_code', None)
                if status_code in (401, 403):
                    yield f"data: {json.dumps({'type':'auth_error','status':status_code,'message':'Authentication failed — your Authorization/Cookie headers are expired or invalid. Please update and retry.'})}\n\n"
                    return
                for dev in batch:
                    missing_devices.append(dev)

            queried_now = batch_start + len(batch)
            pct = round((queried_now / total_devices) * 100)
            yield f"data: {json.dumps({'type':'progress','pct':pct,'queried':queried_now,'total':total_devices,'found':len(platform_device_records),'batch':batch_num,'total_batches':total_batches})}\n\n"

            print(f"Finished batch {batch_num}/{total_batches}")
            time.sleep(SLEEP_SEC)

        # ── Final sort and result ─────────────────────────────────────
        df = pd.DataFrame(platform_device_records)
        if not df.empty:
            df["sort_order"] = df.apply(sort_priority, axis=1)
            df = df.sort_values(by=["sort_order", "Platform ID"])
            df.drop(columns="sort_order", inplace=True)

        records       = df.to_dict(orient="records") if not df.empty else []
        found         = len(records)
        missing_count = len(missing_devices)

        result = {
            "total":         total_devices,
            "found":         found,
            "missing_count": missing_count,
            "found_pct":     round(found / total_devices * 100, 1) if total_devices else 0,
            "missing_pct":   round(missing_count / total_devices * 100, 1) if total_devices else 0,
            "devices":       records,
            "missing":       missing_devices,
        }

        yield f"data: {json.dumps({'type':'progress','pct':100,'queried':total_devices,'total':total_devices,'found':found,'batch':total_batches,'total_batches':total_batches})}\n\n"
        yield f"data: {json.dumps({'type':'done','data':result})}\n\n"

    return Response(generate(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
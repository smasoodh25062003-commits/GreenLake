from flask import Blueprint, request, jsonify, Response
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests
import json
import time
import re

SUB_URL = (
    "https://aquila-user-api.common.cloud.hpe.com"
    "/support-assistant/v1alpha1/subscriptions"
    "?limit={limit}&offset={offset}&subscription_key_pattern={key}"
)
# API often returns max 30 per page; we paginate to get all
PAGE_SIZE = 30
TIMEOUT = 10
# How many keys to fetch in parallel (tune if API throttles)
MAX_CONCURRENT_KEYS = 8

subscription_bp = Blueprint('subscription', __name__)


def _fetch_one_key(key, parsed_headers):
    """Fetch all pages for one key. Returns ('ok', key, results, missing) or ('auth_error', status_code, None, None)."""
    try:
        all_subs_for_key = []
        offset = 0
        while True:
            url = SUB_URL.format(limit=PAGE_SIZE, offset=offset, key=key)
            response = requests.get(url, headers=parsed_headers, timeout=TIMEOUT)
            response.raise_for_status()
            data = response.json()
            subscriptions = data.get("subscriptions", [])
            all_subs_for_key.extend(subscriptions)
            if len(subscriptions) < PAGE_SIZE:
                break
            offset += PAGE_SIZE
            time.sleep(0.05)

        results = []
        missing_for_key = []
        if not all_subs_for_key:
            missing_for_key.append(key)
        else:
            for sub in all_subs_for_key:
                appointments = sub.get("appointments", {})
                start_epoch = appointments.get("subscription_start")
                end_epoch = appointments.get("subscription_end")
                start_str = datetime.utcfromtimestamp(start_epoch / 1000).strftime("%Y-%m-%d") if start_epoch else ""
                end_str = datetime.utcfromtimestamp(end_epoch / 1000).strftime("%Y-%m-%d") if end_epoch else ""
                eval_type = sub.get("evaluation_type", "")
                if eval_type == "NONE":
                    eval_type = "PAID"
                is_valid = (
                    end_epoch
                    and datetime.utcnow().date() <= datetime.utcfromtimestamp(end_epoch / 1000).date()
                )
                status = "VALID" if is_valid else "EXPIRED"
                sub_key = sub.get("subscription_key")
                quote = sub.get("quote")
                if sub_key and quote:
                    results.append({
                        "Subscription Key": sub_key,
                        "Key Description": sub.get("product_description", ""),
                        "Type": eval_type,
                        "Quantity": sub.get("quantity", ""),
                        "Open Seats": sub.get("available_quantity", ""),
                        "Start Date": start_str,
                        "End Date": end_str,
                        "Valid/Expired": status,
                        "Order ID": quote,
                        "Product SKU": sub.get("product_sku", ""),
                        "EndUser Name": sub.get("end_user_name", ""),
                        "Workspace": sub.get("platform_customer_id", ""),
                    })
                else:
                    missing_for_key.append(sub_key or key)
        return ("ok", key, results, missing_for_key)
    except requests.exceptions.RequestException as e:
        status_code = getattr(getattr(e, "response", None), "status_code", None)
        if status_code in (401, 403):
            return ("auth_error", status_code, None, None)
        return ("ok", key, [], [key])


# ─── Routes ───────────────────────────────────────────────────────────────────
@subscription_bp.route("/api/subscription-stream", methods=["POST"])
def subscription_stream():
    body           = request.get_json(force=True)
    raw_keys       = body.get("keys", "")
    parsed_headers = body.get("parsed_headers", {})

    keys = list(set([
        k.strip() for k in re.split(r"[,\n]+", raw_keys)
        if k.strip()
    ]))

    if not keys:
        return jsonify({"error": "No subscription keys provided."}), 400

    def generate():
        total_keys = len(keys)
        results = []
        missing_keys = []

        with ThreadPoolExecutor(max_workers=MAX_CONCURRENT_KEYS) as executor:
            futures = {executor.submit(_fetch_one_key, key, parsed_headers): key for key in keys}
            completed = 0
            for fut in as_completed(futures):
                status, a, res_list, miss_list = fut.result()
                if status == "auth_error":
                    yield f"data: {json.dumps({'type':'auth_error','status':a,'message':'Authentication failed — your Authorization/Cookie headers are expired or invalid. Please update and retry.'})}\n\n"
                    return
                results.extend(res_list)
                missing_keys.extend(miss_list)
                completed += 1
                pct = round(completed / total_keys * 100)
                yield f"data: {json.dumps({'type':'progress','pct':pct,'queried':completed,'total':total_keys})}\n\n"

        # ── Deduplicate ───────────────────────────────────────────────
        seen, deduped = set(), []
        for r in results:
            k = r["Subscription Key"]
            if k not in seen:
                seen.add(k)
                deduped.append(r)

        missing_keys = list(set(missing_keys))

        # Sort by Workspace
        deduped.sort(key=lambda r: (r.get("Workspace") or "").lower())

        valid_count   = sum(1 for r in deduped if r["Valid/Expired"] == "VALID")
        expired_count = sum(1 for r in deduped if r["Valid/Expired"] == "EXPIRED")
        missing_count = len(missing_keys)
        total         = valid_count + expired_count + missing_count

        result = {
            "total":         total,
            "valid":         valid_count,
            "expired":       expired_count,
            "missing_count": missing_count,
            "valid_pct":     round(valid_count   / total * 100, 1) if total else 0,
            "expired_pct":   round(expired_count / total * 100, 1) if total else 0,
            "missing_pct":   round(missing_count / total * 100, 1) if total else 0,
            "subscriptions": deduped,
            "missing":       missing_keys,
        }

        yield f"data: {json.dumps({'type':'progress','pct':100,'queried':total_keys,'total':total_keys})}\n\n"
        yield f"data: {json.dumps({'type':'done','data':result})}\n\n"

    return Response(generate(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
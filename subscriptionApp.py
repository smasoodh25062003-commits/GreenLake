from flask import Blueprint, request, jsonify, Response
from datetime import datetime
import requests
import json
import time
import re

SUB_URL = (
    "https://aquila-user-api.common.cloud.hpe.com"
    "/support-assistant/v1alpha1/subscriptions"
    "?limit=500&offset=0&subscription_key_pattern={}"
)
TIMEOUT = 10

subscription_bp = Blueprint('subscription', __name__)


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
        total_keys   = len(keys)
        results      = []
        missing_keys = []

        for idx, key in enumerate(keys, start=1):
            try:
                response = requests.get(
                    SUB_URL.format(key),
                    headers=parsed_headers,
                    timeout=TIMEOUT
                )
                response.raise_for_status()
                data          = response.json()
                subscriptions = data.get("subscriptions", [])

                if not subscriptions:
                    missing_keys.append(key)
                else:
                    for sub in subscriptions:
                        appointments = sub.get("appointments", {})
                        start_epoch  = appointments.get("subscription_start")
                        end_epoch    = appointments.get("subscription_end")

                        start_str = datetime.utcfromtimestamp(start_epoch / 1000).strftime("%Y-%m-%d") if start_epoch else ""
                        end_str   = datetime.utcfromtimestamp(end_epoch   / 1000).strftime("%Y-%m-%d") if end_epoch   else ""

                        eval_type = sub.get("evaluation_type", "")
                        if eval_type == "NONE":
                            eval_type = "PAID"

                        is_valid = (
                            end_epoch and
                            datetime.utcnow().date() <= datetime.utcfromtimestamp(end_epoch / 1000).date()
                        )
                        status  = "VALID" if is_valid else "EXPIRED"
                        sub_key = sub.get("subscription_key")
                        quote   = sub.get("quote")

                        if sub_key and quote:
                            results.append({
                                "Subscription Key": sub_key,
                                "Key Description":  sub.get("product_description", ""),
                                "Type":             eval_type,
                                "Quantity":         sub.get("quantity", ""),
                                "Open Seats":       sub.get("available_quantity", ""),
                                "Start Date":       start_str,
                                "End Date":         end_str,
                                "Valid/Expired":    status,
                                "Order ID":         quote,
                                "Product SKU":      sub.get("product_sku", ""),
                                "EndUser Name":     sub.get("end_user_name", ""),
                                "Workspace":        sub.get("platform_customer_id", ""),
                            })
                        else:
                            missing_keys.append(sub_key or key)

            except requests.exceptions.RequestException as e:
                status_code = getattr(getattr(e, 'response', None), 'status_code', None)
                if status_code in (401, 403):
                    yield f"data: {json.dumps({'type':'auth_error','status':status_code,'message':'Authentication failed — your Authorization/Cookie headers are expired or invalid. Please update and retry.'})}\n\n"
                    return
                missing_keys.append(key)

            pct = round(idx / total_keys * 100)
            yield f"data: {json.dumps({'type':'progress','pct':pct,'queried':idx,'total':total_keys})}\n\n"
            time.sleep(0.2)

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
import re
from dataclasses import dataclass
from urllib.parse import parse_qs, urlparse

from kicad_dfm.core import http
from kicad_dfm.core.errors import RemoteApiError


DOMESTIC_UPLOAD_URL = "https://www.eda.cn/openapi/dfm/hqpcb/upfile"
DOMESTIC_POLL_URL = "https://www.eda.cn/openapi/dfm/hqpcb/getParseResult"
OVERSEAS_UPLOAD_URL = "https://www.eda.cn/openapi/api/nextpcb/upfile/kiCadUpFile"
OVERSEAS_POLL_URL = "https://www.eda.cn/openapi/api/nextpcb/DfmView/getParseResult"


@dataclass
class RemoteJob:
    region: str
    analyse_id: str
    kicad_id: str
    poll_url: str


def submit_domestic(zip_path):
    response = http.post_multipart_file(
        DOMESTIC_UPLOAD_URL,
        zip_path,
        filename="gerber.zip",
        form={"type": "kicad"},
        headers={"Cookie": "JSESSIONID=107651F471ED81257ABB4BF1FF1E3150"},
    )
    data = response.json()
    if not is_success_response(data):
        raise RemoteApiError("Domestic upload failed")
    result = response_payload(data)
    analyse_id, kicad_id = job_identifiers(result)
    if not analyse_id or not kicad_id:
        raise RemoteApiError("Domestic upload response is missing job identifiers")
    return RemoteJob("domestic", analyse_id, kicad_id, DOMESTIC_POLL_URL)


def submit_overseas(zip_path):
    response = http.post_multipart_file(
        OVERSEAS_UPLOAD_URL,
        zip_path,
        filename="gerber.zip",
        form={"region": "us", "type": "dfm", "bcount": "10"},
    )
    data = response.json()
    if not is_success_response(data):
        raise RemoteApiError("Overseas upload failed")
    analyse_id, kicad_id = job_identifiers(response_payload(data))
    if not analyse_id or not kicad_id:
        raise RemoteApiError("Overseas upload response is missing job identifiers")
    return RemoteJob("overseas", analyse_id, kicad_id, OVERSEAS_POLL_URL)


def poll_domestic(job):
    return http.post_form(job.poll_url, params={"id": job.analyse_id, "kicadid": job.kicad_id}).json()


def poll_overseas(job):
    return http.get_json(job.poll_url, params={"id": job.analyse_id, "kicadid": job.kicad_id})


def download_result(url, filename):
    return http.download_file(url, filename)


def is_success_response(data):
    if not isinstance(data, dict):
        return False
    if data.get("status") is False or data.get("success") is False:
        return False
    code = data.get("code")
    if code is None:
        return data.get("status") is True or data.get("success") is True or bool(response_payload(data))
    try:
        return int(code) in (200, 2000, 50000)
    except (TypeError, ValueError):
        return False


def is_pending_response(data):
    try:
        return int((data or {}).get("code")) == 22006
    except (TypeError, ValueError):
        return False


def response_payload(data):
    if not isinstance(data, dict):
        return {}
    payload = data.get("data")
    if payload in (None, ""):
        payload = data.get("result")
    return payload or {}


def result_url(data):
    payload = response_payload(data)
    if isinstance(payload, str):
        return payload
    if not isinstance(payload, dict):
        return ""
    for key in (
        "analyse_url",
        "analysis_url",
        "analyze_url",
        "result_url",
        "download_url",
        "file_url",
        "json_url",
        "url",
    ):
        value = payload.get(key)
        if value:
            return value
    return ""


def job_identifiers(data):
    if isinstance(data, str):
        return _match_query_value(data, "id"), _match_query_value(data, "kicadid")
    if not isinstance(data, dict):
        return "", ""
    analyse_id = data.get("analyse_id") or data.get("analysis_id") or data.get("analyze_id") or data.get("id") or ""
    kicad_id = data.get("kicad_id") or data.get("kicadid") or data.get("kicadId") or ""
    if not analyse_id or not kicad_id:
        url = result_url({"data": data})
        analyse_id = analyse_id or _match_query_value(url, "id")
        kicad_id = kicad_id or _match_query_value(url, "kicadid")
    return str(analyse_id), str(kicad_id)


def _match_query_value(url, name):
    if not url:
        return ""
    parsed = parse_qs(urlparse(url).query)
    if name in parsed and parsed[name]:
        return parsed[name][0]
    match = re.search(r"[?&]{0}=([A-Za-z0-9_-]+)".format(re.escape(name)), url)
    return match.group(1) if match else ""

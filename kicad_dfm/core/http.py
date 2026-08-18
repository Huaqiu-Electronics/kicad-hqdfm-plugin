import json
import mimetypes
import os
import uuid
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .errors import RemoteApiError


class HttpResponse:
    def __init__(self, status, headers, content):
        self.status = status
        self.headers = headers
        self.content = content

    def json(self):
        if not self.content:
            return None
        return json.loads(self.content.decode("utf-8"))

    def raise_for_status(self):
        if self.status >= 400:
            raise RemoteApiError("HTTP {0}".format(self.status))


def _request(method, url, data=None, headers=None, timeout=20):
    request = Request(url, data=data, headers=headers or {}, method=method)
    try:
        with urlopen(request, timeout=timeout) as response:
            content = response.read()
            return HttpResponse(response.getcode(), response.headers, content)
    except HTTPError as exc:
        raise RemoteApiError("HTTP {0}: {1}".format(exc.code, exc.reason))
    except URLError as exc:
        raise RemoteApiError(str(exc.reason))
    except OSError as exc:
        raise RemoteApiError(str(exc))


def get_json(url, params=None, headers=None, timeout=20):
    if params:
        separator = "&" if "?" in url else "?"
        url = url + separator + urlencode(params)
    return _request("GET", url, headers=headers, timeout=timeout).json()


def post_form(url, data=None, params=None, headers=None, timeout=20):
    if params:
        separator = "&" if "?" in url else "?"
        url = url + separator + urlencode(params)
    body = urlencode(data or {}).encode("utf-8")
    request_headers = {"Content-Type": "application/x-www-form-urlencoded"}
    request_headers.update(headers or {})
    return _request("POST", url, data=body, headers=request_headers, timeout=timeout)


def post_multipart_file(url, file_path, field_name="file", filename=None, form=None, headers=None, timeout=20):
    boundary = "----kicad-hqdfm-{0}".format(uuid.uuid4().hex)
    filename = filename or os.path.basename(file_path)
    content_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    chunks = []
    for name, value in (form or {}).items():
        chunks.append("--{0}\r\n".format(boundary).encode("ascii"))
        chunks.append('Content-Disposition: form-data; name="{0}"\r\n\r\n'.format(name).encode("utf-8"))
        chunks.append(str(value).encode("utf-8"))
        chunks.append(b"\r\n")
    chunks.append("--{0}\r\n".format(boundary).encode("ascii"))
    chunks.append(
        'Content-Disposition: form-data; name="{0}"; filename="{1}"\r\n'.format(
            field_name, filename
        ).encode("utf-8")
    )
    chunks.append("Content-Type: {0}\r\n\r\n".format(content_type).encode("ascii"))
    with open(file_path, "rb") as fp:
        chunks.append(fp.read())
    chunks.append(b"\r\n--" + boundary.encode("ascii") + b"--\r\n")
    request_headers = {"Content-Type": "multipart/form-data; boundary={0}".format(boundary)}
    request_headers.update(headers or {})
    return _request("POST", url, data=b"".join(chunks), headers=request_headers, timeout=timeout)


def download_file(url, path, chunk_size=8192, timeout=20):
    request = Request(url, method="GET")
    try:
        with urlopen(request, timeout=timeout) as response:
            if response.getcode() >= 400:
                raise RemoteApiError("HTTP {0}".format(response.getcode()))
            with open(path, "wb") as fp:
                while True:
                    chunk = response.read(chunk_size)
                    if not chunk:
                        break
                    fp.write(chunk)
    except HTTPError as exc:
        raise RemoteApiError("HTTP {0}: {1}".format(exc.code, exc.reason))
    except URLError as exc:
        raise RemoteApiError(str(exc.reason))
    except OSError as exc:
        raise RemoteApiError(str(exc))
    return path

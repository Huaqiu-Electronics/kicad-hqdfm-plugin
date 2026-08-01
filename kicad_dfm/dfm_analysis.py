from __future__ import annotations

import json
import os
import re
import time

import requests
import wx
from requests.exceptions import (
    ConnectionError,
    HTTPError,
    Timeout,
)

from kicad_dfm import GetFilePath
from kicad_dfm.constants import (
    API_CODE_PENDING as _API_PENDING,
)
from kicad_dfm.constants import (
    API_CODE_SUCCESS as _API_OK,
)
from kicad_dfm.constants import (
    API_CODE_SUCCESS_ALT_200 as _API_OK_200,
)
from kicad_dfm.constants import (
    API_CODE_SUCCESS_ALT_50000 as _API_OK_50000,
)
from kicad_dfm.constants import (
    HTTP_CHUNK_SIZE,
    HTTP_SLEEP_POLL_SEC,
    HTTP_TIMEOUT_SEC,
    PROGRESS_DONE,
    PROGRESS_DOWNLOAD,
    PROGRESS_MAX,
    PROGRESS_POLL_CAP,
    PROGRESS_POLL_START,
    PROGRESS_POLL_STEP,
    PROGRESS_START,
    Colour,
)

from . import config


class DfmAnalysis:
    def __init__(self):
        self.board_layer_count = None

    def guonei_download_dfm_file(self, zip_path, title_name):
        self.start_progress_bar()
        with open(zip_path, "rb") as url_path:
            files = {"file": ("gerber.zip", url_path, "application/zip", {"Expires": "0"})}
            data = {"type": "kicad"}
            url = "https://www.eda.cn/openapi/dfm/hqpcb/upfile"

            response = self.api_request_interface(url, files, data)

        json_temp = response.json()
        if not json_temp:
            self.report_part_search_error(_("Failed to upload file. Please request again."))
            return None
        if json_temp["code"] != 2000:
            self.report_part_search_error(_("HTTP request error. Please request again."))
            return None
        analyse_url = json_temp["data"]
        analyse_id = analyse_url.get("analyse_id", "")
        kicad_id = analyse_url.get("kicad_id", "")
        if analyse_id == "" or kicad_id == "":
            self.report_part_search_error(_("Not dfm data. Please request again."))
            return None
        if self.progress.WasCancelled():
            self.progress_dialog_close()

        id_url = "https://www.eda.cn/openapi/dfm/hqpcb/getParseResult"
        params = {"id": analyse_id, "kicadid": kicad_id}
        filename = self.guonei_request_dfm_analysis_file(id_url, params, zip_path, title_name)
        self.progress_dialog_close()
        return filename

    def haiwai_download_dfm_file(self, zip_path, title_name):
        self.start_progress_bar()
        with open(zip_path, "rb") as url_path:
            files = {"file": ("gerber.zip", url_path, "application/zip", {"Expires": "0"})}
            data = {
                "region": "us",
                "type": "dfm",
                "bcount": "10",
            }
            url = "https://www.eda.cn/openapi/api/nextpcb/upfile/kiCadUpFile"

            response = self.api_request_interface(url, files, data)
        json_temp = response.json()
        if json_temp["status"] is False:
            return None
        if self.progress.WasCancelled():
            self.progress_dialog_close()

        json_id = ""
        kicad_id = ""

        id_rule = re.compile(r"(?<=(\?id=))[A-Za-z0-9]+(?=&kicadid=)")
        kicad_rule = re.compile(r"(?<=(&kicadid=))[A-Za-z0-9]+")
        analyse_url = json_temp["data"]["analyse_url"]
        ret = id_rule.search(analyse_url)
        if ret is not None:
            json_id = ret.group()
        ret = kicad_rule.search(analyse_url)
        if ret is not None:
            kicad_id = ret.group()
        if json_id == "" or kicad_id == "":
            self.report_part_search_error(_("Not dfm data. Please request again."))
            return None

        id_url = "https://www.eda.cn/openapi/api/nextpcb/DfmView/getParseResult"
        params = {"id": json_id, "kicadid": kicad_id}
        filename = self.haiwai_request_dfm_analysis_file(id_url, params, zip_path, title_name)
        self.progress_dialog_close()
        return filename

    def start_progress_bar(self):
        self.progress = wx.ProgressDialog(
            _("Upload DFM analysis file"),
            _("Please wait"),
            maximum=PROGRESS_MAX,
        )
        if self.progress:
            self.progress.Update(PROGRESS_START)

    def progress_dialog_close(self):
        self.progress.Update(PROGRESS_DONE)
        self.progress.Destroy()
        self.progress = None

    def haiwai_request_dfm_analysis_file(self, id_url, params, zip_path, title_name):
        number = PROGRESS_POLL_START
        self.progress.SetTitle(self.language["DFM analysis in progress"])
        while True:
            if number < PROGRESS_POLL_CAP:
                number += PROGRESS_POLL_STEP
            try:
                json_file = requests.get(id_url, params=params, timeout=HTTP_TIMEOUT_SEC)
                time.sleep(HTTP_SLEEP_POLL_SEC)
            except requests.exceptions.ConnectionError:
                self.report_part_search_error(_("Network connection error. Please request again."))
            file_path = json_file.json()
            self.progress.Update(number)
            if file_path["code"] in (_API_OK, _API_OK_200, _API_OK_50000):
                break
            if file_path["code"] != _API_PENDING:
                break

            if self.progress.WasCancelled():
                return None

        if not file_path.get("data"):
            wx.MessageBox(
                _("Request data error,please request again."),
                _("Info"),
                style=wx.ICON_INFORMATION,
            )
            return None

        file_url = file_path["data"]["analyse_url"]
        filename = GetFilePath("temp.json")
        temp_filename = GetFilePath("name.json")
        self.download_file(file_url, filename)

        data = {"name": title_name}
        with open(temp_filename, "w", encoding="utf-8") as fp:
            json.dump(
                data,
                fp,
                ensure_ascii=False,
                indent=4,
                separators=(",", ":"),
                sort_keys=True,
            )
        if os.path.exists(zip_path):
            os.remove(zip_path)
        else:
            return None
        return filename

    def guonei_request_dfm_analysis_file(self, id_url, params, zip_path, title_name):
        number = 30
        self.progress.SetTitle(_("Analytical phase"))
        while True:
            if number < PROGRESS_POLL_CAP:
                number += PROGRESS_POLL_STEP
            try:
                json_file = requests.post(id_url, params=params, timeout=HTTP_TIMEOUT_SEC)
                time.sleep(HTTP_SLEEP_POLL_SEC)
            except requests.exceptions.ConnectionError:
                self.report_part_search_error(_("Network connection error. Please request again."))
            file_path = json_file.json()
            self.progress.Update(number)
            if file_path["code"] in (_API_OK, _API_OK_200, _API_OK_50000):
                break
            if file_path["code"] != _API_PENDING:
                break

            if self.progress.WasCancelled():
                return None

        if not file_path.get("data"):
            wx.MessageBox(
                _("Request data error,please request again."),
                _("Info"),
                style=wx.ICON_INFORMATION,
            )
            return None

        file_url = file_path["data"]["analyse_url"]
        filename = GetFilePath("temp.json")
        temp_filename = GetFilePath("name.json")
        self.download_file(file_url, filename)

        data = {"name": title_name}
        with open(temp_filename, "w", encoding="utf-8") as fp:
            json.dump(
                data,
                fp,
                ensure_ascii=False,
                indent=4,
                separators=(",", ":"),
                sort_keys=True,
            )
        if os.path.exists(zip_path):
            os.remove(zip_path)
        else:
            return None
        return filename

    def download_file(self, url, filename):
        with requests.get(url, stream=True, timeout=HTTP_TIMEOUT_SEC) as response:
            response.raise_for_status()
            with open(filename, "wb") as f:
                for chunk in response.iter_content(chunk_size=HTTP_CHUNK_SIZE):
                    f.write(chunk)

    def api_request_interface(self, url, files, data):
        try:
            headers = {"Cookie": "JSESSIONID=107651F471ED81257ABB4BF1FF1E3150"}
            response = requests.post(url, headers=headers, files=files, data=data, timeout=HTTP_TIMEOUT_SEC)
            response.raise_for_status()
            self.progress.Update(PROGRESS_DOWNLOAD)
            self.progress.SetTitle(_("Analysis file"))
        except Timeout:
            self.report_part_search_error(_("HTTP request timed out."))
        except (ConnectionError, HTTPError) as e:
            self.report_part_search_error(_("HTTP error occurred: {error}").format(error=e))
        except Exception as e:
            self.report_part_search_error(_("An unexpected HTTP error occurred: {error}").format(error=e))
        else:
            return response

    def report_part_search_error(self, reason):
        wx.MessageBox(
            _("Failed to request dfm analysis data: \r\n{reasons}\r\n").format(reasons=reason),
            _("Error"),
            style=wx.ICON_ERROR,
        )
        self.progress_dialog_close()

    def analysis_json(self, json_path, transformation=False):
        json_result = {}
        if json_path is None or not isinstance(json_path, str):
            return None
        with open(json_path) as f:
            content = f.read().encode(encoding="utf-8")
            try:
                data = json.loads(content)
            except json.decoder.JSONDecodeError:
                return None
            try:
                json.loads(content)
            except ValueError:
                os.remove(json_path)
                return None
            json_name = [
                "Signal Integrity",
                "Smallest Trace Width",
                "Smallest Trace Spacing",
                "Pad size",
                "Pad Spacing",
                "Hatched Copper Pour",
                "Hole Diameter",
                "RingHole",
                "Drill Hole Spacing",
                "Drill to Copper",
                "Copper-to-Board Edge",
                "Special Drill Holes",
                "Holes on SMD Pads",
                "Missing SMask Openings",
                "Drill Hole Density",
                "Surface Finish Area",
                "Test Point Count",
            ]

            for name in json_name:
                item_result = {}
                if name not in data:
                    json_result[name] = ""
                    continue
                item_json = data[name]
                if name == "Drill Hole Density" or name == "Surface Finish Area" or name == "Test Point Count":
                    item_result["display"] = item_json["display"]
                    json_result[name] = item_result
                    continue
                if item_json["check"] is None:
                    if item_json["display"] is not None and "detected" not in item_json["display"]:
                        item_result["display"] = None
                        json_result[name] = item_result
                    else:
                        json_result[name] = ""
                    continue

                self.analysis_every_item(json_result, item_json, name, item_result, transformation)
        f.close()
        # with open("output.json", "w") as f:
        #     json.dump(json_result, f)
        return json_result

    def analysis_every_item(self, json_result, item_json, name, item_result, transformation):
        have_red = False
        have_yellow = False
        info_list = []
        dfm_show_layer = ""
        for item_check in item_json["check"]:
            if name == "Drill to Copper":
                if item_check["layer"] == "Drl":
                    dfm_show_layer = ""
            elif item_check["layer"] == "Drl":
                dfm_show_layer = "Top Layer"
            else:
                dfm_show_layer = item_check["layer"]
            for item_info in item_check["info"]:
                item = item_info["item"]
                if transformation and item.lower() in config.Language_chinese:
                    item = config.Language_chinese[item.lower()]
                rule = item_info["rule"]
                rule_string1 = rule.partition(",")
                rule_string2 = rule_string1[2].partition(",")
                rule_string3 = rule_string2[2].partition(",")
                rule_string4 = rule_string3[2].partition(",")
                item_info_info_list = item_info.get("info") or []
                for item_info_info in item_info_info_list:
                    result_list = {}
                    item_layer_list = []
                    if dfm_show_layer != "":
                        item_layer_list.append(dfm_show_layer)
                    if dfm_show_layer == "Bot Paste" or dfm_show_layer == "Top Paste":
                        item_layer_list.append("Outline")
                    for item_layer in item_info_info["layer"]:
                        if name == "Drill to Copper":
                            if item_layer == "Drl":
                                continue
                            item_layer_list.append(item_layer)
                        elif item_layer == "Drl":
                            item_layer_list.append("Top Layer")
                        else:
                            item_layer_list.append(item_layer)
                    # 设置显示的颜色
                    if rule_string2[0] == "-" or rule_string1[0] == "-":
                        have_red = True
                        color = Colour.RED
                    else:
                        if rule_string4[0] != "1":
                            rule1 = float(rule_string1[0])
                            rule2 = float(rule_string2[0])
                        else:
                            rule1 = rule_string1[0]
                            rule2 = rule_string2[0]
                            if "%" in rule1:
                                rule1 = float(rule1.strip("%")) / 100
                                rule2 = float(rule2.strip("%")) / 100
                            else:
                                rule1 = float(rule1)
                                rule2 = float(rule2)

                        if rule1 < rule2:
                            if float(item_info_info["val"]) < rule1:
                                color = Colour.RED
                                have_red = True
                            elif rule2 > float(item_info_info["val"]) > rule1:
                                color = Colour.GOLD
                                have_yellow = True
                            else:
                                color = Colour.BLACK
                        else:
                            if float(item_info_info["val"]) > rule1:
                                color = Colour.RED
                                have_red = True
                            elif rule2 < float(item_info_info["val"]) < rule1:
                                color = Colour.GOLD
                                have_yellow = True
                            else:
                                color = Colour.BLACK
                    result_list["result"] = self.analysis_dfm_type_info(
                        item_info_info,
                        item,
                        rule,
                        item_layer_list,
                        color,
                    )
                    info_list.append(result_list)

        item_result["check"] = info_list
        if len(info_list) == 0:
            item_result["display"] = ""
            item_result["display_inch"] = ""
        else:
            item_result["display"] = item_json["display"]
            item_result["display_inch"] = item_json["display_inch"]
        if have_red:
            item_result["color"] = Colour.RED
        elif have_yellow:
            item_result["color"] = Colour.GOLD
        else:
            item_result["color"] = Colour.BLACK
        json_result[name] = item_result
        return json_result

    def analysis_dfm_type_info(self, item_info_info, item, rule, item_layer_list, color):
        item_list = []
        if item_info_info.get("type") == 0:
            result_data = item_info_info.get("result") or []
            for item_info_info_result in result_data:
                item_info_list = {}
                item_info_list["item"] = item
                item_info_list["rule"] = rule
                item_info_list["layer"] = item_layer_list
                item_info_list["value"] = item_info_info["val"]
                item_info_list["type"] = 0
                item_info_list["color"] = color
                if item_info_info_result["et"] == 0:
                    item_info_list["et"] = item_info_info_result["et"]
                    item_info_list["sx"] = item_info_info_result["coord"]["sx"]
                    item_info_list["sy"] = item_info_info_result["coord"]["sy"]
                    item_info_list["ex"] = item_info_info_result["coord"]["ex"]
                    item_info_list["ey"] = item_info_info_result["coord"]["ey"]
                    item_list.append(item_info_list)
                elif item_info_info_result["et"] == 1:
                    item_info_list["et"] = item_info_info_result["et"]
                    item_info_list["sx"] = item_info_info_result["coord"]["sx"]
                    item_info_list["sy"] = item_info_info_result["coord"]["sy"]
                    item_info_list["ex"] = item_info_info_result["coord"]["ex"]
                    item_info_list["ey"] = item_info_info_result["coord"]["ey"]
                    item_info_list["cx"] = item_info_info_result["coord"]["cx"]
                    item_info_list["cy"] = item_info_info_result["coord"]["cy"]
                    item_list.append(item_info_list)
                else:
                    item_info_list["et"] = item_info_info_result["et"]
                    item_info_list["cx"] = item_info_info_result["coord"]["cx"]
                    item_info_list["cy"] = item_info_info_result["coord"]["cy"]
                    item_list.append(item_info_list)
        elif item_info_info["type"] == 2:
            item_info_list = {}
            item_info_list["item"] = item
            item_info_list["rule"] = rule
            item_info_list["layer"] = item_layer_list
            item_info_list["value"] = item_info_info["val"]
            item_info_list["type"] = 0
            item_info_list["type"] = 2
            item_info_list["color"] = color
            item_info_list["sx"] = item_info_info["result"]["coord"]["sx"]
            item_info_list["ex"] = item_info_info["result"]["coord"]["ex"]
            item_info_list["sy"] = item_info_info["result"]["coord"]["sy"]
            item_info_list["ey"] = item_info_info["result"]["coord"]["ey"]
            item_list.append(item_info_list)
        else:
            item_info_list = {}
            item_info_list["item"] = item
            item_info_list["rule"] = rule
            item_info_list["layer"] = item_layer_list
            item_info_list["value"] = item_info_info["val"]
            item_info_list["type"] = 0
            item_info_list["color"] = color
            signal_integrity_result = []
            item_info_list["type"] = 3
            for signal_integrity_info_info_result in item_info_info["result"]:
                signal_integrity_result.append(signal_integrity_info_info_result)
                item_info_list["result"] = signal_integrity_result
            item_list.append(item_info_list)
        return item_list

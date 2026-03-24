import json

import re
import wx
import os
import sys
import time
from . import config
from kicad_dfm import GetFilePath
from kicad_dfm.settings.timestamp import TimeStamp
import logging
import requests
from requests.exceptions import (
    Timeout,
    ConnectionError,
    HTTPError,
    SSLError,
    RequestException,
)


class DfmAnalysis:
    def __init__(self):
        self.board_layer_count = None

    def guonei_download_dfm_file(self, zip_path, title_name):
        self.start_progress_bar()
        url_path = open(zip_path, "rb")
        files = {"file": ("gerber.zip", url_path, "application/zip", {"Expires": "0"})}
        data = {"type": "kicad"}
        url = "https://www.eda.cn/openapi/dfm/hqpcb/upfile"

        response = self.api_request_interface(url, files, data)

        json_temp = response.json()
        if not json_temp:
            self.report_part_search_error(
                _("Failed to upload file. Please request again.")
            )
            return
        if json_temp["code"] != 2000:
            self.report_part_search_error(
                _("HTTP request error. Please request again.")
            )
            return
        analyse_url = json_temp["data"]
        analyse_id = analyse_url.get("analyse_id", "")
        kicad_id = analyse_url.get("kicad_id", "")
        if analyse_id == "" or kicad_id == "":
            self.report_part_search_error(_("Not dfm data. Please request again."))
            return
        url_path.close()
        if self.progress.WasCancelled():
            self.progress_dialog_close()

        id_url = "https://www.eda.cn/openapi/dfm/hqpcb/getParseResult"
        params = {"id": analyse_id, "kicadid": kicad_id}
        filename = self.guonei_requset_dfm_analysis_file(
            id_url, params, zip_path, title_name
        )
        self.progress_dialog_close()
        return filename

    def haiwai_download_dfm_file(self, zip_path, title_name):
        self.start_progress_bar()
        url_path = open(zip_path, "rb")
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
            return
        url_path.close()
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
            return

        id_url = "https://www.eda.cn/openapi/api/nextpcb/DfmView/getParseResult"
        params = {"id": json_id, "kicadid": kicad_id}
        filename = self.haiwai_requset_dfm_analysis_file(
            id_url, params, zip_path, title_name
        )
        self.progress_dialog_close()
        return filename

    def start_progress_bar(self):
        self.progress = wx.ProgressDialog(
            _("Upload DFM analysis file"),
            _("Please wait"),
            maximum=100,
            style=wx.PD_APP_MODAL | wx.PD_CAN_ABORT | wx.PD_AUTO_HIDE,
        )
        self.abort = False
        # self.progress.Bind(wx.EVT_CLOSE, self.on_cancel)
        self.progress.Update(5)

    def progress_dialog_close(self):
        self.progress.Update(100)
        self.progress.Destroy()
        self.progress = None

    def haiwai_requset_dfm_analysis_file(self, id_url, params, zip_path, title_name):
        number = 30
        self.progress.SetTitle(_("Analytical phase"))
        while 1:
            if number < 90:
                number += 2
            try:
                json_file = requests.get(id_url, params=params, timeout=20  )
                time.sleep(1.5)
            except requests.exceptions.ConnectionError as e:
                self.report_part_search_error(
                    _("Network connection error. Please request again.")
                )
            file_path = json_file.json()
            self.progress.Update(number)
            if (
                file_path["code"] == 2000
                or file_path["code"] == 200
                or file_path["code"] == 50000
            ):
                break
            if file_path["code"] != 22006:
                break

            if self.progress.WasCancelled():
                return

        if len(file_path["data"]) == 0:
            wx.MessageBox(
                _("Request data error,please request again."),
                _("Info"),
                style=wx.ICON_INFORMATION,
            )
            return

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
            return
        return filename

    def guonei_requset_dfm_analysis_file(self, id_url, params, zip_path, title_name):
        number = 30
        self.progress.SetTitle(_("Analytical phase"))
        while 1:
            if number < 90:
                number += 2
            try:
                json_file = requests.post(id_url, params=params)
                time.sleep(1.5)
            except requests.exceptions.ConnectionError as e:
                self.report_part_search_error(
                    _("Network connection error. Please request again.")
                )
            file_path = json_file.json()
            self.progress.Update(number)
            if (
                file_path["code"] == 2000
                or file_path["code"] == 200
                or file_path["code"] == 50000
            ):
                break
            if file_path["code"] != 22006:
                break

            if self.progress.WasCancelled():
                return

        if len(file_path["data"]) == 0:
            wx.MessageBox(
                _("Request data error,please request again."),
                _("Info"),
                style=wx.ICON_INFORMATION,
            )
            return

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
            return
        return filename

    def download_file(self, url, filename):
        with requests.get(url, stream=True,  timeout=20 ) as response:
            response.raise_for_status()  # 检查请求是否成功
            with open(filename, "wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)

    def api_request_interface(self, url, files, data):
        try:
            headers = {"Cookie": "JSESSIONID=107651F471ED81257ABB4BF1FF1E3150"}
            response = requests.post(url, headers=headers, files=files, data=data)
            response.raise_for_status()
            self.progress.Update(20)
            self.progress.SetTitle(_("Analysis file"))
            return response
        except Timeout:
            self.report_part_search_error(_("HTTP request timed out."))
        except (ConnectionError, HTTPError) as e:
            self.report_part_search_error(
                _("HTTP error occurred: {error}").format(error=e)
            )
        except Exception as e:
            self.report_part_search_error(
                _("An unexpected HTTP error occurred: {error}").format(error=e)
            )

    def report_part_search_error(self, reason):
        wx.MessageBox(
            _("Failed to request dfm analysis data: \r\n{reasons}\r\n").format(
                reasons=reason
            ),
            _("Error"),
            style=wx.ICON_ERROR,
        )
        self.progress_dialog_close()

    def analysis_json(self, json_path, transformation=False):
        json_result = {}
        if json_path is None or not isinstance(json_path, str):
            return
        with open(json_path, "r") as f:
            content = f.read().encode(encoding="utf-8")
            try:
                data = json.loads(content)
            except json.decoder.JSONDecodeError as e:
                return
            try:
                json.loads(content)
            except ValueError as e:
                os.remove(json_path)
                return
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
                if (
                    name == "Drill Hole Density"
                    or name == "Surface Finish Area"
                    or name == "Test Point Count"
                ):
                    item_result["display"] = item_json["display"]
                    json_result[name] = item_result
                    continue
                if item_json["check"] is None:
                    if (
                        item_json["display"] is not None
                        and "detected" not in item_json["display"]
                    ):
                        item_result["display"] = None
                        json_result[name] = item_result
                    else:
                        json_result[name] = ""
                    continue

                self.analysis_every_item(
                    json_result, item_json, name, item_result, transformation
                )
        f.close()
        # with open("output.json", "w") as f:
        #     json.dump(json_result, f)
        return json_result

    def analysis_every_item(
        self, json_result, item_json, name, item_result, transformation
    ):
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
                if transformation:
                    if item.lower() in config.Language_chinese:
                        item = config.Language_chinese[item.lower()]
                rule = item_info["rule"]
                rule_string1 = rule.partition(",")
                rule_string2 = rule_string1[2].partition(",")
                rule_string3 = rule_string2[2].partition(",")
                rule_string4 = rule_string3[2].partition(",")
                for item_info_info in item_info["info"]:
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
                            else:
                                item_layer_list.append(item_layer)
                        elif item_layer == "Drl":
                            item_layer_list.append("Top Layer")
                        else:
                            item_layer_list.append(item_layer)
                    # 设置显示的颜色
                    if rule_string2[0] == "-" or rule_string1[0] == "-":
                        have_red = True
                        color = "red"
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
                                color = "red"
                                have_red = True
                            elif rule2 > float(item_info_info["val"]) > rule1:
                                color = "gold"
                                have_yellow = True
                            else:
                                color = "black"
                        else:
                            if float(item_info_info["val"]) > rule1:
                                color = "red"
                                have_red = True
                            elif rule2 < float(item_info_info["val"]) < rule1:
                                color = "gold"
                                have_yellow = True
                            else:
                                color = "black"
                    result_list["result"] = self.anaylsis_dfm_type_info(
                        item_info_info, item, rule, item_layer_list, color
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
            item_result["color"] = "red"
        elif have_yellow:
            item_result["color"] = "gold"
        else:
            item_result["color"] = "black"
        json_result[name] = item_result
        return json_result

    def anaylsis_dfm_type_info(
        self, item_info_info, item, rule, item_layer_list, color
    ):
        item_list = []
        if item_info_info["type"] == 0:
            for item_info_info_result in item_info_info["result"]:
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
            item_info_list["sx"] = item_info_info["result"]["coord"]["spt"]["x"]
            item_info_list["ex"] = item_info_info["result"]["coord"]["ept"]["x"]
            item_info_list["sy"] = item_info_info["result"]["coord"]["spt"]["y"]
            item_info_list["ey"] = item_info_info["result"]["coord"]["ept"]["y"]
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

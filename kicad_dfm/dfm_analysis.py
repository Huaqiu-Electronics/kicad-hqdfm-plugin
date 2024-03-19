import json
import requests
import re
import wx
import urllib.request
import os
import sys
import time
from . import config
from kicad_dfm import GetFilePath


class DfmAnalysis:
    def __init__(self):
        self.board_layer_count = None

    def download_file(self, zip_path, title_name):
        progress = wx.ProgressDialog(
            _("Upload DFM analysis file"),
            _("Please wait"),
            maximum=100,
            style=wx.PD_SMOOTH | wx.PD_AUTO_HIDE,
        )
        progress.Update(5)
        url_path = open(zip_path, "rb")
        request_data = {
            "region": (None, "us"),
            "file": ("gerber.zip", url_path, "application/zip"),
            "type": (None, "dfm"),
            "bcount": (None, 10),
        }
        # headers = {'content-type': 'application/json'}

        url = "https://www.nextpcb.com/upfile/kiCadUpFile"
        try:
            response = requests.post(url, files=request_data)
        except requests.exceptions.ConnectionError as e:
            wx.MessageBox(
                _("Network connection error"), _("Help"), style=wx.ICON_INFORMATION
            )
            progress.Update(90)
            time.sleep(1)
            return
        progress.Update(20)
        progress.SetTitle(_("Analysis file"))
        json_id = ""
        kicad_id = ""
        id_url = "https://www.nextpcb.com/DfmView/getParseResult"
        json_temp = response.json()
        if json_temp["status"] is False:
            return
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
            progress.Update(90)
            time.sleep(1)
            return
        params = {"id": json_id, "kicadid": kicad_id}
        # json_file = requests.get(json_temp["data"]["analyse_url"].encode("utf8"))
        number = 30
        while 1:
            progress.SetTitle(_("Analytical phase"))
            if number < 80:
                number += 2
            try:
                json_file = requests.get(id_url, params=params)
            except requests.exceptions.ConnectionError as e:
                wx.MessageBox(
                    _("Network connection error"), _("Help"), style=wx.ICON_INFORMATION
                )
                progress.Update(90)
                time.sleep(1)
                return
            file_path = json_file.json()
            progress.Update(number)
            if file_path["code"] == 200:
                progress.Destroy()
                break
            if file_path["code"] != 22006:
                progress.Destroy()
                break

        if len(file_path["data"]) == 0:
            return
        file_url = file_path["data"]["analyse_url"]
        filename = GetFilePath("temp.json")
        temp_filename = GetFilePath("name.json")
        urllib.request.urlretrieve(file_url, filename)

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

        url_path.close()
        progress.Update(100)
        if os.path.exists(zip_path):
            os.remove(zip_path)
        else:
            return
        return filename

    def analysis_json(self, json_path, transformation=False):
        json_result = {}
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
                "Board Edge Clearance",
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
        self, json_result, item_json, name, item_result, transformation=False
    ):
        have_red = False
        have_yellow = False
        info_list = []
        for item_check in item_json["check"]:
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
                    item_layer_list.append(dfm_show_layer)
                    for item_layer in item_info_info["layer"]:
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

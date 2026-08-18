import json

import wx
import os
import time
from . import config
from kicad_dfm import GetFilePath
from kicad_dfm.core import dfm_json
from kicad_dfm.core.errors import RemoteApiError
from kicad_dfm.services import remote


class DfmAnalysis:
    def __init__(self,_board):
        self.board =_board
        self.board_layer_count = None
        self.dfm_issues = ()
        self.dfm_summary = {}

    def guonei_download_dfm_file(self, zip_path, title_name):
        self.start_progress_bar()
        job = self.api_request_interface("domestic", zip_path)
        if job is None:
            return
        if self.progress.WasCancelled():
            self.progress_dialog_close()
            return

        filename = self.guonei_requset_dfm_analysis_file(
            job, zip_path, title_name
        )
        if self.progress is not None:
            self.progress_dialog_close()
        return filename

    def haiwai_download_dfm_file(self, zip_path, title_name):
        self.start_progress_bar()
        job = self.api_request_interface("overseas", zip_path)
        if job is None:
            return
        if self.progress.WasCancelled():
            self.progress_dialog_close()
            return

        filename = self.haiwai_requset_dfm_analysis_file(
            job, zip_path, title_name
        )
        if self.progress is not None:
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

    def haiwai_requset_dfm_analysis_file(self, job, zip_path, title_name):
        number = 30
        self.progress.SetTitle(_("Analytical phase"))
        while 1:
            if number < 90:
                number += 2
            try:
                file_path = remote.poll_overseas(job)
                time.sleep(1.5)
            except RemoteApiError:
                self.report_part_search_error(
                    _("Network connection error. Please request again.")
                )
                return
            self.progress.Update(number)
            if remote.is_success_response(file_path):
                break
            if not remote.is_pending_response(file_path):
                break

            if self.progress.WasCancelled():
                return

        file_url = remote.result_url(file_path)
        if not file_url:
            wx.MessageBox(
                _("Request data error,please request again."),
                _("Info"),
                style=wx.ICON_INFORMATION,
            )
            return

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

    def guonei_requset_dfm_analysis_file(self, job, zip_path, title_name):
        number = 30
        self.progress.SetTitle(_("Analytical phase"))
        while 1:
            if number < 90:
                number += 2
            try:
                file_path = remote.poll_domestic(job)
                time.sleep(1.5)
            except RemoteApiError:
                self.report_part_search_error(
                    _("Network connection error. Please request again.")
                )
                return
            self.progress.Update(number)
            if remote.is_success_response(file_path):
                break
            if not remote.is_pending_response(file_path):
                break

            if self.progress.WasCancelled():
                return

        file_url = remote.result_url(file_path)
        if not file_url:
            wx.MessageBox(
                _("Request data error,please request again."),
                _("Info"),
                style=wx.ICON_INFORMATION,
            )
            return

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
        remote.download_result(url, filename)

    def api_request_interface(self, region, zip_path):
        try:
            if region == "domestic":
                job = remote.submit_domestic(zip_path)
            else:
                job = remote.submit_overseas(zip_path)
            self.progress.Update(20)
            self.progress.SetTitle(_("Analysis file"))
            return job
        except RemoteApiError as e:
            self.report_part_search_error(
                _("HTTP error occurred: {error}").format(error=e)
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
        parsed = dfm_json.parse_file(
            json_path,
            board=self.board,
            transformation=transformation,
            translations=config.Language_chinese,
        )
        self.dfm_issues = parsed.issues
        self.dfm_summary = parsed.summary
        return parsed.compat

import copy
import os
import threading
import wx
import re
import json
import pcbnew
from . import config

from .child_frame.dfm_child_frame import DfmChildFrame
from .picture import GetImagePath
from .dfm_analysis import DfmAnalysis
from kicad_dfm import GetFilePath
from kicad_dfm.dfm_maindialog.dfm_maindialog_view import DfmMaindailogView
from kicad_dfm.settings.pcb_setting import PcbSetting
from kicad_dfm.settings.kicad_setting import KiCadSetting
from kicad_dfm.manager.rule_manager_view import RuleManagerView
from kicad_dfm.settings.single_plugin import SINGLE_PLUGIN
from kicad_dfm.hole_childframe.hole_childframe_view import HoleChildFrameView
from kicad_dfm.services.export import export_fabrication_package, gerber_output_dir
from kicad_dfm.services.analysis_cache import load_analysis_cache
from kicad_dfm.services.analysis_cache import save_analysis_cache
from kicad_dfm.services.analysis_cache import CachePayloadTooLarge
from kicad_dfm.services.analysis_cache import STARTUP_CACHE_MAX_BYTES
from kicad_dfm.services.analysis_cache import rules_fingerprint
from kicad_dfm.services.analysis_results import AnalysisStageResult
from kicad_dfm.services.analysis_results import CombinedAnalysisService
from kicad_dfm.services.analysis_results import COMBINED
from kicad_dfm.services.analysis_results import GERBER_ENRICHED
from kicad_dfm.services.analysis_results import GERBER_STRICT
from kicad_dfm.services.analysis_results import KICAD_NATIVE
from kicad_dfm.services.analysis_results import build_analysis_contract
from kicad_dfm.services.analysis_results import canonical_mode
from kicad_dfm.services.analysis_results import normalize_smd_spacing_results
from kicad_dfm.services.analysis_results import normalize_source_views
from kicad_dfm.services.export_checks import CATEGORY as GERBER_EXPORT_CATEGORY
from kicad_dfm.services.export_checks import analyze_export_with_results
from kicad_dfm.services.export_result_helpers import aggregate_color
from kicad_dfm.services.export_result_helpers import aggregate_physical_native_results
from kicad_dfm.services.export_result_helpers import grouped_native_results
from kicad_dfm.services.locate import LocatePlan
from kicad_dfm.services.locate import ResultLocationPlanner
from kicad_dfm.services.local_checks import declared_net_tie_pad_pair
from kicad_dfm.services.local_checks import local_net_tie_attachment_candidates
from kicad_dfm.services.native_drc import NativeDrcMarkerExporter
from kicad_dfm.services.offline_analysis import OfflineDfmAnalysis
from kicad_dfm.services.offline_analysis import COMPAT_CATEGORIES
from kicad_dfm.services.result_object_mapper import GerberResultObjectMapper
from kicad_dfm.ui.detail_frame import statistic_display
from kicad_dfm.ui.main_frame import (
    Workflow,
    default_summary_map,
    format_board_dimensions,
    load_ui_settings,
    select_language_control,
)
from kicad_dfm.core.logging import get_logger, info as log_info, error as log_error, log_dir
from kicad_dfm.core.i18n import _
from kicad_dfm.core.models import DfmSummary
from kicad_dfm.core.progress import AnalysisCancelled
from kicad_dfm.core.progress import report_progress
from kicad_dfm.core.units import mm_to_inches, mm_to_mils
from kicad_dfm.core.report import export_csv as export_report_csv
from kicad_dfm.core.report import export_html as export_report_html
from kicad_dfm.core.report import export_json as export_report_json
from kicad_dfm.core.rule_profiles import (
    profile_choices,
    rule_label,
    rules_for_profile,
    selected_profile_id,
)
from kicad_dfm.core.settings import save_settings
from kicad_dfm.kicad.swig import SwigBackend


GERBER_NET_TIE_CONTACT_TOLERANCE_NM = 1
GERBER_PAIR_MEASUREMENT_TIE_TOLERANCE_NM = 1
GERBER_COPPER_SPACING_ITEMS = frozenset(
    (
        "Trace Spacing",
        "Trace-to-Pad Spacing",
        "Pad-to-Pad Spacing",
        "BGA Pads",
        "SMD Pad Spacing",
    )
)


class DfmMainframe(wx.Frame):
    def __init__(self, parent):
        super(DfmMainframe, self).__init__(
            parent,
            title=_("HQ DFM"),
            style=wx.DEFAULT_FRAME_STYLE & ~(wx.MAXIMIZE_BOX) | wx.TAB_TRAVERSAL,
        )
        SINGLE_PLUGIN.register_main_wind(self)
        self._startup_cache_restore_scheduled = False
        self.workflow = Workflow()
        self.settings = load_ui_settings()
        self.logger = get_logger(__name__)
        self.language = KiCadSetting.read_lang_setting()
        self.control = select_language_control(self.language, config)
        if self.control is None:
            wx.MessageBox(
                _("The language you selected is currently not supported"),
                _("Help"),
                style=wx.ICON_INFORMATION,
            )
            return
        self.line_list = []
        self.have_progress = False
        self._analysis_cancel_requested = False
        self._saved_analysis_load_generation = 0
        self._closing = False
        try:
            pcbnew.GetBoard().GetFileName()
            self.board = pcbnew.GetBoard()
        except Exception:
            for fp in (
                "C:\\Program Files\\demos\\flat_hierarchy\\flat_hierarchy.kicad_pcb",
                "C:\\Program Files\\demos\\kit-dev-coldfire-xilinx_5213\\kit-dev-coldfire-xilinx_5213.kicad_pcb",
                "C:\\Program Files\\demos\\video\\video.kicad_pcb",

                "C:\\Program Files\\demos\\sondexilinx\\sonde xilinx.kicad_pcb",
                "C:\\Program Files\\demos\\stickhub\\StickHub.kicad_pcb",

                # "C:\\Users\\haf\\Desktop\\常用文档\\tiny-scarab.kicad_pcb",
                # "C:\\Program Files\\demos\\testDFM\\testDFM.kicad_pcb",
                # "C:\\Program Files\\demos\\microwave\\microwave.kicad_pcb",
                # "C:\\Program Files\\demos\\ecc83\\ecc83-pp_v2.kicad_pcb",
                # "C:\\Program Files\\demos\\N100.kicad_pcb",
                # "C:\\Program Files\\demos\\complex_hierarchy\\complex_hierarchy.kicad_pcb",
            ):
                if os.path.exists(fp):
                    self.board = pcbnew.LoadBoard(fp)

        self.path, self.filename = os.path.split(self.board.GetFileName())
        self.board_name = os.path.split(self.board.GetFileName())[1]
        self.name = os.path.splitext(self.board_name)[0]
        self.analysis_result = {}
        self.analysis_contract = {}
        self.source_views = {}
        self.analysis_cache_input_paths = ()
        self.unit = pcbnew.GetUserUnits()
        self.kicad_result = {}
        self.rule_message_list = []
        self.dfm_analysis = DfmAnalysis( self.board )
        self.backend = SwigBackend(self.board)
        self.native_drc_marker_exporter = NativeDrcMarkerExporter(self.board, backend=self.backend)
        self.hole_childframe = None
        self.pcb_setting = PcbSetting(self.board)
        self.item_result = _("no errors detected")
        self.json_analysis_map = {}
        self.SetIcon(wx.Icon(GetImagePath("icon.png"), wx.BITMAP_TYPE_PNG))  # 设置窗口图标
        self.dfm_maindialog = DfmMaindailogView(
            self,
            self.control,
            self.settings.get("summary_column_widths"),
            language=self.language,
        )
        self.sizer = wx.BoxSizer(wx.VERTICAL)
        self.sizer.Add(self.dfm_maindialog, 1, wx.EXPAND)
        self.SetSizer(self.sizer)

        self.SetMinSize(wx.Size(610, 1030))
        self.SetSize(wx.Size(610, 1030))
        self.Layout()
        self.Centre(wx.BOTH)
        self.init_rule_profile_choice()
        self.init_data_view()
        self.dfm_maindialog.dfm_run_button.Bind(
            wx.EVT_BUTTON, self.on_select_native_dfm
        )
        self.dfm_maindialog.gerber_dfm_button.Bind(
            wx.EVT_BUTTON, self.on_select_combined_dfm
        )
        self.configure_analysis_entry_buttons()
        self.dfm_maindialog.stop_check_button.Bind(
            wx.EVT_BUTTON, self.on_stop_analysis
        )
        self.dfm_maindialog.rule_manager_button.Bind(
            wx.EVT_BUTTON, self.show_rule_manager
        )
        self.dfm_maindialog.reset_visible_layers_button.Bind(
            wx.EVT_BUTTON, self.on_reset_visible_layers
        )
        self.dfm_maindialog.inject_drc_markers_button.Bind(
            wx.EVT_BUTTON, self.on_inject_native_drc_markers
        )
        self.dfm_maindialog.clear_drc_markers_button.Bind(
            wx.EVT_BUTTON, self.on_clear_native_drc_markers
        )
        self.configure_native_drc_marker_buttons()
        self.dfm_maindialog.signal_integrity_button.Bind(
            wx.EVT_BUTTON, self.show_signal_integrity_button
        )
        self.dfm_maindialog.smallest_trace_width_button.Bind(
            wx.EVT_BUTTON, self.show_smallest_trace_width_button
        )
        self.dfm_maindialog.smallest_trace_spacing_button.Bind(
            wx.EVT_BUTTON, self.show_smallest_trace_spacing_button
        )
        self.dfm_maindialog.smd_spacing_button.Bind(
            wx.EVT_BUTTON, self.show_smd_spacing_button
        )
        self.dfm_maindialog.pad_size_button.Bind(
            wx.EVT_BUTTON, self.show_pad_size_button
        )
        self.dfm_maindialog.hole_diameter_button.Bind(
            wx.EVT_BUTTON, self.show_hole_diameter_button
        )
        self.dfm_maindialog.ringHole_button.Bind(
            wx.EVT_BUTTON, self.show_ringHole_button
        )
        self.dfm_maindialog.drill_hole_spacing_button.Bind(
            wx.EVT_BUTTON, self.show_drill_hole_spacing_button
        )
        self.dfm_maindialog.drill_to_copper_button.Bind(
            wx.EVT_BUTTON, self.show_drill_to_copper_button
        )
        self.dfm_maindialog.board_edge_clearance_button.Bind(
            wx.EVT_BUTTON, self.show_board_edge_clearance_button
        )
        self.dfm_maindialog.hole_to_board_edge_button.Bind(
            wx.EVT_BUTTON, self.show_hole_to_board_edge_button
        )
        self.dfm_maindialog.special_drill_holes_button.Bind(
            wx.EVT_BUTTON, self.show_special_drill_holes_button
        )
        self.dfm_maindialog.holes_on_smd_pads_button.Bind(
            wx.EVT_BUTTON, self.show_holes_on_smd_pads_button
        )
        self.dfm_maindialog.missing_mask_openings_button.Bind(
            wx.EVT_BUTTON, self.show_missing_mask_openings_button
        )
        self.dfm_maindialog.solder_mask_analysis_button.Bind(
            wx.EVT_BUTTON, self.show_solder_mask_analysis_button
        )
        self.dfm_maindialog.drill_hole_density_button.Bind(
            wx.EVT_BUTTON, self.show_drill_hole_density_button
        )
        self.dfm_maindialog.surface_finish_area_button.Bind(
            wx.EVT_BUTTON, self.show_surface_finish_area_button
        )
        self.dfm_maindialog.test_point_count_button.Bind(
            wx.EVT_BUTTON, self.show_test_point_count_button
        )
        self.Bind(wx.EVT_CLOSE, self.on_close)
        self._last_dpi_scale = self.dfm_maindialog.current_dpi_scale()
        if hasattr(wx, "EVT_DPI_CHANGED"):
            self.Bind(wx.EVT_DPI_CHANGED, self.on_dpi_changed)
        if hasattr(wx, "EVT_MOVE"):
            self.Bind(wx.EVT_MOVE, self.on_window_moved)

    def Show(self, show=True):
        shown = super(DfmMainframe, self).Show(show)
        if (
            show
            and not self._startup_cache_restore_scheduled
            and hasattr(self, "board")
            and hasattr(self, "dfm_maindialog")
        ):
            self._startup_cache_restore_scheduled = True
            # Queue after Show() so constructing the frame and its first display
            # never wait for filesystem or JSON work.
            wx.CallAfter(self.schedule_saved_analysis_load)
        return shown


    def init_data_view(self):
        # record pcblayer and object visibility
        self.gal_set = self.board.GetVisibleLayers()
        self.ele_gal_set = self.board.GetVisibleElements()

        self.json_analysis_map = default_summary_map(_)
        self.dfm_maindialog.init_data_view(self.json_analysis_map)

    def schedule_saved_analysis_load(self):
        """Restore a bounded cache after the window gets its first paint."""
        self._saved_analysis_load_generation = (
            getattr(self, "_saved_analysis_load_generation", 0) + 1
        )
        generation = self._saved_analysis_load_generation
        board_path = self.board.GetFileName()
        profile_id = self.current_rule_profile_id()
        rules = rules_for_profile(profile_id)
        request = {
            "generation": generation,
            "board_path": board_path,
            "profile_id": profile_id,
            "rules": rules,
            "rules_digest": rules_fingerprint(profile_id, rules),
            "language": self.language,
            "board_file_state": self._board_file_state(board_path),
        }
        # This callback cannot run until the current plugin click handler returns.
        # BaseApp calls Show() before that happens, so cache I/O is never on the
        # first-paint path.
        wx.CallAfter(self._start_saved_analysis_load, request)

    def _start_saved_analysis_load(self, request):
        if not self._saved_analysis_request_is_current(request):
            return
        worker = threading.Thread(
            target=self._load_saved_analysis_worker,
            args=(request,),
            name="hqdfm-cache-restore",
            daemon=True,
        )
        self._saved_analysis_load_thread = worker
        worker.start()

    def _load_saved_analysis_worker(self, request):
        cached = None
        error = None
        try:
            cached = load_analysis_cache(
                request["board_path"],
                request["profile_id"],
                request["language"],
                rules=request["rules"],
                max_payload_bytes=STARTUP_CACHE_MAX_BYTES,
            )
        except Exception as exc:
            error = exc
        try:
            wx.CallAfter(self._finish_saved_analysis_load, request, cached, error)
        except RuntimeError:
            # wx may already be shutting down while this daemon finishes.
            return

    def _finish_saved_analysis_load(self, request, cached, error=None):
        if not self._saved_analysis_request_is_current(request):
            return False
        if error is not None:
            self.logger.warning("analysis cache lookup failed: %s", error)
            return False
        if not cached:
            self.logger.info(
                "no valid startup cache within %d MiB; leaving results empty",
                STARTUP_CACHE_MAX_BYTES // (1024 * 1024),
            )
            return False
        return self.apply_saved_analysis(cached)

    def _saved_analysis_request_is_current(self, request):
        if getattr(self, "_closing", False):
            return False
        try:
            is_being_deleted = getattr(self, "IsBeingDeleted", None)
            if callable(is_being_deleted) and is_being_deleted():
                return False
        except RuntimeError:
            return False
        if request["generation"] != getattr(
            self, "_saved_analysis_load_generation", 0
        ):
            return False
        if getattr(getattr(self, "workflow", None), "running", False):
            return False
        if getattr(self, "analysis_result", None):
            return False
        try:
            is_modified = getattr(self.board, "IsModified", None)
            if callable(is_modified) and is_modified():
                return False
            board_path = self.board.GetFileName()
            if os.path.normcase(os.path.abspath(board_path)) != os.path.normcase(
                os.path.abspath(request["board_path"])
            ):
                return False
            if self._board_file_state(board_path) != request.get("board_file_state"):
                return False
            if self.current_rule_profile_id() != request["profile_id"]:
                return False
            current_rules = rules_for_profile(request["profile_id"])
            return rules_fingerprint(
                request["profile_id"], current_rules
            ) == request["rules_digest"]
        except Exception:
            return False

    @staticmethod
    def _board_file_state(board_path):
        try:
            stat = os.stat(board_path)
            return (
                stat.st_size,
                getattr(stat, "st_mtime_ns", int(stat.st_mtime * 1000000000)),
            )
        except OSError:
            return None

    def cancel_saved_analysis_load(self):
        self._saved_analysis_load_generation = (
            getattr(self, "_saved_analysis_load_generation", 0) + 1
        )

    def on_dpi_changed(self, event):
        event.Skip()
        wx.CallAfter(self.refresh_for_current_dpi, True)

    def on_window_moved(self, event):
        event.Skip()
        wx.CallAfter(self.refresh_for_current_dpi)

    def refresh_for_current_dpi(self, force=False):
        scale = self.dfm_maindialog.current_dpi_scale()
        if not force and abs(scale - self._last_dpi_scale) < 0.001:
            return
        self._last_dpi_scale = scale
        self.dfm_maindialog.refresh_dpi_layout()
        self.Layout()

    def init_rule_profile_choice(self):
        self.rule_profile_ids = []
        self.dfm_maindialog.rule_profile_sizer.Clear(True)
        self.dfm_maindialog.rule_profile_buttons = []
        for profile_id, label in profile_choices(_, self.control):
            self.rule_profile_ids.append(profile_id)
            style = wx.RB_GROUP if not self.dfm_maindialog.rule_profile_buttons else 0
            button = wx.RadioButton(
                self.dfm_maindialog.rule_profile_panel,
                wx.ID_ANY,
                label,
                style=style,
            )
            button.Bind(wx.EVT_RADIOBUTTON, self.on_rule_profile_changed)
            self.dfm_maindialog.rule_profile_buttons.append(button)
            self.dfm_maindialog.rule_profile_sizer.Add(
                button, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 10
            )
        selected = selected_profile_id(self.settings)
        try:
            index = self.rule_profile_ids.index(selected)
        except ValueError:
            index = 0
        if self.rule_profile_ids:
            self.dfm_maindialog.rule_profile_buttons[index].SetValue(True)
            self.settings["rule_profile"] = self.rule_profile_ids[index]
        self.dfm_maindialog.rule_profile_panel.Layout()

    def on_rule_profile_changed(self, event):
        self.cancel_saved_analysis_load()
        selection = self.selected_rule_profile_index()
        if 0 <= selection < len(self.rule_profile_ids):
            self.settings["rule_profile"] = self.rule_profile_ids[selection]
            save_settings(self.settings)
            if self.analysis_result:
                rules = rules_for_profile(self.rule_profile_ids[selection])
                result = self._analyze_native_stage(rules)
                self.apply_native_stage_result(result)
                self.add_all_item(use_existing_kicad_result=True)
                self.sync_native_drc_markers()
            else:
                self.schedule_saved_analysis_load()
        event.Skip()

    def current_rule_profile_id(self):
        selection = self.selected_rule_profile_index()
        if 0 <= selection < len(self.rule_profile_ids):
            return self.rule_profile_ids[selection]
        return selected_profile_id(self.settings)

    def selected_rule_profile_index(self):
        for index, button in enumerate(self.dfm_maindialog.rule_profile_buttons):
            if button.GetValue():
                return index
        return -1

    def current_rules(self):
        profile_id = self.current_rule_profile_id()
        self.settings["rule_profile"] = profile_id
        save_settings(self.settings)
        return rules_for_profile(profile_id)

    @staticmethod
    def complete_compat_results(results):
        """Return a legacy UI map with every fixed-index category present."""
        completed = normalize_smd_spacing_results(results)
        for category in COMPAT_CATEGORIES:
            completed.setdefault(category, "")
        return completed

    @staticmethod
    def complete_stage_contract(result, analysis_result):
        contract = copy.deepcopy(result.contract or {})
        categories = contract.get("categories") or {}
        if all(category in categories for category in COMPAT_CATEGORIES):
            return contract
        return build_analysis_contract(
            result.mode,
            analysis_result,
            result.issues,
            result.summary,
            categories=COMPAT_CATEGORIES,
            profile=result.profile,
            execution_status=contract.get("execution_status", "completed"),
            metadata=contract.get("metadata") or {},
        )

    def apply_native_stage_result(self, result):
        """Atomically replace any prior combined/Gerber view with native state."""
        analysis_result = self.complete_compat_results(result.analysis_result)
        kicad_result = self.complete_compat_results(result.kicad_result)
        self.analysis_result = analysis_result
        self.kicad_result = kicad_result
        self.analysis_contract = copy.deepcopy(result.contract)
        self.source_views = normalize_source_views({
            KICAD_NATIVE: {
                "analysis_result": copy.deepcopy(analysis_result),
                "kicad_result": copy.deepcopy(kicad_result),
                "issues": tuple(result.issues or ()),
                "summary": copy.deepcopy(result.summary),
                "profile": copy.deepcopy(result.profile),
                "contract": copy.deepcopy(result.contract),
                "input_paths": (),
            }
        })
        self.analysis_cache_input_paths = ()
        self.dfm_analysis.dfm_issues = tuple(result.issues or ())
        self.dfm_analysis.dfm_summary = copy.deepcopy(result.summary)

    def on_reset_visible_layers(self, event):
        self.show_all_visible_layers()
        event.Skip()

    def on_inject_native_drc_markers(self, event):
        exported, skipped = self.inject_native_drc_markers()
        if exported:
            wx.MessageBox(
                _("Injected {count} HQ DFM marker(s).").format(count=exported),
                _("Info"),
                style=wx.ICON_INFORMATION,
            )
        else:
            wx.MessageBox(
                _("No UUID-backed DFM results are available for native DRC markers."),
                _("Info"),
                style=wx.ICON_INFORMATION,
            )
        if skipped:
            self.logger.debug("native_drc_marker skipped=%s", skipped)
        event.Skip()

    def configure_native_drc_marker_buttons(self):
        supported = self.supports_native_drc_marker_auto_sync()
        buttons = (
            self.dfm_maindialog.inject_drc_markers_button,
            self.dfm_maindialog.clear_drc_markers_button,
        )
        for button in buttons:
            button.Enable(supported)
            if not supported and hasattr(button, "SetToolTip"):
                button.SetToolTip(
                    _("Native DRC marker injection is unavailable in KiCad 8, 9, and 10.")
                )

    def on_clear_native_drc_markers(self, event):
        cleared = self.clear_native_drc_markers()
        wx.MessageBox(
            _("Cleared {count} HQ DFM marker(s).").format(count=cleared),
            _("Info"),
            style=wx.ICON_INFORMATION,
        )
        event.Skip()

    def inject_native_drc_markers(self):
        if not self.supports_native_drc_marker_auto_sync():
            self.clear_native_drc_markers(refresh=False)
            return 0, 0
        self.clear_native_drc_markers(refresh=False)
        exported = 0
        skipped = 0
        for category, plan in self.native_drc_marker_plans():
            result = self.native_drc_marker_exporter.export(plan, category=category)
            exported += len(result.markers)
            skipped += len(result.skipped)
        if exported:
            pcbnew.UpdateUserInterface()
            pcbnew.Refresh()
        return exported, skipped

    def sync_native_drc_markers(self):
        if not self.supports_native_drc_marker_auto_sync():
            self.clear_native_drc_markers(refresh=False)
            return 0, 0
        exported, skipped = self.inject_native_drc_markers()
        if skipped:
            self.logger.debug("native_drc_marker auto_sync skipped=%s", skipped)
        self.logger.debug(
            "native_drc_marker auto_sync exported=%s skipped=%s",
            exported,
            skipped,
        )
        return exported, skipped

    def supports_native_drc_marker_auto_sync(self):
        try:
            capabilities = self.backend.capabilities()
        except Exception:
            return False
        return bool(getattr(capabilities, "can_native_drc_marker", False))

    def clear_native_drc_markers(self, refresh=True):
        count = len(self.native_drc_marker_exporter.markers)
        self.native_drc_marker_exporter.clear()
        if count and refresh:
            pcbnew.UpdateUserInterface()
            pcbnew.Refresh()
        return count

    def native_drc_marker_plans(self):
        planner = ResultLocationPlanner(self.backend)
        for category, row in self.iter_native_drc_marker_rows():
            plan = planner.plan_native_items(row)
            if plan.items:
                yield category, LocatePlan(items=plan.items)

    def iter_native_drc_marker_rows(self):
        seen = set()
        for result_map in (self.kicad_result, self.analysis_result):
            if not isinstance(result_map, dict):
                continue
            for category, data in result_map.items():
                if not isinstance(data, dict):
                    continue
                for check in data.get("check") or ():
                    if not isinstance(check, dict):
                        continue
                    for row in check.get("result") or ():
                        if not isinstance(row, dict):
                            continue
                        mapping = (row.get("raw") or {}).get("uuid_mapping") or {}
                        if row.get("source") in ("gerber", "drill") and mapping.get("status") != "matched":
                            continue
                        row_key = (category, row.get("id"), row.get("related_id"), row.get("uuid"))
                        if row_key in seen:
                            continue
                        seen.add(row_key)
                        yield category, row

    def show_all_visible_layers(self):
        self.backend.set_visible_alls()
        pcbnew.UpdateUserInterface()
        pcbnew.Refresh()

    def restore_initial_visibility(self):
        self.board.SetVisibleLayers(self.gal_set)
        self.board.SetVisibleElements(self.ele_gal_set)
        pcbnew.UpdateUserInterface()
        pcbnew.Refresh()

    def on_close(self, event):
        if getattr(self, "_closing", False):
            return
        self._closing = True
        self.cancel_saved_analysis_load()
        try:
            self.persist_summary_column_widths()
        except Exception:
            self.logger.exception("Failed to save summary column widths")
        try:
            self.close_owned_windows()
            self.restore_initial_visibility()
            self.clear_native_drc_markers(refresh=False)
            for line in tuple(self.line_list):
                try:
                    self.board.Delete(line)
                except Exception:
                    self.logger.debug("temporary shape already removed during close", exc_info=True)
        except Exception:
            self.logger.exception("Error during close")
        finally:
            SINGLE_PLUGIN.register_main_wind(None)
            self.Destroy()

    def persist_summary_column_widths(self):
        self.settings["summary_column_widths"] = (
            self.dfm_maindialog.summary_column_widths()
        )
        save_settings(self.settings)

    def close_owned_windows(self):
        """Close every top-level window owned by this DFM session."""
        for window in tuple(wx.GetTopLevelWindows()):
            if window is self:
                continue
            try:
                if window.GetParent() is not self:
                    continue
                window.Close(True)
            except Exception:
                self.logger.debug("owned window close failed; forcing destroy", exc_info=True)
                try:
                    window.Destroy()
                except Exception:
                    self.logger.debug("owned window was already destroyed", exc_info=True)

    def add_temp_json(self):
        json_name = GetFilePath("temp.json")
        temp_filename = GetFilePath("name.json")
        if os.path.exists(temp_filename) and os.path.exists(json_name):
            try:
                with open(temp_filename, "r", encoding="utf-8") as stream:
                    data = json.load(stream)
            except (OSError, ValueError):
                self.logger.warning("Ignoring unreadable remote-analysis name cache: %s", temp_filename)
                return
            cached_name = data.get("name", "") if isinstance(data, dict) else ""
            if cached_name:
                if cached_name == self.name or "*" + cached_name == self.name:
                    if self.language == "简体中文":
                        self.analysis_result = self.dfm_analysis.analysis_json(
                            json_name, True
                        )
                    else:
                        self.analysis_result = self.dfm_analysis.analysis_json(
                            json_name
                        )
                    if self.analysis_result == "":
                        wx.MessageBox(
                            _("File parsing failed. Please click dfm analysis."),
                            _("Help"),
                            style=wx.ICON_INFORMATION,
                        )
                        return
                    self.add_all_item()

    def load_saved_analysis(self, max_payload_bytes=None):
        profile_id = self.current_rule_profile_id()
        try:
            cached = load_analysis_cache(
                self.board.GetFileName(),
                profile_id,
                self.language,
                rules=rules_for_profile(profile_id),
                max_payload_bytes=max_payload_bytes,
            )
        except OSError:
            self.logger.debug("analysis cache lookup failed", exc_info=True)
            return False
        if not cached:
            return False
        return self.apply_saved_analysis(cached)

    def apply_saved_analysis(self, cached):
        self.analysis_result = self.complete_compat_results(cached["analysis_result"])
        self.kicad_result = self.complete_compat_results(cached["kicad_result"])
        self.analysis_contract = cached.get("contract") or {}
        # load_analysis_cache already returns the normalized runtime schema.
        self.source_views = cached.get("source_views") or {}
        self.analysis_cache_input_paths = cached.get("input_paths") or ()
        self.dfm_analysis.dfm_issues = cached["issues"]
        self.dfm_analysis.dfm_summary = cached["summary"]
        self.add_all_item(use_existing_kicad_result=True)
        self.logger.info("loaded saved DFM analysis: %s", cached["path"])
        return True

    def save_current_analysis(self, mode):
        return self.save_analysis_snapshot(
            mode,
            self.analysis_result,
            self.kicad_result,
            self.dfm_analysis.dfm_issues,
            self.dfm_analysis.dfm_summary,
            self.analysis_contract,
            self.analysis_cache_input_paths,
        )

    def save_analysis_snapshot(
        self,
        mode,
        analysis_result,
        kicad_result,
        issues,
        summary,
        contract=None,
        input_paths=(),
        rules=None,
        source_views=None,
    ):
        try:
            if source_views is None:
                try:
                    current_mode = canonical_mode((self.analysis_contract or {}).get("mode"))
                except ValueError:
                    current_mode = None
                source_views = (
                    self.source_views
                    if current_mode == canonical_mode(mode)
                    else {}
                )
            path = save_analysis_cache(
                self.board.GetFileName(),
                self.current_rule_profile_id(),
                mode,
                analysis_result,
                kicad_result,
                issues,
                summary,
                self.language,
                input_paths=input_paths,
                rules=rules if rules is not None else self.current_rules(),
                contract=contract,
                source_views=source_views,
            )
            self.logger.info("saved DFM analysis: %s", path)
            return path
        except CachePayloadTooLarge as exc:
            self.logger.warning("analysis cache not saved: %s", exc)
            return None
        except OSError:
            self.logger.exception("unable to save DFM analysis cache")
            return None

    def get_file_name(self):
        title_name = self.title_name
        name = title_name.partition("— PCB")
        return name[0]

    # 只出现一个查看窗口
    def have_same_class_window(self):
        for line in self.line_list:
            self.board.Delete(line)
        pcbnew.Refresh()
        title_name = [
            _("Signal Integrity"),
            _("Smallest Trace Width"),
            _("Smallest Trace Spacing"),
            _("SMD Spacing"),
            _("Pad size"),
            _("Hole Size"),
            _("RingHole"),
            _("Drill Hole Spacing"),
            _("Drill to Copper"),
            _("Copper-to-Board Edge"),
            _("Hole-to-Board Edge"),
            _("Special Drill Holes"),
            _("Holes on SMD Pads"),
            _("Missing SMask Openings"),
            _("Solder Mask Analysis"),
            _("Surface Finish Area"),
            _("Test Point Count"),
            _("Drill Hole Density"),
        ]
        for win in wx.GetTopLevelWindows():
            if win.GetTitle() in title_name:
                win.Destroy()

    def create_child_frame(
        self, title, analysis_result, jsonfile_string, is_kicad_result=False
    ):
        if not self.has_detail_result(analysis_result, jsonfile_string, is_kicad_result):
            wx.MessageBox(
                _("No detailed issues are available for this item. Please run DFM analysis first, or this item has no detected issues."),
                _("Info"),
                style=wx.ICON_INFORMATION,
            )
            return
        try:
            wx.BeginBusyCursor()
            self.have_same_class_window()
            child_frame = DfmChildFrame(
                self,
                title,
                analysis_result,
                jsonfile_string,
                self.line_list,
                self.unit,
                self.board,
                is_kicad_result,
            )

            child_frame.Show()
        finally:
            wx.EndBusyCursor()

    def has_detail_result(self, analysis_result, jsonfile_string, is_kicad_result=False):
        result = analysis_result.get(jsonfile_string) if isinstance(analysis_result, dict) else None
        if not isinstance(result, dict):
            return False
        if not any(self.iter_result_rows(result)):
            return False
        if is_kicad_result:
            return True
        return bool(self.result_violation_color(result))

    @staticmethod
    def iter_result_rows(result):
        if not isinstance(result, dict):
            return
        for check in result.get("check") or ():
            if not isinstance(check, dict):
                continue
            for row in check.get("result") or ():
                if isinstance(row, dict):
                    yield row

    @classmethod
    def result_violation_color(cls, result):
        """Return the worst violation color without reading localized display text."""
        if not isinstance(result, dict):
            return ""
        count_is_valid = False
        violation_count = result.get("violation_count")
        if violation_count is not None:
            try:
                count_is_valid = True
                if float(violation_count) <= 0:
                    return ""
            except (TypeError, ValueError):
                count_is_valid = False

        row_color = ""
        for row in cls.iter_result_rows(result):
            color = str(row.get("color") or "").lower()
            severity = str(row.get("severity") or "").lower()
            if color == "red" or severity in ("error", "fatal", "critical"):
                row_color = "red"
                break
            if color == "gold" or severity == "warning":
                row_color = "gold"
        parent_color = str(result.get("color") or "").lower()
        colors = (row_color, parent_color)
        if "red" in colors:
            return "red"
        if "gold" in colors:
            return "gold"
        return "red" if count_is_valid else ""

    def apply_signal_integrity_summary(self):
        signal_result = self.analysis_result.get("Signal Integrity")
        issue_color = self.result_violation_color(signal_result)
        summary = self.json_analysis_map[_("Signal Integrity")]
        if issue_color:
            summary["display"] = _("Error(s) detected")
            summary["color"] = issue_color
        else:
            summary["display"] = self.item_result
            summary["color"] = ""

    # 每个查看按钮
    def show_signal_integrity_button(self, event):
        self.create_child_frame(
            _("Signal Integrity"), self.analysis_result, "Signal Integrity"
        )

    def show_smallest_trace_width_button(self, event):
        self.create_child_frame(
            _("Smallest Trace Width"), self.kicad_result, "Smallest Trace Width", True
        )

    def show_smallest_trace_spacing_button(self, event):
        self.create_child_frame(
            _("Smallest Trace Spacing"), self.analysis_result, "Smallest Trace Spacing"
        )

    def show_smd_spacing_button(self, event):
        self.create_child_frame(
            _("SMD Spacing"), self.analysis_result, "SMD Spacing"
        )

    def show_pad_size_button(self, event):
        self.create_child_frame(_("Pad size"), self.kicad_result, "Pad size", True)

    def show_hole_diameter_button(self, event):
        self.create_child_frame(
            _("Hole Size"), self.analysis_result, "Hole Size"
        )

    def show_ringHole_button(self, event):
        self.create_child_frame(_("RingHole"), self.kicad_result, "RingHole", True)

    def show_drill_hole_spacing_button(self, event):
        self.create_child_frame(
            _("Drill Hole Spacing"), self.analysis_result, "Drill Hole Spacing"
        )

    def show_drill_to_copper_button(self, event):
        self.create_child_frame(
            _("Drill to Copper"), self.analysis_result, "Drill to Copper"
        )

    def show_board_edge_clearance_button(self, event):
        self.create_child_frame(
            _("Copper-to-Board Edge"), self.analysis_result, "Copper-to-Board Edge"
        )

    def show_hole_to_board_edge_button(self, event):
        self.create_child_frame(
            _("Hole-to-Board Edge"),
            self.analysis_result,
            "Hole-to-Board Edge",
        )

    def show_special_drill_holes_button(self, event):
        self.create_child_frame(
            _("Special Drill Holes"), self.analysis_result, "Special Drill Holes"
        )

    def show_holes_on_smd_pads_button(self, event):
        self.create_child_frame(
            _("Holes on SMD Pads"), self.analysis_result, "Holes on SMD Pads"
        )

    def show_missing_mask_openings_button(self, event):
        self.create_child_frame(
            _("Missing SMask Openings"), self.analysis_result, "Missing SMask Openings"
        )

    def show_solder_mask_analysis_button(self, event):
        self.create_child_frame(
            _("Solder Mask Analysis"), self.analysis_result, "Solder Mask Analysis"
        )

    def show_drill_hole_density_button(self, event):
        self.show_statistic_detail("Drill Hole Density")

    def show_surface_finish_area_button(self, event):
        self.show_statistic_detail("Surface Finish Area")

    def show_test_point_count_button(self, event):
        self.show_statistic_detail("Test Point Count")

    def show_gerber_export_issues(self, summary):
        export_summary = (summary or {}).get(GERBER_EXPORT_CATEGORY)
        issues = tuple(export_summary.issues if export_summary is not None else ())
        if not issues:
            return False
        wx.MessageDialog(
            self,
            self.gerber_export_issue_text(issues),
            _("Gerber File Integrity"),
            wx.OK | wx.ICON_INFORMATION,
        ).ShowModal()
        return True

    def gerber_export_issue_text(self, issues):
        lines = []
        for index, issue in enumerate(issues, start=1):
            message = issue.message or issue.item
            lines.append("{0}. [{1}] {2}: {3}".format(index, issue.severity, issue.item, message))
        return "\n".join(lines)

    def show_statistic_detail(self, name):
        self.have_same_class_window()
        display_value = statistic_display(self.analysis_result, name, self.item_result)
        HoleChildFrameView(self, display_value, _(name)).Show()

    def open_log_dir(self):
        log_info(self.logger, "open log dir")
        return log_dir()

    def export_report(self, path, report_type="html"):
        if report_type == "json":
            return export_report_json(self.json_analysis_map, path)
        if report_type == "csv":
            return export_report_csv(self.json_analysis_map, path)
        return export_report_html(self.json_analysis_map, path)

    def on_select_combined_dfm(self, event):
        self._run_analysis_entry("combined", self.run_combined_analysis)

    def on_select_export_gerber(self, event):
        """Compatibility alias for the former combined-entry callback."""
        return self.on_select_combined_dfm(event)

    def on_select_native_dfm(self, event):
        self._run_analysis_entry("native", self.run_offline_analysis)

    def on_select_gerber_dfm(self, event):
        """Retained compatibility entry for the standalone Gerber pipeline."""
        self._run_analysis_entry("gerber export", self.run_online_analysis)

    def _run_analysis_entry(self, workflow_name, runner):
        if not self.workflow.start_analysis():
            return

        self.begin_analysis_progress()
        try:
            log_info(
                self.logger,
                "{0} analysis workflow started".format(workflow_name),
            )
            runner()
        except AnalysisCancelled:
            self.workflow.cancel()
            log_info(
                self.logger,
                "{0} analysis workflow stopped by user".format(workflow_name),
            )
            wx.MessageBox(_("Check stopped."), _("Info"), style=wx.ICON_INFORMATION)
        except Exception as exc:
            self.workflow.fail(exc)
            self.logger.exception(
                "%s analysis workflow failed",
                workflow_name,
            )
            log_error(self.logger, exc)
            wx.MessageBox(str(exc), _("Error"), style=wx.ICON_ERROR)
        finally:
            self.have_progress = False
            self.end_analysis_progress()

    def run_offline_analysis(self):
        self.workflow.parsing()
        rules = self.current_rules()
        result = self._analyze_native_stage(
            rules,
            self.scaled_analysis_progress(0, 90),
        )
        self.analysis_checkpoint(90, 100, "Finalizing results")
        self.apply_native_stage_result(result)
        self.add_all_item(use_existing_kicad_result=True)
        self.analysis_checkpoint(94, 100, "Finalizing results")
        self.sync_native_drc_markers()
        self.analysis_checkpoint(96, 100, "Saving analysis cache")
        self.save_analysis_snapshot(
            KICAD_NATIVE,
            result.analysis_result,
            result.kicad_result,
            result.issues,
            result.summary,
            result.contract,
            rules=rules,
        )
        self.analysis_checkpoint(100, 100, "Finalizing results")
        self.workflow.done()
        wx.MessageDialog(
            self,
            _("Quick DFM check completed."),
            _("Info"),
            wx.OK | wx.ICON_INFORMATION,
        ).ShowModal()

    def run_online_analysis(self):
        self.workflow.parsing()
        rules = self.current_rules()
        result = self._analyze_gerber_stage(
            rules,
            self.scaled_analysis_progress(0, 10),
            self.scaled_analysis_progress(10, 90),
        )
        self.analysis_checkpoint(90, 100, "Finalizing results")
        analysis_result = self.complete_compat_results(result.analysis_result)
        kicad_source = copy.deepcopy(analysis_result)
        if isinstance(result.kicad_result, dict):
            kicad_source.update(result.kicad_result)
        kicad_result = self.complete_compat_results(kicad_source)
        analysis_contract = self.complete_stage_contract(result, analysis_result)
        self.analysis_result = analysis_result
        self.kicad_result = kicad_result
        self.analysis_contract = analysis_contract
        source_views = copy.deepcopy(result.source_views)
        source_views[GERBER_ENRICHED] = {
            "analysis_result": copy.deepcopy(analysis_result),
            "kicad_result": copy.deepcopy(kicad_result),
            "issues": tuple(result.issues or ()),
            "summary": copy.deepcopy(result.summary),
            "profile": copy.deepcopy(result.profile),
            "contract": copy.deepcopy(analysis_contract),
            "input_paths": tuple(result.input_paths or ()),
            "export_summary": copy.deepcopy(result.export_summary),
        }
        self.source_views = normalize_source_views(source_views)
        self.analysis_cache_input_paths = result.input_paths
        self.dfm_analysis.dfm_issues = result.issues
        self.dfm_analysis.dfm_summary = result.summary
        self.add_all_item(use_existing_kicad_result=True)
        self.analysis_checkpoint(94, 100, "Finalizing results")
        self.sync_native_drc_markers()
        self.analysis_checkpoint(96, 100, "Saving analysis cache")
        self.save_analysis_snapshot(
            GERBER_ENRICHED,
            analysis_result,
            kicad_result,
            result.issues,
            result.summary,
            analysis_contract,
            result.input_paths,
            rules,
        )
        self.analysis_checkpoint(100, 100, "Finalizing results")
        self.workflow.done()
        if not self.show_gerber_export_issues(result.export_summary):
            wx.MessageDialog(
                self,
                _("Gerber export check completed locally."),
                _("Info"),
                wx.OK | wx.ICON_INFORMATION,
            ).ShowModal()

    def run_combined_analysis(self):
        """Run native then Gerber analysis and publish one merged UI result."""
        self.workflow.parsing()
        rules = self.current_rules()

        def native_runner():
            stage = self._analyze_native_stage(
                rules,
                self.scaled_analysis_progress(0, 55),
            )
            self.analysis_checkpoint(55, 100, "Preparing Gerber analysis")
            return stage

        def gerber_runner():
            stage = self._analyze_gerber_stage(
                rules,
                self.scaled_analysis_progress(55, 65),
                self.scaled_analysis_progress(65, 95),
            )
            self.analysis_checkpoint(95, 100, "Merging analysis results")
            return stage

        service = CombinedAnalysisService(
            native_runner,
            gerber_runner,
        )
        result = service.run()
        self.analysis_checkpoint(96, 100, "Merging analysis results")
        analysis_result = self.complete_compat_results(result.analysis_result)
        kicad_result = self.complete_compat_results(result.kicad_result)
        self.analysis_result = analysis_result
        self.kicad_result = kicad_result
        self.analysis_contract = result.contract
        self.source_views = result.source_views
        self.analysis_cache_input_paths = result.gerber.input_paths
        self.dfm_analysis.dfm_issues = result.issues
        self.dfm_analysis.dfm_summary = result.summary

        self.add_all_item(use_existing_kicad_result=True)
        self.analysis_checkpoint(97, 100, "Finalizing results")
        self.sync_native_drc_markers()
        self.analysis_checkpoint(98, 100, "Saving analysis cache")
        self.save_analysis_snapshot(
            KICAD_NATIVE,
            result.native.analysis_result,
            result.native.kicad_result,
            result.native.issues,
            result.native.summary,
            result.native.contract,
            rules=rules,
        )
        self.analysis_checkpoint(99, 100, "Saving analysis cache")
        self.save_analysis_snapshot(
            COMBINED,
            analysis_result,
            kicad_result,
            result.issues,
            result.summary,
            result.contract,
            result.gerber.input_paths,
            rules,
        )
        self.analysis_checkpoint(100, 100, "Finalizing results")
        self.workflow.done()
        if not self.show_gerber_export_issues(result.gerber.export_summary):
            wx.MessageDialog(
                self,
                _("Combined DFM analysis completed."),
                _("Info"),
                wx.OK | wx.ICON_INFORMATION,
            ).ShowModal()

    def _analyze_native_stage(self, rules, progress_callback=None):
        return OfflineDfmAnalysis(
            self.board,
            self.control,
            backend=self.backend,
            rules=rules,
        ).analyze(progress_callback, self.analysis_cancelled)

    def _analyze_gerber_stage(
        self,
        rules,
        progress_callback=None,
        analysis_progress_callback=None,
    ):
        progress_callback = progress_callback or self.scaled_analysis_progress(0, 10)
        analysis_progress_callback = (
            analysis_progress_callback or self.scaled_analysis_progress(10, 90)
        )
        strict_progress_callback = self.scaled_progress_callback(
            analysis_progress_callback,
            0,
            75,
        )
        enrichment_progress_callback = self.scaled_progress_callback(
            analysis_progress_callback,
            75,
            100,
        )
        if progress_callback(0, 2, "Saving board") is False or self.analysis_cancelled():
            raise AnalysisCancelled()
        pcbnew.SaveBoard(self.board.GetFileName(), self.board)
        filename = GetFilePath("temp.json")
        if os.path.exists(filename):
            os.remove(filename)
        if (
            progress_callback(1, 2, "Exporting fabrication files") is False
            or self.analysis_cancelled()
        ):
            raise AnalysisCancelled()
        export_result = export_fabrication_package(self.board, self.output_gerber_dir())

        # First produce the strict fabrication-file view.  UUID mapping is a
        # separate enrichment layer so the Gerber source truth remains
        # inspectable in the combined contract.
        export_issues, export_summary, strict_results, export_profile = analyze_export_with_results(
            export_result,
            rules,
            include_profile=True,
            progress_callback=strict_progress_callback,
            is_cancelled=self.analysis_cancelled,
            board_thickness_mm=self.backend.board_thickness_mm(),
            chinese=self.language == "简体中文",
        )
        self.logger.debug("export_dfm_analysis profile=%s", export_profile)
        strict_results = self.complete_compat_results(strict_results)
        strict_summary = self.gerber_summary_map(
            export_summary,
            strict_results,
            export_issues,
        )
        strict_contract = build_analysis_contract(
            GERBER_STRICT,
            strict_results,
            export_issues,
            strict_summary,
            categories=COMPAT_CATEGORIES,
            profile=export_profile,
            metadata={"input_kind": "gerber_excellon"},
        )

        enriched_results = copy.deepcopy(strict_results)
        # Candidate indexes walk every native track/pad/zone on the board.
        # Reuse one mapper for the whole Gerber pass instead of rebuilding
        # those indexes independently for every result category.
        result_mapper = GerberResultObjectMapper(self.board, self.backend)
        enrichment_items = tuple(enriched_results.items())
        enrichment_total = len(enrichment_items) + 1
        self.analysis_checkpoint(
            0,
            enrichment_total,
            "Enriching Gerber results",
            enrichment_progress_callback,
        )
        for enrichment_index, (category, result) in enumerate(
            enrichment_items,
            start=1,
        ):
            enrichment_heartbeat = lambda current=enrichment_index: self.analysis_checkpoint(
                current,
                enrichment_total,
                "Enriching Gerber results",
                enrichment_progress_callback,
            )
            enrichment_heartbeat()
            self.map_gerber_native_result_rows(
                result,
                heartbeat=enrichment_heartbeat,
                category=category,
                mapper=result_mapper,
            )
        enriched_summary = self.gerber_summary_map(
            export_summary,
            enriched_results,
            export_issues,
        )
        enriched_contract = build_analysis_contract(
            GERBER_ENRICHED,
            enriched_results,
            export_issues,
            enriched_summary,
            categories=COMPAT_CATEGORIES,
            profile=export_profile,
            metadata={
                "derived_from": GERBER_STRICT,
                "enrichment": "kicad_uuid_mapping",
                "measurement_values_preserved": True,
            },
        )
        self.analysis_checkpoint(
            enrichment_total,
            enrichment_total,
            "Finalizing results",
            enrichment_progress_callback,
        )
        input_paths = tuple(export_result.files or ())
        if export_result.zip_path:
            input_paths += (export_result.zip_path,)
        return AnalysisStageResult(
            mode=GERBER_ENRICHED,
            analysis_result=enriched_results,
            kicad_result=copy.deepcopy(enriched_results),
            issues=tuple(export_issues or ()),
            summary=enriched_summary,
            profile=export_profile,
            contract=enriched_contract,
            input_paths=input_paths,
            export_summary=export_summary,
            source_views={
                GERBER_STRICT: {
                    "analysis_result": strict_results,
                    "kicad_result": copy.deepcopy(strict_results),
                    "issues": tuple(export_issues or ()),
                    "summary": strict_summary,
                    "profile": copy.deepcopy(export_profile),
                    "contract": strict_contract,
                    "input_paths": input_paths,
                }
            },
        )

    def scaled_analysis_progress(self, start, end):
        return self.scaled_progress_callback(
            self.update_analysis_progress,
            start,
            end,
        )

    @staticmethod
    def scaled_progress_callback(progress_callback, start, end):
        start = int(start)
        span = max(0, int(end) - start)

        def callback(completed, total, item):
            total = max(1, int(total))
            ratio = min(1.0, max(0.0, float(completed) / float(total)))
            return progress_callback(
                start + int(round(span * ratio)),
                100,
                item,
            )

        return callback

    def apply_gerber_native_results(self, native_results):
        self.analysis_result = {category: "" for category in COMPAT_CATEGORIES}
        self.kicad_result = {
            "Smallest Trace Width": "",
            "Pad size": "",
            "RingHole": "",
        }
        result_mapper = GerberResultObjectMapper(self.board, self.backend)
        for category, result in normalize_smd_spacing_results(native_results).items():
            self.map_gerber_native_result_rows(
                result,
                category=category,
                mapper=result_mapper,
            )
            self.analysis_result[category] = result
            if category in self.kicad_result:
                self.kicad_result[category] = result

    def map_gerber_native_result_rows(
        self,
        result,
        heartbeat=None,
        category=None,
        mapper=None,
    ):
        if not isinstance(result, dict):
            return
        category = category or self._gerber_result_category(result)
        mapper = mapper or GerberResultObjectMapper(self.board, self.backend)
        net_tie_groups_by_pad = self._gerber_net_tie_groups_by_pad_id()
        row_count = 0
        suppressed_rows = []
        for check in result.get("check") or ():
            if not isinstance(check, dict):
                continue
            visible_rows = []
            for row in check.get("result") or ():
                if not isinstance(row, dict):
                    continue
                if row.get("source") not in ("gerber", "drill"):
                    visible_rows.append(row)
                    continue
                row_count += 1
                if heartbeat is not None and row_count % 256 == 0:
                    heartbeat()
                value = row.get("value")
                message = row.get("message")
                geometry_basis = row.get("geometry_basis")
                ambiguous_local_net_tie_contact = (
                    self._ambiguous_mapped_local_net_tie_contact(
                        row,
                        mapper,
                        net_tie_groups_by_pad,
                    )
                )
                mapping = mapper.apply_mapping(row)
                if category == "Copper-to-Board Edge" and mapping.status not in (
                    "matched",
                    "already_mapped",
                ):
                    mapping = self._map_aggregated_through_hole_row(
                        row,
                        mapper,
                        mapping,
                    )
                # Mapping supplies a native location, not a new measurement.
                # Keep fabrication geometry/value provenance intact and record
                # hit testing independently.
                row["value"] = value
                row["message"] = message
                if geometry_basis is not None:
                    row["geometry_basis"] = geometry_basis
                raw = row.setdefault("raw", {})
                raw.setdefault(
                    "measurement_basis",
                    "excellon" if row.get("source") == "drill" else "gerber",
                )
                mapping_info = raw.get("uuid_mapping") or {}
                related_mapping = mapping_info.get("related") or {}
                if mapping.status in ("matched", "already_mapped") or related_mapping.get(
                    "status"
                ) in ("matched", "already_mapped"):
                    raw["location_basis"] = "kicad_hit_test"
                if (
                    ambiguous_local_net_tie_contact
                    or self._is_mapped_local_net_tie_contact(
                        row,
                        mapping,
                        net_tie_groups_by_pad,
                    )
                ):
                    raw["suppressed_reason"] = "local_net_tie_contact"
                    suppressed_rows.append(row)
                    continue
                visible_rows.append(row)
            check["result"] = visible_rows
        physically_aggregated = False
        if category == "Copper-to-Board Edge":
            visible_rows = self._gerber_visible_result_rows(result)
            self._propagate_board_edge_through_hole_mappings(visible_rows)
            physical_rows = aggregate_physical_native_results(
                category,
                visible_rows,
            )
            physically_aggregated = len(physical_rows) != len(visible_rows)
            result["check"] = grouped_native_results(physical_rows)
        if suppressed_rows or physically_aggregated:
            result["check"] = [
                check
                for check in result.get("check") or ()
                if isinstance(check, dict) and check.get("result")
            ]
            self._recompute_enriched_result_after_suppression(
                result,
                suppressed_rows,
            )
        counts = {}
        for row in self._gerber_visible_result_rows(result) + list(suppressed_rows):
            mapping = (row.get("raw") or {}).get("uuid_mapping") or {}
            status = str(mapping.get("status") or "")
            if status:
                counts[status] = counts.get(status, 0) + 1
        if counts:
            self.logger.debug("gerber_uuid_mapping counts=%s", counts)

    @staticmethod
    def _gerber_visible_result_rows(result):
        return [
            row
            for check in result.get("check") or ()
            if isinstance(check, dict)
            for row in check.get("result") or ()
            if isinstance(row, dict)
        ]

    @staticmethod
    def _gerber_result_category(result):
        for row in DfmMainframe._gerber_visible_result_rows(result):
            rule_key = str(row.get("rule_key") or "").lower()
            if rule_key.startswith("coppertoboardedge:") or row.get("item") in (
                "Copper-to-Board Edge",
                "SMD-to-Board Edge",
                "Trace-to-Board Edge",
            ):
                return "Copper-to-Board Edge"
        return ""

    def _propagate_board_edge_through_hole_mappings(self, rows):
        """Reuse an authoritative outer-layer UUID for identical inner copper.

        KiCad X2 attributes identify component pads on the outer Gerbers, while
        otherwise identical inner-layer apertures may omit those attributes.
        Correlation is limited to exported through-hole evidence with an exact
        geometry/net signature, and only a signature resolving to one UUID is
        propagated.  This handles custom slotted pads whose copper bbox centre
        is not the drill axis without guessing from that centre.
        """
        ids_by_signature = {}
        for row in rows:
            signature = self._board_edge_through_hole_signature(row)
            mapping = (row.get("raw") or {}).get("uuid_mapping") or {}
            if signature is None or mapping.get("status") not in (
                "matched",
                "already_mapped",
            ):
                continue
            item_id = str(mapping.get("id") or row.get("id") or "")
            if item_id:
                ids_by_signature.setdefault(signature, set()).add(item_id)

        for row in rows:
            signature = self._board_edge_through_hole_signature(row)
            if signature is None:
                continue
            mapping = (row.get("raw") or {}).get("uuid_mapping") or {}
            if mapping.get("status") in ("matched", "already_mapped"):
                continue
            candidates = ids_by_signature.get(signature) or ()
            if len(candidates) != 1:
                continue
            item_id = next(iter(candidates))
            row["id"] = item_id
            row["confidence"] = max(float(row.get("confidence") or 0.0), 0.99)
            raw = row.setdefault("raw", {})
            raw["uuid_mapping"] = {
                "status": "matched",
                "confidence": 0.99,
                "reason": "cross_layer_export_identity",
                "id": item_id,
            }
            raw["location_basis"] = "kicad_hit_test"

    @staticmethod
    def _map_aggregated_through_hole_row(row, mapper, current_mapping):
        """Map a folded PTH through any authoritative per-layer observation."""
        raw = row.get("raw") if isinstance(row.get("raw"), dict) else {}
        primary = raw.get("primary") if isinstance(raw.get("primary"), dict) else {}
        measurements = raw.get("per_layer_measurements")
        if not primary.get("through_hole") or not isinstance(
            measurements, (tuple, list)
        ):
            return current_mapping

        matches = {}
        for measurement in measurements:
            if not isinstance(measurement, dict):
                continue
            endpoint = measurement.get("primary")
            if not isinstance(endpoint, dict):
                continue
            probe = dict(row)
            probe["raw"] = endpoint
            probe["id"] = endpoint.get("file") or measurement.get("id") or row.get("id")
            probe["layer"] = endpoint.get("layer") or measurement.get("layer") or row.get(
                "layer"
            )
            if endpoint.get("item_type"):
                probe["item_type"] = endpoint["item_type"]
            candidate = mapper.map_row(probe)
            if candidate.status in ("matched", "already_mapped") and candidate.item_id:
                matches[candidate.item_id] = candidate
        if len(matches) != 1:
            return current_mapping

        item_id, candidate = next(iter(matches.items()))
        row["id"] = item_id
        row["confidence"] = max(
            float(row.get("confidence") or 0.0),
            float(candidate.confidence or 0.0),
        )
        raw["uuid_mapping"] = {
            "status": "matched",
            "confidence": candidate.confidence,
            "reason": "per_layer_export_identity",
            "id": item_id,
        }
        return candidate

    @staticmethod
    def _board_edge_through_hole_signature(row):
        raw = row.get("raw") if isinstance(row.get("raw"), dict) else {}
        primary = raw.get("primary") if isinstance(raw.get("primary"), dict) else {}
        if not primary.get("through_hole"):
            return None

        def rounded(value):
            if isinstance(value, dict):
                return tuple(
                    (key, rounded(item)) for key, item in sorted(value.items())
                )
            if isinstance(value, (tuple, list)):
                return tuple(rounded(item) for item in value)
            if isinstance(value, float):
                return round(value, 6)
            return value

        drill_identity = primary.get("drill_identity")
        if isinstance(drill_identity, dict):
            physical_geometry = ("drill", rounded(drill_identity))
        else:
            physical_geometry = (
                str(primary.get("kind") or "").lower(),
                rounded(primary.get("point")),
                rounded(primary.get("segment")),
                rounded(primary.get("bbox")),
                round(float(primary.get("width") or 0.0), 6),
            )
        return (
            str(primary.get("net") or ""),
            str(primary.get("aperture_function") or "").lower(),
            physical_geometry,
        )

    def _gerber_net_tie_groups_by_pad_id(self):
        reader = getattr(self.backend, "net_tie_pad_groups", None)
        if reader is None:
            return {}
        try:
            raw_groups = tuple(reader() or ())
        except Exception:
            return {}
        groups_by_pad = {}
        for raw_group in raw_groups:
            members = {}
            for raw_member in raw_group or ():
                if not isinstance(raw_member, (tuple, list)) or len(raw_member) < 2:
                    continue
                pad_id = str(raw_member[0] or "")
                net_name = str(raw_member[1] or "")
                if pad_id and net_name:
                    members[pad_id] = net_name
            net_names = frozenset(members.values())
            if len(net_names) < 2:
                continue
            group = (members, net_names)
            for pad_id in members:
                groups_by_pad.setdefault(pad_id, []).append(group)
        return {
            pad_id: tuple(groups)
            for pad_id, groups in groups_by_pad.items()
        }

    def _is_mapped_local_net_tie_contact(
        self,
        row,
        primary_mapping,
        groups_by_pad,
    ):
        """Suppress only a proven local relation at a declared net tie."""
        if not groups_by_pad or not self._is_gerber_copper_spacing_row(row):
            return False
        raw = row.get("raw") if isinstance(row.get("raw"), dict) else {}
        mapping_info = raw.get("uuid_mapping")
        mapping_info = mapping_info if isinstance(mapping_info, dict) else {}
        related_mapping = mapping_info.get("related")
        related_mapping = related_mapping if isinstance(related_mapping, dict) else {}
        primary_status = str(
            getattr(primary_mapping, "status", "") or mapping_info.get("status") or ""
        )
        related_status = str(related_mapping.get("status") or "")
        authoritative = {"matched", "already_mapped"}
        if primary_status not in authoritative or related_status not in authoritative:
            return False

        left_id = str(row.get("id") or mapping_info.get("id") or "")
        right_id = str(row.get("related_id") or related_mapping.get("id") or "")
        if not left_id or not right_id or left_id == right_id:
            return False
        resolver = getattr(self.backend, "resolve_item", None)
        if resolver is None:
            return False
        try:
            left = resolver(left_id)
            right = resolver(right_id)
        except Exception:
            return False
        if left is None or right is None:
            return False

        return self._is_local_net_tie_item_contact(
            left,
            right,
            groups_by_pad,
            left_id=left_id,
            right_id=right_id,
            allow_positive_pad_gap=self._is_smd_spacing_row(row),
        )

    def _ambiguous_mapped_local_net_tie_contact(
        self,
        row,
        mapper,
        groups_by_pad,
    ):
        """Resolve duplicated-pad mappings using the Gerber measurement.

        Net-tie footprints commonly repeat one pad number for several native
        pad shapes.  X2 identity then yields an ambiguous cross-product.  The
        fabricated clearance is independent evidence: only native pairs whose
        clearance best matches that Gerber value may decide suppression.  A
        tied best match containing any non-NetTie pair remains visible.
        """
        if not groups_by_pad or not self._is_gerber_copper_spacing_row(row):
            return False
        pair_reader = getattr(mapper, "map_pair", None)
        candidate_reader = getattr(mapper, "map_pair_candidates", None)
        clearance_reader = getattr(self.backend, "item_clearance_nm", None)
        if pair_reader is None or candidate_reader is None or clearance_reader is None:
            return False
        try:
            primary, related = pair_reader(row)
        except Exception:
            return False
        if related is None:
            return False
        statuses = {
            str(getattr(primary, "status", "") or ""),
            str(getattr(related, "status", "") or ""),
        }
        if "ambiguous" not in statuses or not statuses.issubset(
            {"matched", "ambiguous"}
        ):
            return False
        try:
            target_nm = float(row.get("value")) * 1000000.0
            left_candidates, right_candidates = candidate_reader(row)
        except (TypeError, ValueError, AttributeError):
            return False

        evaluated = []
        seen_pairs = set()
        for left_mapping in left_candidates or ():
            left = getattr(left_mapping, "item", None)
            if left is None:
                continue
            for right_mapping in right_candidates or ():
                right = getattr(right_mapping, "item", None)
                if right is None:
                    continue
                pair_key = tuple(sorted((id(left), id(right))))
                if pair_key in seen_pairs:
                    continue
                seen_pairs.add(pair_key)
                try:
                    clearance_nm = float(
                        clearance_reader(left, right, 5000000)
                    )
                except (TypeError, ValueError, AttributeError):
                    continue
                evaluated.append(
                    (
                        abs(clearance_nm - target_nm),
                        self._is_local_net_tie_item_contact(
                            left,
                            right,
                            groups_by_pad,
                            clearance_nm=clearance_nm,
                            allow_positive_pad_gap=self._is_smd_spacing_row(row),
                        ),
                    )
                )
        if not evaluated:
            return False
        best_delta = min(delta for delta, _is_contact in evaluated)
        closest = [
            is_contact
            for delta, is_contact in evaluated
            if delta
            <= best_delta + GERBER_PAIR_MEASUREMENT_TIE_TOLERANCE_NM
        ]
        suppress = bool(closest) and all(closest)
        row.setdefault("raw", {})["net_tie_candidate_resolution"] = {
            "candidate_pair_count": len(evaluated),
            "closest_pair_count": len(closest),
            "target_clearance_nm": target_nm,
            "best_delta_nm": best_delta,
            "all_closest_local_contacts": suppress,
        }
        return suppress

    def _is_local_net_tie_item_contact(
        self,
        left,
        right,
        groups_by_pad,
        left_id="",
        right_id="",
        clearance_nm=None,
        allow_positive_pad_gap=False,
    ):
        net_reader = getattr(self.backend, "item_net_name", None)
        clearance_reader = getattr(self.backend, "item_clearance_nm", None)
        if net_reader is None or clearance_reader is None:
            return False
        item_id_reader = getattr(self.backend, "item_id", None)
        try:
            if item_id_reader is not None:
                left_id = str(item_id_reader(left) or left_id or "")
                right_id = str(item_id_reader(right) or right_id or "")
            else:
                left_id = str(getattr(left, "item_id", "") or left_id or "")
                right_id = str(getattr(right, "item_id", "") or right_id or "")
            left_net = str(net_reader(left) or "")
            right_net = str(net_reader(right) or "")
        except Exception:
            return False
        # Same-net copper and unnamed nets are not NetTie proof.  They remain
        # visible so a declaration elsewhere cannot hide a board-wide issue.
        if not left_id or not right_id or not left_net or not right_net:
            return False
        if left_id == right_id or left_net == right_net:
            return False
        is_pad = getattr(self.backend, "is_pad", lambda _item: False)
        is_track = getattr(self.backend, "is_track", lambda _item: False)
        try:
            left_pad = bool(is_pad(left))
            right_pad = bool(is_pad(right))
            left_track = bool(is_track(left))
            right_track = bool(is_track(right))
        except Exception:
            return False
        if left_pad and right_pad:
            local_relation = self._pads_share_local_net_tie_structure(
                left,
                right,
                left_id,
                right_id,
                left_net,
                right_net,
                groups_by_pad,
            )
            if allow_positive_pad_gap and local_relation:
                return True
            if not local_relation:
                return False

        try:
            if clearance_nm is None:
                clearance_nm = clearance_reader(
                    left,
                    right,
                    GERBER_NET_TIE_CONTACT_TOLERANCE_NM,
                )
            clearance_nm = float(clearance_nm)
        except Exception:
            return False
        if clearance_nm < 0 or clearance_nm > GERBER_NET_TIE_CONTACT_TOLERANCE_NM:
            return False
        if left_pad and right_pad:
            return True
        if left_pad and right_track:
            pad_id, pad_net, track_net = left_id, left_net, right_net
        elif right_pad and left_track:
            pad_id, pad_net, track_net = right_id, right_net, left_net
        else:
            return False
        return any(
            members.get(pad_id) == pad_net and track_net in net_names
            for members, net_names in groups_by_pad.get(pad_id, ())
        )

    def _pads_share_local_net_tie_structure(
        self,
        left,
        right,
        left_id,
        right_id,
        left_net,
        right_net,
        groups_by_pad,
    ):
        if declared_net_tie_pad_pair(
            groups_by_pad,
            left_id,
            left_net,
            right_id,
            right_net,
        ):
            return True
        return self._pad_attached_to_net_tie_member(
            right,
            right_id,
            right_net,
            groups_by_pad,
            left_id,
            left_net,
        ) or self._pad_attached_to_net_tie_member(
            left,
            left_id,
            left_net,
            groups_by_pad,
            right_id,
            right_net,
        )

    def _pad_attached_to_net_tie_member(
        self,
        pad,
        pad_id,
        pad_net,
        groups_by_pad,
        reported_member_id,
        reported_member_net,
    ):
        resolver = getattr(self.backend, "resolve_item", None)
        clearance_reader = getattr(self.backend, "item_clearance_nm", None)
        if resolver is None or clearance_reader is None:
            return False
        for member_id, member_net in local_net_tie_attachment_candidates(
            groups_by_pad,
            reported_member_id,
            reported_member_net,
            pad_id,
            pad_net,
        ):
            try:
                member = resolver(member_id)
            except Exception:
                continue
            if member is None:
                continue
            layer_reader = getattr(self.backend, "pad_copper_layer_ids", None)
            if layer_reader is not None:
                try:
                    pad_layers = set(layer_reader(pad) or ())
                    member_layers = set(layer_reader(member) or ())
                except Exception:
                    pad_layers = member_layers = set()
                if pad_layers and member_layers and pad_layers.isdisjoint(member_layers):
                    continue
            local_clearance_nm = self._item_local_clearance_nm(member)
            attachment_limit_nm = max(1.0, float(local_clearance_nm or 0.0))
            try:
                clearance_nm = clearance_reader(
                    pad,
                    member,
                    int(attachment_limit_nm) + 1,
                )
            except Exception:
                continue
            if clearance_nm is not None and float(clearance_nm) <= attachment_limit_nm:
                return True
        return False

    def _item_local_clearance_nm(self, item):
        reader = getattr(self.backend, "item_local_clearance_nm", None)
        if reader is not None:
            try:
                value = reader(item)
            except Exception:
                value = None
            if value is not None:
                try:
                    return max(0.0, float(value))
                except (TypeError, ValueError):
                    pass
        method = getattr(item, "GetLocalClearance", None)
        if method is None:
            return None
        try:
            return max(0.0, float(method()))
        except (TypeError, ValueError, RuntimeError):
            return None

    @staticmethod
    def _is_smd_spacing_row(row):
        rule_identity = str(row.get("rule_key") or "").lower()
        return bool(
            rule_identity.startswith("smdspacing:")
            or row.get("item") == "SMD Pad Spacing"
        )

    @staticmethod
    def _is_gerber_copper_spacing_row(row):
        rule_identity = str(row.get("rule_key") or "").lower()
        return bool(
            rule_identity.startswith("smallesttracespacing:")
            or rule_identity.startswith("smdspacing:")
            or row.get("item") in GERBER_COPPER_SPACING_ITEMS
        )

    def _recompute_enriched_result_after_suppression(self, result, suppressed_rows):
        visible_rows = [
            row
            for check in result.get("check") or ()
            if isinstance(check, dict)
            for row in check.get("result") or ()
            if isinstance(row, dict)
        ]
        all_rows = visible_rows + list(suppressed_rows)
        values = [self._gerber_result_float(row.get("value")) for row in visible_rows]
        values = [value for value in values if value is not None]
        result["display"] = round(min(values), 6) if values else "正常"
        if "display_inch" in result:
            result["display_inch"] = ""
        result["color"] = aggregate_color(row.get("color") for row in visible_rows)
        result["violation_count"] = sum(
            self._gerber_result_is_violation(row) for row in visible_rows
        )
        result["displayed_count"] = len(visible_rows)
        result["visible_count"] = len(visible_rows)
        result["suppressed_count"] = self._integer_metric(
            result.get("suppressed_count")
        ) + len(suppressed_rows)
        reasons = dict(result.get("suppression_reasons") or {})
        reasons["local_net_tie_contact"] = self._integer_metric(
            reasons.get("local_net_tie_contact")
        ) + len(suppressed_rows)
        result["suppression_reasons"] = reasons
        result["item_summaries"] = self._recomputed_gerber_item_summaries(
            result.get("item_summaries"),
            all_rows,
            visible_rows,
            suppressed_rows,
        )

    def _recomputed_gerber_item_summaries(
        self,
        existing_summaries,
        all_rows,
        visible_rows,
        suppressed_rows,
    ):
        existing_summaries = (
            existing_summaries if isinstance(existing_summaries, dict) else {}
        )
        rebuilt = {}
        covered = set()
        for summary_key, source_summary in existing_summaries.items():
            if not isinstance(source_summary, dict):
                continue
            matching_all = [
                row
                for row in all_rows
                if self._gerber_summary_matches_row(summary_key, source_summary, row)
            ]
            matching_visible = [
                row
                for row in visible_rows
                if self._gerber_summary_matches_row(summary_key, source_summary, row)
            ]
            matching_suppressed = [
                row
                for row in suppressed_rows
                if self._gerber_summary_matches_row(summary_key, source_summary, row)
            ]
            covered.update(id(row) for row in matching_all)
            rebuilt[summary_key] = self._updated_gerber_item_summary(
                source_summary,
                matching_all,
                matching_visible,
                matching_suppressed,
            )

        ungrouped = {}
        for row in all_rows:
            if id(row) in covered:
                continue
            identity = str(row.get("rule_key") or row.get("item") or "")
            if identity:
                ungrouped.setdefault(identity, []).append(row)
        visible_ids = {id(row) for row in visible_rows}
        suppressed_ids = {id(row) for row in suppressed_rows}
        for identity, rows in ungrouped.items():
            source_summary = {
                "rule_key": str(rows[0].get("rule_key") or ""),
                "item": str(rows[0].get("item") or ""),
                "checked_count": len(rows),
                "available_count": len(rows),
            }
            rebuilt[identity] = self._updated_gerber_item_summary(
                source_summary,
                rows,
                [row for row in rows if id(row) in visible_ids],
                [row for row in rows if id(row) in suppressed_ids],
            )
        return rebuilt

    def _updated_gerber_item_summary(
        self,
        source_summary,
        all_rows,
        visible_rows,
        suppressed_rows,
    ):
        summary = dict(source_summary)
        values = [self._gerber_result_float(row.get("value")) for row in visible_rows]
        values = [value for value in values if value is not None]
        summary["display"] = min(values) if values else None
        summary["color"] = aggregate_color(row.get("color") for row in visible_rows)
        summary["violation_count"] = sum(
            self._gerber_result_is_violation(row) for row in visible_rows
        )
        summary["displayed_count"] = len(visible_rows)
        summary["visible_count"] = len(visible_rows)
        summary["checked_count"] = self._integer_metric(
            source_summary.get("checked_count"),
            len(all_rows),
        )
        summary["available_count"] = self._integer_metric(
            source_summary.get("available_count"),
            summary["checked_count"],
        )
        summary["suppressed_count"] = self._integer_metric(
            source_summary.get("suppressed_count")
        ) + len(suppressed_rows)
        summary["execution_status"] = "completed"
        return summary

    @staticmethod
    def _gerber_summary_matches_row(summary_key, summary, row):
        stable_key = str(summary.get("rule_key") or "")
        row_key = str(row.get("rule_key") or "")
        if stable_key and row_key:
            return stable_key == row_key
        item = str(summary.get("item") or summary_key or "")
        return bool(item and item == str(row.get("item") or ""))

    @staticmethod
    def _gerber_result_is_violation(row):
        return bool(
            str(row.get("color") or "").lower() in ("red", "gold")
            or str(row.get("severity") or "").lower()
            in ("fatal", "error", "warning")
        )

    @staticmethod
    def _gerber_result_float(value):
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _integer_metric(value, fallback=0):
        try:
            return int(value)
        except (TypeError, ValueError):
            return int(fallback or 0)

    def gerber_summary_map(self, export_summary, native_results, issues):
        summary = dict(export_summary or {})
        for category, result in (native_results or {}).items():
            if not isinstance(result, dict):
                continue
            summary[category] = DfmSummary(
                category=category,
                display=str(result.get("display", "")),
                display_inch=str(result.get("display_inch", "")),
                color=result.get("color", ""),
                issues=tuple(issue for issue in issues if issue.category == category),
            )
        return summary

    def output_gerber_dir(self):
        return gerber_output_dir(self.path, include_metadata=True)

    def set_run_enabled(self, enabled):
        self.dfm_maindialog.dfm_run_button.Enable(enabled)
        if hasattr(self.dfm_maindialog, "gerber_dfm_button"):
            self.dfm_maindialog.gerber_dfm_button.Enable(enabled)

    def configure_analysis_entry_buttons(self):
        """Expose explicit native-fast and complete-combined entry points."""
        self.dfm_maindialog.dfm_run_button.SetLabel(_("Quick DFM Check"))
        if hasattr(self.dfm_maindialog, "gerber_dfm_button"):
            self.dfm_maindialog.gerber_dfm_button.SetLabel(
                _("Full DFM Check")
            )
            self.dfm_maindialog.gerber_dfm_button.Show()
        self.dfm_maindialog.Layout()

    def begin_analysis_progress(self):
        self.cancel_saved_analysis_load()
        self._analysis_cancel_requested = False
        self.set_run_enabled(False)
        self.dfm_maindialog.begin_check_progress()

    def end_analysis_progress(self):
        self.dfm_maindialog.end_check_progress()
        self.set_run_enabled(True)

    def analysis_cancelled(self):
        return bool(getattr(self, "_analysis_cancel_requested", False))

    def analysis_checkpoint(
        self,
        completed,
        total,
        item="Finalizing results",
        progress_callback=None,
    ):
        """Yield to the UI and reject a Stop request before committing work."""
        report_progress(
            progress_callback or self.update_analysis_progress,
            self.analysis_cancelled,
            completed,
            total,
            item,
        )

    def on_stop_analysis(self, event):
        self._analysis_cancel_requested = True
        self.dfm_maindialog.show_stopping()
        event.Skip()

    def update_analysis_progress(self, completed, total, item):
        item_labels = {
            "Preparing board data": _("Preparing board data"),
            "Checking output directory": _("Checking output directory"),
            "Checking exported files": _("Checking exported files"),
            "Checking ZIP package": _("Checking ZIP package"),
            "Scanning exported geometry": _("Scanning exported geometry"),
            "Checking copper spacing": _("Checking copper spacing"),
            "Checking drill-to-copper clearance": _("Checking drill-to-copper clearance"),
            "Checking signal integrity": _("Checking signal integrity"),
            "Checking solder mask": _("Checking solder mask"),
            "Finalizing results": _("Finalizing results"),
            "Saving board": _("Saving board"),
            "Exporting fabrication files": _("Exporting fabrication files"),
            "Enriching Gerber results": _("Enriching Gerber results"),
            "Preparing Gerber analysis": _("Preparing Gerber analysis"),
            "Merging analysis results": _("Merging analysis results"),
            "Saving analysis cache": _("Saving analysis cache"),
        }
        current_item = item_labels.get(item, rule_label(item, self.control, _))
        message = _("Checking: {item} ({current}/{total})").format(
            item=current_item,
            current=min(int(completed) + 1, int(total)),
            total=total,
        )
        self.dfm_maindialog.update_check_progress(completed, total, message)
        return not self._analysis_cancel_requested

    def update_export_analysis_progress(self, completed, total, item):
        return self.update_analysis_progress(completed + 2, total + 2, item)

    # 添加分析项
    def add_all_item(self, use_existing_kicad_result=False):
        if self.analysis_result == {}:
            return
        if not use_existing_kicad_result:
            result = OfflineDfmAnalysis(
                self.board,
                self.control,
                rules=self.current_rules(),
            ).analyze()
            self.analysis_result = result.analysis_result
            self.kicad_result = result.kicad_result
            self.dfm_analysis.dfm_issues = result.issues
            self.dfm_analysis.dfm_summary = result.summary

        # 板子层数 # 板子尺寸
        self.json_analysis_map[_("Layer Count")]["display"] = str(
            self.board.GetCopperLayerCount()
        )
        self.json_analysis_map[_("Layer Count")]["color"] = ""
        self.json_analysis_map[_("Dimensions")]["display"] = str(
            format_board_dimensions(self.pcb_setting.get_layer_size())
        )
        self.json_analysis_map[_("Dimensions")]["color"] = ""

        # 电气信号
        self.apply_signal_integrity_summary()

        # 最小线宽
        if self.kicad_result["Smallest Trace Width"] == "":
            self.json_analysis_map[_("Smallest Trace Width")][
                "display"
            ] = self.item_result
            self.json_analysis_map[_("Smallest Trace Width")]["color"] = ""
        else:
            minimum_value = self.kicad_result["Smallest Trace Width"]["display"]
            self.apply_local_summary("Smallest Trace Width", minimum_value)

        # 最小间距
        if self.analysis_result["Smallest Trace Spacing"] == "":
            self.json_analysis_map[_("Smallest Trace Spacing")][
                "display"
            ] = self.item_result
            self.json_analysis_map[_("Smallest Trace Spacing")]["color"] = ""
        else:
            data = self.get_data(
                self.analysis_result["Smallest Trace Spacing"]["display"]
            )
            if data is not None:
                self.json_analysis_map[_("Smallest Trace Spacing")][
                    "display"
                ] = self.unit_conversion(data)
                self.json_analysis_map[_("Smallest Trace Spacing")][
                    "color"
                ] = self.analysis_result["Smallest Trace Spacing"]["color"]

            else:
                self.json_analysis_map[_("Smallest Trace Spacing")][
                    "display"
                ] = self.item_result
                self.json_analysis_map[_("Smallest Trace Spacing")]["color"] = ""

        # SMD焊盘间距
        if self.analysis_result["SMD Spacing"] == "":
            self.json_analysis_map[_("SMD Spacing")]["display"] = self.item_result
            self.json_analysis_map[_("SMD Spacing")]["color"] = ""
        else:
            data = self.get_data(self.analysis_result["SMD Spacing"]["display"])
            if data is not None:
                self.json_analysis_map[_("SMD Spacing")]["display"] = self.unit_conversion(data)
                self.json_analysis_map[_("SMD Spacing")]["color"] = self.analysis_result[
                    "SMD Spacing"
                ]["color"]
            else:
                self.json_analysis_map[_("SMD Spacing")]["display"] = self.item_result
                self.json_analysis_map[_("SMD Spacing")]["color"] = ""

        # 最小焊盘
        if self.kicad_result["Pad size"] == "":
            self.json_analysis_map[_("Pad size")]["display"] = self.item_result
            self.json_analysis_map[_("Pad size")]["color"] = ""
        else:
            minimum_value = self.kicad_result["Pad size"]["display"]
            self.apply_local_summary("Pad size", minimum_value)

        # 孔大小
        if self.analysis_result["Hole Size"] == "":
            self.json_analysis_map[_("Hole Size")]["display"] = self.item_result
            self.json_analysis_map[_("Hole Size")]["color"] = ""
        else:
            data = self.get_data(self.analysis_result["Hole Size"]["display"])
            if data is not None:
                self.json_analysis_map[_("Hole Size")][
                    "display"
                ] = self.unit_conversion(data)
                self.json_analysis_map[_("Hole Size")][
                    "color"
                ] = self.analysis_result["Hole Size"]["color"]

            else:
                self.json_analysis_map[_("Hole Size")]["display"] = self.item_result
                self.json_analysis_map[_("Hole Size")]["color"] = ""

        # 孔环大小
        if self.kicad_result["RingHole"] == "":
            self.json_analysis_map[_("RingHole")]["display"] = self.item_result
            self.json_analysis_map[_("RingHole")]["color"] = ""
        else:
            minimum_value = self.kicad_result["RingHole"]["display"]
            self.apply_local_summary("RingHole", minimum_value)

        # 孔到孔
        if self.analysis_result["Drill Hole Spacing"] == "":
            self.json_analysis_map[_("Drill Hole Spacing")][
                "display"
            ] = self.item_result
            self.json_analysis_map[_("Drill Hole Spacing")]["color"] = ""
        else:
            data = self.get_data(self.analysis_result["Drill Hole Spacing"]["display"])
            if data is not None:
                self.json_analysis_map[_("Drill Hole Spacing")][
                    "display"
                ] = self.unit_conversion(data)
                self.json_analysis_map[_("Drill Hole Spacing")][
                    "color"
                ] = self.analysis_result["Drill Hole Spacing"]["color"]
            else:
                self.json_analysis_map[_("Drill Hole Spacing")][
                    "display"
                ] = self.item_result
                self.json_analysis_map[_("Drill Hole Spacing")]["color"] = ""

        # 孔到线
        if self.analysis_result["Drill to Copper"] == "":
            self.json_analysis_map[_("Drill to Copper")]["display"] = self.item_result
            self.json_analysis_map[_("Drill to Copper")]["color"] = ""
        else:
            data = self.get_data(self.analysis_result["Drill to Copper"]["display"])
            if data is not None:
                self.json_analysis_map[_("Drill to Copper")][
                    "display"
                ] = self.unit_conversion(data)
                self.json_analysis_map[_("Drill to Copper")][
                    "color"
                ] = self.analysis_result["Drill to Copper"]["color"]
            else:
                self.json_analysis_map[_("Drill to Copper")][
                    "display"
                ] = self.item_result
                self.json_analysis_map[_("Drill to Copper")]["color"] = ""

        # 板边距离
        if self.analysis_result["Copper-to-Board Edge"] == "":
            self.json_analysis_map[_("Copper-to-Board Edge")][
                "display"
            ] = self.item_result
            self.json_analysis_map[_("Copper-to-Board Edge")]["color"] = ""
        else:
            data = self.get_data(
                self.analysis_result["Copper-to-Board Edge"]["display"]
            )
            if data is not None:
                self.json_analysis_map[_("Copper-to-Board Edge")][
                    "display"
                ] = self.unit_conversion(data)
                self.json_analysis_map[_("Copper-to-Board Edge")][
                    "color"
                ] = self.analysis_result["Copper-to-Board Edge"]["color"]
            else:
                self.json_analysis_map[_("Copper-to-Board Edge")][
                    "display"
                ] = self.item_result
                self.json_analysis_map[_("Copper-to-Board Edge")]["color"] = ""

        # 特殊孔
        if self.analysis_result["Hole-to-Board Edge"] == "":
            self.json_analysis_map[_("Hole-to-Board Edge")][
                "display"
            ] = self.item_result
            self.json_analysis_map[_("Hole-to-Board Edge")]["color"] = ""
        else:
            data = self.get_data(
                self.analysis_result["Hole-to-Board Edge"]["display"]
            )
            if data is not None:
                self.json_analysis_map[_("Hole-to-Board Edge")][
                    "display"
                ] = self.unit_conversion(data)
                self.json_analysis_map[_("Hole-to-Board Edge")][
                    "color"
                ] = self.analysis_result["Hole-to-Board Edge"]["color"]
            else:
                self.json_analysis_map[_("Hole-to-Board Edge")][
                    "display"
                ] = self.item_result
                self.json_analysis_map[_("Hole-to-Board Edge")]["color"] = ""

        if self.analysis_result["Special Drill Holes"] == "":
            self.json_analysis_map[_("Special Drill Holes")][
                "display"
            ] = self.item_result
            self.json_analysis_map[_("Special Drill Holes")]["color"] = ""
        else:
            data = self.get_data(self.analysis_result["Special Drill Holes"]["display"])
            if data is not None:
                self.json_analysis_map[_("Special Drill Holes")][
                    "display"
                ] = self.unit_conversion(data)
                self.json_analysis_map[_("Special Drill Holes")][
                    "color"
                ] = self.analysis_result["Special Drill Holes"]["color"]
            else:
                self.json_analysis_map[_("Special Drill Holes")][
                    "display"
                ] = self.item_result
                self.json_analysis_map[_("Special Drill Holes")]["color"] = ""

        # 孔上焊盘
        if self.analysis_result["Holes on SMD Pads"] == "":
            self.json_analysis_map[_("Holes on SMD Pads")]["display"] = self.item_result
            self.json_analysis_map[_("Holes on SMD Pads")]["color"] = ""
        else:
            data = self.analysis_result["Holes on SMD Pads"]["display"]
            if data is not None:
                self.json_analysis_map[_("Holes on SMD Pads")]["display"] = str(data)
                self.json_analysis_map[_("Holes on SMD Pads")][
                    "color"
                ] = self.analysis_result["Holes on SMD Pads"]["color"]
            else:
                self.json_analysis_map[_("Holes on SMD Pads")][
                    "display"
                ] = self.item_result
                self.json_analysis_map[_("Holes on SMD Pads")]["color"] = ""

            # 阻焊开窗
        if self.analysis_result["Missing SMask Openings"] == "":
            self.json_analysis_map[_("Missing SMask Openings")][
                "display"
            ] = self.item_result
            self.json_analysis_map[_("Missing SMask Openings")]["color"] = ""
        else:
            data = self.get_data(
                self.analysis_result["Missing SMask Openings"]["display"]
            )
            if data is not None:
                self.json_analysis_map[_("Missing SMask Openings")]["display"] = str(
                    data
                )
                self.json_analysis_map[_("Missing SMask Openings")][
                    "color"
                ] = self.analysis_result["Missing SMask Openings"]["color"]

            else:
                self.json_analysis_map[_("Missing SMask Openings")][
                    "display"
                ] = self.item_result
                self.json_analysis_map[_("Missing SMask Openings")]["color"] = ""

        # 阻焊分析
        solder_mask_result = self.analysis_result.get("Solder Mask Analysis", "")
        if not isinstance(solder_mask_result, dict):
            self.json_analysis_map[_("Solder Mask Analysis")]["display"] = self.item_result
            self.json_analysis_map[_("Solder Mask Analysis")]["color"] = ""
        else:
            data = self.get_data(solder_mask_result.get("display"))
            self.json_analysis_map[_("Solder Mask Analysis")]["display"] = (
                self.unit_conversion(data) if data is not None else self.item_result
            )
            self.json_analysis_map[_("Solder Mask Analysis")]["color"] = (
                solder_mask_result.get("color", "") if data is not None else ""
            )

        # 孔密度
        if self.analysis_result["Drill Hole Density"] == "":
            self.json_analysis_map[_("Drill Hole Density")][
                "display"
            ] = self.item_result
            self.json_analysis_map[_("Drill Hole Density")]["color"] = ""
        else:
            self.json_analysis_map[_("Drill Hole Density")]["display"] = str(
                self.analysis_result["Drill Hole Density"]["display"]
            )
            self.json_analysis_map[_("Drill Hole Density")]["color"] = ""

        # 沉金面积
        if self.analysis_result["Surface Finish Area"] == "":
            self.json_analysis_map[_("Surface Finish Area")][
                "display"
            ] = self.item_result
            self.json_analysis_map[_("Surface Finish Area")]["color"] = ""
        else:
            self.json_analysis_map[_("Surface Finish Area")]["display"] = str(
                self.analysis_result["Surface Finish Area"]["display"]
            )
            self.json_analysis_map[_("Surface Finish Area")]["color"] = ""

        # 飞针点数
        if self.analysis_result["Test Point Count"] == "":
            self.json_analysis_map[_("Test Point Count")]["display"] = self.item_result
            self.json_analysis_map[_("Test Point Count")]["color"] = ""
        else:
            self.json_analysis_map[_("Test Point Count")]["display"] = str(
                self.analysis_result["Test Point Count"]["display"]
            )
            self.json_analysis_map[_("Test Point Count")]["color"] = ""

        self.dfm_maindialog.init_data_view(self.json_analysis_map)

    # 只获取数据
    def get_data(self, data_string):
        if data_string is None:
            return None
        pattern = re.compile(r"(\d+(\.\d+)?)")
        ret = pattern.search(str(data_string))
        if ret is not None:
            result = ret.group()
            return float(result)

    def apply_local_summary(self, category, value):
        if value == "正常":
            self.json_analysis_map[_(category)]["display"] = self.item_result
            self.json_analysis_map[_(category)]["color"] = ""
            return
        self.json_analysis_map[_(category)]["display"] = self.unit_conversion(value)
        self.json_analysis_map[_(category)]["color"] = self.kicad_result[category]["color"]

    # 单位转换
    def unit_conversion(self, str_value):
        if self.unit == 0:
            iu_value = mm_to_inches(str_value)
            return str(round(iu_value, 3)) + "inch"
        elif self.unit == 5:
            mils_value = mm_to_mils(str_value)
            return str(round(mils_value, 3)) + "mils"
        else:
            return str(round(float(str_value), 3)) + "mm"

    def show_rule_manager(self, event):
        profile_id = self.current_rule_profile_id()
        for window in wx.GetTopLevelWindows():
            if window.GetTitle() == _("Rule View"):
                window.Destroy()
        RuleManagerView(self, profile_id, rules_for_profile(profile_id), self.unit, self.control).Show()

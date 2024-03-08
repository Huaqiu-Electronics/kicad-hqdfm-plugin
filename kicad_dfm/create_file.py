import os
from pathlib import Path
import logging
import wx
from pcbnew import (
    EXCELLON_WRITER,
    PCB_PLOT_PARAMS,
    PLOT_CONTROLLER,
    PLOT_FORMAT_GERBER,
    ZONE_FILLER,
    B_Cu,
    B_Mask,
    B_Paste,
    B_SilkS,
    Cmts_User,
    Edge_Cuts,
    F_Cu,
    In1_Cu,
    In2_Cu,
    In3_Cu,
    In4_Cu,
    In5_Cu,
    In6_Cu,
    F_Mask,
    F_Paste,
    F_SilkS,
    GetBoard,
    ToMM,
    DRILL_MARKS_NO_DRILL_SHAPE,
)


class CreateFile:
    def __init__(self, _board):
        self.board = _board
        self.logger = logging.getLogger(__name__)

    def export_gerber(self, gerber_dir, layer_count=None):
        """Generating Gerber files"""
        pctl = PLOT_CONTROLLER(self.board)
        popt = pctl.GetPlotOptions()
        popt.SetOutputDirectory(gerber_dir)

        popt.SetFormat(1)

        popt.SetPlotValue(True)
        popt.SetPlotReference(True)
        popt.SetPlotInvisibleText(False)

        popt.SetSketchPadsOnFabLayers(False)

        popt.SetUseGerberProtelExtensions(False)

        popt.SetCreateGerberJobFile(False)

        popt.SetSubtractMaskFromSilk(True)

        popt.SetPlotViaOnMaskLayer(False)

        popt.SetUseAuxOrigin(True)

        popt.SetPlotViaOnMaskLayer(True)

        popt.SetUseGerberX2format(True)

        popt.SetIncludeGerberNetlistInfo(True)

        popt.SetDisableGerberMacros(False)

        popt.SetDrillMarksType(DRILL_MARKS_NO_DRILL_SHAPE)

        popt.SetPlotFrameRef(False)

        # delete all existing files in the output directory first
        for f in os.listdir(gerber_dir):
            os.remove(os.path.join(gerber_dir, f))

        # if no layer_count is given, get the layer count from the board
        if not layer_count:
            layer_count = self.board.GetCopperLayerCount()

        if layer_count == 1:
            plot_plan = [
                ("CuTop", F_Cu, "Top layer"),
                ("SilkTop", F_SilkS, "Silk top"),
                ("MaskTop", F_Mask, "Mask top"),
                ("PasteTop", F_Paste, "Paste top"),
                ("EdgeCuts", Edge_Cuts, "Edges"),
                ("VScore", Cmts_User, "V score cut"),
            ]
        elif layer_count == 2:
            plot_plan = [
                ("CuTop", F_Cu, "Top layer"),
                ("SilkTop", F_SilkS, "Silk top"),
                ("MaskTop", F_Mask, "Mask top"),
                ("PasteTop", F_Paste, "Paste top"),
                ("CuBottom", B_Cu, "Bottom layer"),
                ("SilkBottom", B_SilkS, "Silk top"),
                ("MaskBottom", B_Mask, "Mask bottom"),
                ("PasteBottom", B_Paste, "Paste bottom"),
                ("EdgeCuts", Edge_Cuts, "Edges"),
                ("VScore", Cmts_User, "V score cut"),
            ]
        elif layer_count == 4:
            plot_plan = [
                ("CuTop", F_Cu, "Top layer"),
                ("SilkTop", F_SilkS, "Silk top"),
                ("MaskTop", F_Mask, "Mask top"),
                ("PasteTop", F_Paste, "Paste top"),
                ("CuIn1", In1_Cu, "Inner layer 1"),
                ("CuIn2", In2_Cu, "Inner layer 2"),
                ("CuBottom", B_Cu, "Bottom layer"),
                ("SilkBottom", B_SilkS, "Silk top"),
                ("MaskBottom", B_Mask, "Mask bottom"),
                ("PasteBottom", B_Paste, "Paste bottom"),
                ("EdgeCuts", Edge_Cuts, "Edges"),
                ("VScore", Cmts_User, "V score cut"),
            ]
        elif layer_count == 6:
            plot_plan = [
                ("CuTop", F_Cu, "Top layer"),
                ("SilkTop", F_SilkS, "Silk top"),
                ("MaskTop", F_Mask, "Mask top"),
                ("PasteTop", F_Paste, "Paste top"),
                ("CuIn1", In1_Cu, "Inner layer 1"),
                ("CuIn2", In2_Cu, "Inner layer 2"),
                ("CuIn3", In3_Cu, "Inner layer 3"),
                ("CuIn4", In4_Cu, "Inner layer 4"),
                ("CuBottom", B_Cu, "Bottom layer"),
                ("SilkBottom", B_SilkS, "Silk top"),
                ("MaskBottom", B_Mask, "Mask bottom"),
                ("PasteBottom", B_Paste, "Paste bottom"),
                ("EdgeCuts", Edge_Cuts, "Edges"),
                ("VScore", Cmts_User, "V score cut"),
            ]

        for layer_info in plot_plan:
            if layer_info[1] <= B_Cu:
                popt.SetSkipPlotNPTH_Pads(True)
            else:
                popt.SetSkipPlotNPTH_Pads(False)
            pctl.SetLayer(layer_info[1])
            pctl.OpenPlotfile(layer_info[0], PLOT_FORMAT_GERBER, layer_info[2])
            if pctl.PlotLayer() is False:
                self.logger.error(f"Error plotting {layer_info[2]}")
            self.logger.info(f"Successfully plotted {layer_info[2]}")
        pctl.ClosePlot()
        # 导出gerber

    def export_drl(self, gerber_dir):
        """Generate Drill files."""
        drl_writer = EXCELLON_WRITER(self.board)
        mirror = False
        minimal_header = False
        offset = self.board.GetDesignSettings().GetAuxOrigin()
        merge_NPTH = False
        drl_writer.SetOptions(mirror, minimal_header, offset, merge_NPTH)
        drl_writer.SetFormat(False)
        gen_drl = True
        gen_map = True
        drl_writer.CreateDrillandMapFilesSet(gerber_dir, gen_drl, gen_map)
        self.logger.info("Finished generating Drill files")

from kicad_dfm.child_frame.picture_catalog import PICTURE_BY_ITEM


DIAGRAM_SPECS = {
    "acute_angle": ("A", "diagram.acute_angle", (0.36, 0.40), (0.28, 0.18), "center"),
    "breakage_line": ("1", "diagram.unconnected_trace", (0.72, 0.52), (0.72, 0.18), "center"),
    "dangling_tracks": ("1", "diagram.dangling_trace", (0.733, 0.528), (0.72, 0.18), "center"),
    "isolated_copper": ("1", "diagram.floating_copper", (0.19, 0.52), (0.19, 0.18), "center"),
    "invalid_via": ("1", "diagram.unconnected_via", (0.20, 0.53), (0.32, 0.18), "center"),
    "line_width": ("W", "diagram.trace_width", (0.45, 0.50), (0.45, 0.18), "center"),
    "line2line": ("S", "diagram.trace_spacing", (0.46, 0.49), (0.46, 0.18), "center"),
    "pad2line": ("S", "diagram.trace_to_pad_spacing", (0.43, 0.60), (0.39, 0.22), "center"),
    "pad2pad": ("S", "diagram.pad_spacing", (0.22, 0.64), (0.22, 0.22), "center"),
    "bga": ("A", "diagram.bga_pad", (0.55, 0.54), (0.50, 0.18), "center"),
    "pad_spacing_base": ("S", "diagram.smd_pad_spacing", (0.39, 0.56), (0.46, 0.20), "center"),
    "min_diameter": ("D", "diagram.min_hole_diameter", (0.70, 0.54), (0.70, 0.20), "center"),
    "min_thick_diameter": ("A", "diagram.aspect_ratio", (0.42, 0.52), (0.42, 0.18), "center"),
    "min_slot": ("W", "diagram.min_slot_width", (0.72, 0.54), (0.72, 0.20), "center"),
    "max_diameter": ("D", "diagram.max_hole_diameter", (0.74, 0.52), (0.74, 0.18), "center"),
    "max_slot": ("W", "diagram.max_slot_width", (0.25, 0.52), (0.25, 0.18), "center"),
    "max_slot_length": ("L", "diagram.max_slot_length", (0.50, 0.76), (0.50, 0.22), "center"),
    "slot_length_width": ("L/W", "diagram.slot_aspect_ratio", (0.76, 0.50), (0.76, 0.18), "center"),
    "max_diameter_blind_buried": ("D", "diagram.blind_buried_diameter", (0.65, 0.51), (0.65, 0.18), "center"),
    "via_ring": ("A", "diagram.annular_ring", (0.33, 0.54), (0.33, 0.18), "center"),
    "line2pth_outer": ("S", "diagram.outer_hole_to_trace", (0.61, 0.38), (0.50, 0.18), "center"),
    "line2pth_inner": ("S", "diagram.inner_hole_to_trace", (0.61, 0.38), (0.50, 0.18), "center"),
    "npth2copper": ("S", "diagram.npth_to_copper", (0.50, 0.55), (0.56, 0.20), "center"),
    "smd2edge": ("S", "diagram.smd_to_board_edge", (0.30, 0.72), (0.22, 0.22), "center"),
    "copper2edge": ("S", "diagram.copper_to_board_edge", (0.92, 0.52), (0.78, 0.18), "center"),
    "pth2edge": ("S", "diagram.pth_to_board_edge", (0.24, 0.62), (0.34, 0.18), "center"),
    "via2edge": ("S", "diagram.via_to_board_edge", (0.52, 0.74), (0.52, 0.18), "center"),
    "npth2edge": ("S", "diagram.npth_to_board_edge", (0.24, 0.62), (0.34, 0.18), "center"),
    "hole_spuared": ("1", "diagram.square_rect_hole", (0.23, 0.46), (0.18, 0.18), "center"),
    "hole_half": ("1", "diagram.castellated_hole", (0.18, 0.49), (0.18, 0.18), "center"),
    "pth_insmd": ("1", "diagram.pth_on_smd_pad", (0.82, 0.56), (0.72, 0.18), "center"),
    "via_insmd": ("1", "diagram.via_on_smd_pad", (0.24, 0.58), (0.24, 0.18), "center"),
    "npth_insmd": ("1", "diagram.npth_on_smd_pad", (0.82, 0.56), (0.72, 0.18), "center"),
    "soldmask_lack": ("1", "diagram.missing_smask_opening", (0.49, 0.70), (0.49, 0.20), "center"),
    "solder_mask_bridge": ("S", "diagram.solder_mask_bridge", (0.50, 0.55), (0.50, 0.18), "center"),
    "solder_mask_covers_trace": ("S", "diagram.solder_mask_covers_trace", (0.55, 0.50), (0.55, 0.18), "center"),
    "solder_mask_multiple_nets": ("1", "diagram.solder_mask_multiple_nets", (0.50, 0.52), (0.50, 0.18), "center"),
    "via_same net": ("S", "diagram.same_net_via_spacing", (0.39, 0.54), (0.39, 0.18), "center"),
    "via_difference_net": ("S", "diagram.different_net_via_spacing", (0.45, 0.55), (0.45, 0.18), "center"),
    "pth_difference_net": ("S", "diagram.different_net_pth_spacing", (0.52, 0.47), (0.52, 0.18), "center"),
    "blind2blind": ("S", "diagram.blind_buried_via_spacing", (0.67, 0.59), (0.67, 0.20), "center"),
}

DIAGRAM_LABELS_EN = {
    "diagram.acute_angle": "Acute angle trace",
    "diagram.unconnected_trace": "Unconnected trace",
    "diagram.dangling_trace": "Dangling trace endpoint",
    "diagram.floating_copper": "Floating copper",
    "diagram.unconnected_via": "Unconnected via",
    "diagram.trace_width": "Trace width",
    "diagram.trace_spacing": "Trace spacing",
    "diagram.trace_to_pad_spacing": "Trace to pad spacing",
    "diagram.pad_spacing": "Pad spacing",
    "diagram.bga_pad": "BGA pad",
    "diagram.smd_pad_spacing": "SMD pad spacing",
    "diagram.min_hole_diameter": "Minimum hole diameter",
    "diagram.aspect_ratio": "Aspect ratio",
    "diagram.min_slot_width": "Minimum slot width",
    "diagram.max_hole_diameter": "Maximum hole diameter",
    "diagram.max_slot_width": "Maximum slot width",
    "diagram.max_slot_length": "Maximum slot length",
    "diagram.slot_aspect_ratio": "Slot aspect ratio",
    "diagram.blind_buried_diameter": "Blind/buried via diameter",
    "diagram.annular_ring": "Annular ring",
    "diagram.outer_hole_to_trace": "Outer hole to trace",
    "diagram.inner_hole_to_trace": "Inner hole to trace",
    "diagram.npth_to_copper": "NPTH to copper",
    "diagram.smd_to_board_edge": "SMD to board edge",
    "diagram.copper_to_board_edge": "Copper to board edge",
    "diagram.pth_to_board_edge": "PTH to board edge",
    "diagram.via_to_board_edge": "Via to board edge",
    "diagram.npth_to_board_edge": "NPTH to board edge",
    "diagram.square_rect_hole": "Square/rectangular hole",
    "diagram.castellated_hole": "Castellated hole",
    "diagram.pth_on_smd_pad": "PTH on SMD pad",
    "diagram.via_on_smd_pad": "Via on SMD pad",
    "diagram.npth_on_smd_pad": "NPTH on SMD pad",
    "diagram.missing_smask_opening": "Missing solder mask opening",
    "diagram.solder_mask_bridge": "Solder mask bridge",
    "diagram.solder_mask_covers_trace": "Solder mask opening near another-net trace",
    "diagram.solder_mask_multiple_nets": "One opening exposes multiple nets",
    "diagram.same_net_via_spacing": "Same net via spacing",
    "diagram.different_net_via_spacing": "Different net via spacing",
    "diagram.different_net_pth_spacing": "Different net PTH spacing",
    "diagram.blind_buried_via_spacing": "Blind/buried via spacing",
}


def _entry_for(picture_name, aliases):
    symbol, key, anchor, label, align = DIAGRAM_SPECS[picture_name]
    return {
        "image": picture_name + ".png",
        "aliases": aliases,
        "labels": (
            {
                "key": key,
                "symbol": symbol,
                "anchor": anchor,
                "label": label,
                "align": align,
            },
        ),
        "legend": (key,),
    }


DIAGRAM_BY_ITEM = {
    picture_name: _entry_for(picture_name, aliases)
    for picture_name, aliases in PICTURE_BY_ITEM.items()
}

import ast
import os
import subprocess
import sys
import struct


DOMAIN = "kicad_hqdfm_plugin"


def main():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    locale_root = os.path.join(root, "kicad_dfm", "language", "locale")
    status = 0
    for current, _, files in os.walk(locale_root):
        po_name = DOMAIN + ".po"
        if po_name in files:
            po_path = os.path.join(current, po_name)
            mo_path = os.path.join(current, DOMAIN + ".mo")
            try:
                status = subprocess.call(["msgfmt", "-o", mo_path, po_path]) or status
            except FileNotFoundError:
                compile_po(po_path, mo_path)
    return status


def compile_po(po_path, mo_path):
    messages = parse_po(po_path)
    keys = sorted(messages)
    ids = b"\x00".join(key.encode("utf-8") for key in keys) + b"\x00"
    strs = b"\x00".join(messages[key].encode("utf-8") for key in keys) + b"\x00"
    count = len(keys)
    keystart = 7 * 4 + count * 16
    valuestart = keystart + len(ids)
    offsets = []
    key_offset = keystart
    value_offset = valuestart
    for key in keys:
        key_bytes = key.encode("utf-8")
        value_bytes = messages[key].encode("utf-8")
        offsets.append((len(key_bytes), key_offset, len(value_bytes), value_offset))
        key_offset += len(key_bytes) + 1
        value_offset += len(value_bytes) + 1

    with open(mo_path, "wb") as fp:
        fp.write(struct.pack("Iiiiiii", 0x950412DE, 0, count, 7 * 4, 7 * 4 + count * 8, 0, 0))
        for length, offset, _, _ in offsets:
            fp.write(struct.pack("ii", length, offset))
        for _, _, length, offset in offsets:
            fp.write(struct.pack("ii", length, offset))
        fp.write(ids)
        fp.write(strs)


def parse_po(po_path):
    messages = {}
    msgid = None
    msgstr = None
    active = None
    fuzzy = False
    with open(po_path, encoding="utf-8") as fp:
        for raw_line in fp:
            line = raw_line.strip()
            if line.startswith("#,") and "fuzzy" in line:
                fuzzy = True
            elif line.startswith("msgid "):
                if msgid is not None and msgstr is not None and not fuzzy:
                    messages[msgid] = msgstr
                msgid = decode_po_string(line[6:])
                msgstr = None
                active = "msgid"
                fuzzy = False
            elif line.startswith("msgstr "):
                msgstr = decode_po_string(line[7:])
                active = "msgstr"
            elif line.startswith('"'):
                if active == "msgid" and msgid is not None:
                    msgid += decode_po_string(line)
                elif active == "msgstr" and msgstr is not None:
                    msgstr += decode_po_string(line)
        if msgid is not None and msgstr is not None and not fuzzy:
            messages[msgid] = msgstr
    return messages


def decode_po_string(value):
    return ast.literal_eval(value.strip())


if __name__ == "__main__":
    sys.exit(main())

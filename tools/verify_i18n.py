import ast
import os
import sys


def main():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    po_path = os.path.join(
        root,
        "kicad_dfm",
        "language",
        "locale",
        "zh_CN",
        "LC_MESSAGES",
        "kicad_hqdfm_plugin.po",
    )
    translations = parse_po(po_path)
    missing = []
    for message in sorted(source_messages(os.path.join(root, "kicad_dfm"))):
        if not message or message.startswith(" "):
            continue
        translated = translations.get(message, "")
        if translated == "":
            missing.append(message)
    if missing:
        for message in missing:
            print("missing zh_CN translation: {0}".format(message), file=sys.stderr)
        return 1
    print("i18n-ok")
    return 0


def source_messages(root):
    messages = set()
    for current, _, files in os.walk(root):
        for filename in files:
            if not filename.endswith(".py"):
                continue
            path = os.path.join(current, filename)
            with open(path, encoding="utf-8", errors="ignore") as fp:
                tree = ast.parse(fp.read(), filename=path)
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                if not isinstance(node.func, ast.Name) or node.func.id != "_":
                    continue
                if node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                    messages.add(node.args[0].value)
    return messages


def parse_po(po_path):
    messages = {}
    msgid = None
    msgstr = None
    active = None
    with open(po_path, encoding="utf-8") as fp:
        for raw_line in fp:
            line = raw_line.strip()
            if line.startswith("msgid "):
                if msgid is not None and msgstr is not None:
                    messages[msgid] = msgstr
                msgid = decode_po_string(line[6:])
                msgstr = None
                active = "msgid"
            elif line.startswith("msgstr "):
                msgstr = decode_po_string(line[7:])
                active = "msgstr"
            elif line.startswith('"'):
                if active == "msgid" and msgid is not None:
                    msgid += decode_po_string(line)
                elif active == "msgstr" and msgstr is not None:
                    msgstr += decode_po_string(line)
        if msgid is not None and msgstr is not None:
            messages[msgid] = msgstr
    return messages


def decode_po_string(value):
    return ast.literal_eval(value.strip())


if __name__ == "__main__":
    raise SystemExit(main())

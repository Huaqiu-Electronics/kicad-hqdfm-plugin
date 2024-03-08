import json

mapping = {}
with open("kicad_amf_plugin.po", encoding="utf-8", errors="ignore") as f:
    pair = []
    for line in f.readlines():
        if line.startswith("msgstr"):
            pair.append((line.removeprefix("msgstr").strip()).replace('"', ""))
        elif line.startswith("msgid"):
            pair.append(line.removeprefix("msgid").strip().replace('"', ""))
        if len(pair) == 2:
            mapping[pair[0]] = pair[1]
            pair = []


with open("mapping.json", "w", encoding="utf-8") as f:
    (json.dump(mapping, f, ensure_ascii=False))
    # f.write(str(mapping))

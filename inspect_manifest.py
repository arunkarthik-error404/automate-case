import json

with open("demo-ui/reports-manifest.json", "r", encoding="utf-8") as f:
    manifest = json.load(f)

print("--- MANIFEST KEYS ---")
for key in manifest.keys():
    if "janathan" in key.lower() or "janardhan" in key.lower():
        print("Key:", key)
        for item in manifest[key]:
            print("  -", item["name"], "->", item["relativePath"])

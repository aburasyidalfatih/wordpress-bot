import json
print(json.loads('{"a": "b\nc"}', strict=False))

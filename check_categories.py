import json
try:
    with open('categories.json', 'r', encoding='utf-8') as f:
        data = json.load(f)
    print("Categories lacking description:")
    for c in data:
        if not c.get('description'):
            print(f"- {c['name']} (Posts: {c['count']})")
    print("\nCategories with description:")
    for c in data:
        if c.get('description'):
            print(f"- {c['name']} (Posts: {c['count']})")
except Exception as e:
    print(f"Error: {e}")

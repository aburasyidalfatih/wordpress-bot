import requests

def test():
    r = requests.get("https://kelasmaster.id/wp-json/wp/v2/media?per_page=50", timeout=30)
    for media in r.json():
        print(f"ID: {media['id']} | Date: {media['date']} | MIME: {media['mime_type']} | Link: {media['source_url']}")

if __name__ == "__main__":
    test()

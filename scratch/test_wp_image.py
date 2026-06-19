import requests
from PIL import Image
import io
import os

def test():
    url = 'https://kelasmaster.id/wp-content/uploads/2026/06/7-Langkah-Buat-SK-Unit-Usaha-Sekolah-Cuan-Legal-d-scaled.webp'
    print(f"Downloading from {url}...")
    r = requests.get(url, timeout=30)
    print("Download status:", r.status_code)
    print("Download bytes size:", len(r.content))
    
    img = Image.open(io.BytesIO(r.content))
    print("Image mode:", img.mode, "size:", img.size)
    colors = img.getcolors(maxcolors=100)
    if colors:
        print("Number of unique colors (max 100):", len(colors))
        print("Unique colors:", colors)
    else:
        print("More than 100 unique colors (actual image)")

if __name__ == "__main__":
    test()

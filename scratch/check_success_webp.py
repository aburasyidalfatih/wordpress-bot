import requests
from PIL import Image
import io

def test():
    url = 'https://kelasmaster.id/wp-content/uploads/2026/06/Biaya-Sekolah-Mahal-7-Taktik-Pertahankan-Kualitas-scaled.webp'
    print(f"Downloading from {url}...")
    r = requests.get(url, timeout=30)
    print("Download status:", r.status_code)
    print("Download bytes size:", len(r.content))
    
    img = Image.open(io.BytesIO(r.content))
    print("Image mode:", img.mode, "size:", img.size)

if __name__ == "__main__":
    test()

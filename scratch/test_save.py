import os
from google import genai
from google.genai import types
from PIL import Image
import io

def test():
    from core_extensions import db
    with db.get_session() as session:
        from database import Config
        cfg = session.query(Config).first()
        api_key = cfg.gemini_api_key
        
    client = genai.Client(api_key=api_key)
    prompt = "Create a professional featured image about school business unit, modern landscape 16:9"
    
    print("Calling generate_content...")
    response = client.models.generate_content(
        model="gemini-3.1-flash-image",
        contents=prompt,
        config=types.GenerateContentConfig(
            response_modalities=["IMAGE"],
            image_config=types.ImageConfig(
                aspect_ratio="16:9",
            )
        ),
    )
    
    for i, part in enumerate(response.parts or []):
        if part.inline_data is not None:
            image_bytes = part.inline_data.data
            
            # Save raw bytes
            with open("raw_gemini.png", "wb") as f:
                f.write(image_bytes)
            print("Saved raw_gemini.png, size:", os.path.getsize("raw_gemini.png"))
            
            # Open with PIL
            img = Image.open(io.BytesIO(image_bytes))
            print("PIL Image mode:", img.mode, "size:", img.size)
            
            # Save as WEBP using PIL
            output = io.BytesIO()
            img.save(output, format='WEBP', quality=85, method=6)
            webp_bytes = output.getvalue()
            with open("pil_converted.webp", "wb") as f:
                f.write(webp_bytes)
            print("Saved pil_converted.webp, size:", os.path.getsize("pil_converted.webp"))
            
            # Let's check pixel values of the PIL image!
            # Get pixel at center
            w, h = img.size
            pixels = list(img.getdata())
            # Print a few pixels from the center
            center_idx = (h // 2) * w + (w // 2)
            print("Center pixels:", pixels[center_idx:center_idx+5])
            
            # Let's count how many distinct pixel values there are
            unique_pixels = set(pixels)
            print("Number of unique RGB pixel values:", len(unique_pixels))

if __name__ == "__main__":
    test()

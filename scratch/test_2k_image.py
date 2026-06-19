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
    
    print("Calling generate_content with image_size='2K'...")
    response = client.models.generate_content(
        model="gemini-3.1-flash-image",
        contents=prompt,
        config=types.GenerateContentConfig(
            response_modalities=["IMAGE"],
            image_config=types.ImageConfig(
                aspect_ratio="16:9",
                image_size="2K"
            )
        ),
    )
    
    for i, part in enumerate(response.parts or []):
        if part.inline_data is not None:
            image_bytes = part.inline_data.data
            print("Bytes size:", len(image_bytes))
            
            img = Image.open(io.BytesIO(image_bytes))
            print("PIL Image size:", img.size, "mode:", img.mode)
            
            # Check unique colors
            pixels = list(img.getdata())
            unique_pixels = set(pixels)
            print("Number of unique RGB pixel values:", len(unique_pixels))
            
            # Save the image
            with open("test_2k.webp", "wb") as f:
                output = io.BytesIO()
                img.save(output, format='WEBP', quality=85, method=6)
                f.write(output.getvalue())
            print("Saved test_2k.webp, size:", os.path.getsize("test_2k.webp"))

if __name__ == "__main__":
    test()

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
    
    topic = "Unit Usaha Sekolah"
    title = "7 Langkah Buat SK Unit Usaha Sekolah: Cuan Legal di 2026"
    
    prompt = f"""Create a professional featured image about {topic}.

Title: "{title}"

Design: Modern, landscape (16:9), professional colors, with title text and kelasmaster.id branding.
Style: Educational blog featured image."""

    print("Calling generate_content with else prompt...")
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
            
            with open("test_else_prompt.png", "wb") as f:
                f.write(image_bytes)
            print("Saved test_else_prompt.png, size:", os.path.getsize("test_else_prompt.png"))
            
            img = Image.open(io.BytesIO(image_bytes))
            print("PIL Image mode:", img.mode, "size:", img.size)
            
            # Save as WEBP using PIL
            output = io.BytesIO()
            img.save(output, format='WEBP', quality=85, method=6)
            webp_bytes = output.getvalue()
            with open("test_else_prompt.webp", "wb") as f:
                f.write(webp_bytes)
            print("Saved test_else_prompt.webp, size:", os.path.getsize("test_else_prompt.webp"))
            
            # Check unique colors
            pixels = list(img.getdata())
            unique_pixels = set(pixels)
            print("Number of unique RGB pixel values:", len(unique_pixels))

if __name__ == "__main__":
    test()

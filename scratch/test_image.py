import os
from google import genai
from google.genai import types
from PIL import Image
import io

def test():
    # Load API key from env or config
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
    
    print("Response parts:", len(response.parts) if response.parts else 0)
    for i, part in enumerate(response.parts or []):
        print(f"Part {i}: inline_data is None? {part.inline_data is None}")
        if part.inline_data is not None:
            image_bytes = part.inline_data.data
            print("Bytes size:", len(image_bytes))
            
            # Test opening with PIL directly
            img = Image.open(io.BytesIO(image_bytes))
            print("Direct PIL Image size:", img.size, "mode:", img.mode)
            
            # Check unique colors in the image
            colors = img.getcolors(maxcolors=10000)
            if colors:
                print("Number of unique colors:", len(colors))
                if len(colors) < 5:
                    print("Unique colors:", colors)
            else:
                print("More than 10,000 unique colors (likely a real image)")

if __name__ == "__main__":
    test()

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
    
    prompt = f"""Create a professional featured image for this article about {topic}.

Article Title: {title}

Design Requirements:
- Modern, clean design in landscape orientation (16:9) - perfect for blog featured image
- Professional color scheme (blues, greens, education colors)
- Include the title text: "{title}"
- Add relevant visual elements, icons, or illustrations
- "kelasmaster.id" branding subtly placed
- High quality, eye-catching design
- Suitable as blog header/featured image

Style: Modern, professional, suitable for educational blog featured image."""

    print("Calling generate_content with exact prompt...")
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
            
            with open("test_indonesian_prompt.png", "wb") as f:
                f.write(image_bytes)
            print("Saved test_indonesian_prompt.png, size:", os.path.getsize("test_indonesian_prompt.png"))
            
            img = Image.open(io.BytesIO(image_bytes))
            print("PIL Image mode:", img.mode, "size:", img.size)
            
            # Save as WEBP using PIL
            output = io.BytesIO()
            img.save(output, format='WEBP', quality=85, method=6)
            webp_bytes = output.getvalue()
            with open("test_indonesian_prompt.webp", "wb") as f:
                f.write(webp_bytes)
            print("Saved test_indonesian_prompt.webp, size:", os.path.getsize("test_indonesian_prompt.webp"))
            
            # Check unique colors
            pixels = list(img.getdata())
            unique_pixels = set(pixels)
            print("Number of unique RGB pixel values:", len(unique_pixels))

if __name__ == "__main__":
    test()

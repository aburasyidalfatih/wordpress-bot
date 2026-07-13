import sys; sys.path.append('/app')
from core_extensions import db
from models import WordPressSite

with db.get_session() as session:
    sites = session.query(WordPressSite).all()
    count = 0
    for site in sites:
        if site.article_prompt and 'FORMAT OUTPUT' in site.article_prompt and 'JSON' in site.article_prompt:
            parts = site.article_prompt.split('FORMAT OUTPUT')
            site.article_prompt = parts[0].strip() + "\n\nFORMAT OUTPUT (Gunakan XML-Tags berikut):\n<TITLE>Judul CTR tinggi dengan angka + power word + benefit (50-60 karakter)</TITLE>\n<META_DESCRIPTION>Meta description 150-160 karakter dengan CTA dan keyword</META_DESCRIPTION>\n<CONTENT>Konten HTML lengkap 2000-2500 kata</CONTENT>\n<FOCUS_KEYWORD>keyword utama artikel</FOCUS_KEYWORD>"
            count += 1
            print(f"Updated prompt for site ID {site.id}")
            
    session.commit()
    print(f'Migration completed successfully! Updated {count} sites.')

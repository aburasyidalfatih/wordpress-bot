import subprocess
import re
import sys

out = subprocess.check_output(['git', 'show', 'HEAD~1:app.py']).decode('utf-8')
article = re.search(r'default_article_prompt = """(.*?)"""', out, re.DOTALL)
image = re.search(r'default_image_prompt = """(.*?)"""', out, re.DOTALL)
with open('old_prompts.txt', 'w', encoding='utf-8') as f:
    f.write('===ARTICLE===\n')
    if article:
        f.write(article.group(1))
    f.write('\n===IMAGE===\n')
    if image:
        f.write(image.group(1))
print("Done")

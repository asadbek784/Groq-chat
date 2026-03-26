# DEPLOY QO'LLANMASI

## GitHub ga yuklash

1. github.com ga kiring → New repository → "groq-bot" nomini bering → Create

2. Kompyuterda ZIP ni chiqaring, papka ichiga kiring

3. Bu buyruqlarni bajaring:
   git init
   git add .
   git commit -m "deploy"
   git branch -M main
   git remote add origin https://github.com/SIZNING_USERNAME/groq-bot.git
   git push -u origin main

## Render.com ga deploy

1. render.com ga kiring → New → Web Service
2. "Connect a repository" → GitHub repo tanlang
3. Quyidagilarni tekshiring:
   - Build Command:  pip install -r requirements.txt
   - Start Command:  python app.py
4. Environment → Add Environment Variable:
   - TELEGRAM_TOKEN = (bot tokeningiz)
   - GROQ_API_KEY   = (groq api kalitingiz)
5. Create Web Service tugmasini bosing

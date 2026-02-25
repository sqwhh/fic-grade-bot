# Local setup (macOS/Linux)

```bash
python -m venv .venv
source .venv/bin/activate

pip install -r requirements.txt
python -m playwright install chromium

cp .env.example .env
# edit .env

python -m fic_grade_bot
# or: python bot.py
```

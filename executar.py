"""Carrega .env simples e inicia servidor local. Não instale servidor publicamente sem HTTPS."""
import os
from pathlib import Path
for line in (Path(__file__).parent/'.env').read_text(encoding='utf8').splitlines() if (Path(__file__).parent/'.env').exists() else []:
    s=line.strip()
    if not s or s.startswith('#') or '=' not in s:continue
    k,v=s.split('=',1)
    os.environ.setdefault(k.strip(),v.strip().strip('"').strip("'"))
import uvicorn
uvicorn.run('app:app',host=os.getenv('PULSO_HOST','127.0.0.1'),port=int(os.getenv('PULSO_PORT','8000')),workers=1)

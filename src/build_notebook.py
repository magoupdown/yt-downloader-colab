# Monta o notebook .ipynb a partir de backend.py + app.html
import json, os, sys, io
HERE = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = sys.argv[1] if len(sys.argv) > 1 else os.path.dirname(HERE)
os.makedirs(OUT_DIR, exist_ok=True)

backend = open(os.path.join(HERE, 'backend.py'), encoding='utf-8').read()
app_html = open(os.path.join(HERE, 'app.html'), encoding='utf-8').read()
assert '"""' not in app_html, 'app.html não pode conter aspas triplas'

INTRO_MD = r"""# ▶️ YT Downloader Pessoal

Baixe **vídeos e playlists do YouTube** em **MP4** (na resolução que quiser) ou **somente o áudio** (MP3, M4A, OPUS, FLAC, WAV ou original), com uma interface de página web, prévia antes de baixar e confirmação em cada etapa.

**Como usar (2 cliques):**

1. Rode a célula **1️⃣** — faça login na sua conta Google (obrigatório) e, se quiser, autorize o Google Drive.
2. Rode a célula **2️⃣** — o aplicativo aparece logo abaixo dela. Cole o link e siga as etapas.

> 💡 Ou use **Ambiente de execução ▸ Executar tudo** (`Ctrl+F9`).

**Vídeos privados, +18 ou só para membros:** dentro do app, abra a seção *Cookies da sua conta*, carregue o arquivo `cookies.txt` exportado do seu navegador uma única vez. Com o Drive conectado ele fica salvo em `Meu Drive/YT_Downloader/cookies.txt` e é carregado automaticamente nas próximas vezes.

> ⚠️ Uso **pessoal**. Respeite os termos do YouTube e os direitos autorais dos criadores. Nunca compartilhe seu arquivo de cookies: ele dá acesso à sua conta.

---
*Desenvolvido por **@emersonms** - 2026*
"""

SETUP_PY = r'''#@title 1️⃣ Preparar o ambiente e entrar com a conta Google  { display-mode: "form" }
#@markdown Clique no ▶ à esquerda. Uma janela do Google vai pedir autorização — isso é obrigatório para usar o app.
conectar_google_drive = True  #@param {type:"boolean"}
#@markdown *Com o Drive conectado, os cookies ficam salvos entre sessões e os downloads podem ser copiados para o Drive.*

import os, sys, shutil, subprocess, json
from IPython.display import HTML, display, clear_output

def _box(msg, kind='info'):
    cor = {'info': '#3b82f6', 'ok': '#22c55e', 'warn': '#f59e0b', 'err': '#ef4444'}[kind]
    display(HTML(f'<div style="font-family:system-ui,sans-serif;font-size:14px;padding:10px 14px;margin:6px 0;border-radius:10px;'
                 f'border-left:4px solid {cor};background:{cor}14;color:inherit">{msg}</div>'))

# ---------- 1. Login Google (obrigatório) ----------
_box('🔐 Aguardando login na conta Google… aceite a janela que abriu.')
try:
    from google.colab import auth
    auth.authenticate_user()
except Exception as e:
    raise SystemExit(f'Login cancelado ou falhou: {e}. Rode a célula novamente e conclua o login.')

USER_EMAIL = None
try:
    import google.auth, google.auth.transport.requests, requests
    _creds, _ = google.auth.default()
    _creds.refresh(google.auth.transport.requests.Request())
    USER_EMAIL = requests.get('https://www.googleapis.com/oauth2/v3/userinfo',
                              headers={'Authorization': f'Bearer {_creds.token}'}, timeout=15).json().get('email')
except Exception:
    pass
USER_EMAIL = USER_EMAIL or 'Conta Google conectada'

# ---------- 2. Google Drive (opcional) ----------
DRIVE_OK = False
if conectar_google_drive:
    try:
        from google.colab import drive
        drive.mount('/content/drive', force_remount=False)
        DRIVE_OK = os.path.isdir('/content/drive/MyDrive')
    except Exception as e:
        _box(f'Drive não conectado: {e}', 'warn')

# ---------- 3. Dependências ----------
_box('📦 Instalando/atualizando yt-dlp e o runtime JavaScript (deno)… ~30 s')
subprocess.run([sys.executable, '-m', 'pip', 'install', '-q', '-U', 'yt-dlp[default]'], check=False,
               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
if not shutil.which('deno'):
    subprocess.run('curl -fsSL https://deno.land/install.sh -o /tmp/deno_install.sh && '
                   'DENO_INSTALL=/usr/local sh /tmp/deno_install.sh < /dev/null', shell=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if not shutil.which('deno') and os.path.exists('/usr/local/bin/deno'):
        os.environ['PATH'] += ':/usr/local/bin'
import importlib, yt_dlp
importlib.reload(yt_dlp)

clear_output()
_box(f'✅ <b>Login OK</b> — {USER_EMAIL}', 'ok')
_box(('✅ <b>Google Drive conectado</b> — cookies e downloads podem ser salvos em <code>Meu Drive/YT_Downloader</code>' if DRIVE_OK
      else 'ℹ️ Google Drive <b>não conectado</b> — os cookies valerão só nesta sessão.'), 'ok' if DRIVE_OK else 'info')
_box(f'✅ yt-dlp <b>{yt_dlp.version.__version__}</b> · ffmpeg {"OK" if shutil.which("ffmpeg") else "NÃO encontrado"} · '
     f'deno {"OK" if shutil.which("deno") else "não instalado (alguns vídeos podem falhar)"}', 'ok' if shutil.which('deno') else 'warn')
_box('👉 Agora rode a célula <b>2️⃣ Abrir o aplicativo</b>.', 'info')
'''

APP_PY_HEAD = r'''#@title 2️⃣ Abrir o aplicativo  { display-mode: "form" }
#@markdown Clique no ▶. A interface aparece logo abaixo. Se o ambiente for reiniciado, rode a célula 1 e depois esta.
import os as _os
from IPython.display import HTML as _HTML, display as _display

def _erro(msg):
    _display(_HTML(f'<div style="font-family:system-ui,sans-serif;padding:14px 16px;border-radius:12px;border-left:4px solid #ef4444;'
                   f'background:#ef444414;font-size:14px">⛔ <b>{msg}</b></div>'))

_pronto = True
if 'USER_EMAIL' not in globals():
    _erro('Execute primeiro a célula 1️⃣ (login na conta Google).'); _pronto = False
else:
    try:
        import google.auth as _ga; _ga.default()
    except Exception:
        _erro('Login na conta Google necessário. Rode a célula 1️⃣ novamente.'); _pronto = False

if _pronto:
'''

CLEAN_PY = r'''#@title 3️⃣ (Opcional) Limpar arquivos baixados do servidor  { display-mode: "form" }
#@markdown Apaga apenas os arquivos temporários desta sessão do Colab. Nada é removido do seu Drive.
import shutil, os
shutil.rmtree('/content/yt_downloader/downloads', ignore_errors=True)
os.makedirs('/content/yt_downloader/downloads', exist_ok=True)
print('✅ Pasta de downloads temporários limpa.')
'''

def indent(code, n=4):
    return '\n'.join((' ' * n + l) if l.strip() else l for l in code.splitlines())

APP_PY_TAIL = r'''
if _pronto:
    try:
        _display(_HTML(APP_HTML))
    except Exception as _e:
        import traceback as _tb
        _erro('Falha ao abrir o aplicativo. Copie a mensagem abaixo e envie para suporte.')
        print(_tb.format_exc())
'''
# corpo do backend protegido: qualquer erro Python aparece na tela em vez de sumir
app_cell = (APP_PY_HEAD + '    try:\n' + indent(backend, 8) + '\n\n' + indent('APP_HTML = r"""' + app_html + '"""', 8)
            + '\n    except Exception as _e:\n        import traceback as _tb\n        _pronto = False\n'
            + '        _erro(\'Erro ao preparar o aplicativo. Copie a mensagem abaixo e envie para suporte.\')\n'
            + '        print(_tb.format_exc())\n' + APP_PY_TAIL)

def cell(kind, src, **meta):
    lines = src.splitlines(keepends=True)
    c = {'cell_type': kind, 'metadata': meta, 'source': lines}
    if kind == 'code':
        c.update({'execution_count': None, 'outputs': []})
    return c

nb = {
    'nbformat': 4, 'nbformat_minor': 0,
    'metadata': {
        'colab': {'name': 'YT_Downloader_Pessoal.ipynb', 'provenance': [], 'toc_visible': True},
        'kernelspec': {'name': 'python3', 'display_name': 'Python 3'},
        'language_info': {'name': 'python'},
    },
    'cells': [
        cell('markdown', INTRO_MD, id='intro'),
        cell('code', SETUP_PY, id='setup', cellView='form'),
        cell('code', app_cell, id='app', cellView='form'),
        cell('code', CLEAN_PY, id='clean', cellView='form'),
    ],
}
out = os.path.join(OUT_DIR, 'YT_Downloader_Pessoal.ipynb')
with open(out, 'w', encoding='utf-8') as f:
    json.dump(nb, f, ensure_ascii=False, indent=1)
# valida sintaxe Python das células de código
for c in nb['cells']:
    if c['cell_type'] == 'code':
        compile(''.join(c['source']), c['metadata']['id'], 'exec')
print('notebook gerado:', out, f'({os.path.getsize(out)//1024} KB)')

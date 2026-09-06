# ============================================================
#  YT Downloader Pessoal — backend (roda dentro do Colab)
#  Expõe funções Python para a interface web via
#  google.colab.output.register_callback / kernel.invokeFunction
# ============================================================
import os, re, json, time, uuid, shutil, threading, socket, http.server, socketserver
import urllib.parse, traceback

import yt_dlp
from IPython.display import JSON

# ---------- caminhos ----------
BASE_DIR     = '/content/yt_downloader'
DL_DIR       = os.path.join(BASE_DIR, 'downloads')
COOKIES_PATH = os.path.join(BASE_DIR, 'cookies.txt')
DRIVE_MYDRIVE = '/content/drive/MyDrive'
DRIVE_ROOT    = os.path.join(DRIVE_MYDRIVE, 'YT_Downloader')
FILE_PORT    = 8765
os.makedirs(DL_DIR, exist_ok=True)

STATE = {
    'jobs': {},
    'user': globals().get('USER_EMAIL') or 'Conta Google conectada',
    'js_runtime': None,
}

# ---------- utilidades ----------
def _drive_on():
    return os.path.isdir(DRIVE_MYDRIVE)

def _detect_js_runtime():
    if STATE['js_runtime'] is not None:
        return STATE['js_runtime']
    rt = {}
    for name in ('deno', 'node', 'bun'):
        p = shutil.which(name)
        if p:
            rt = {name: {'path': p}}
            break
    STATE['js_runtime'] = rt
    return rt

def _friendly_error(msg):
    m = (msg or '').lower()
    if 'sign in to confirm' in m or 'not a bot' in m or 'bot' in m and 'confirm' in m:
        return ('O YouTube pediu confirmação de que você não é um robô. '
                'Isso é comum em servidores do Colab. Carregue os cookies da sua conta '
                'na etapa "Cookies" e tente novamente.')
    if 'private video' in m or 'this video is private' in m:
        return 'Vídeo privado. Carregue os cookies de uma conta com acesso para baixá-lo.'
    if 'members-only' in m or 'join this channel' in m:
        return 'Conteúdo exclusivo para membros. Carregue os cookies da conta que é membro do canal.'
    if 'age' in m and ('restrict' in m or 'confirm your age' in m or 'inappropriate' in m):
        return 'Vídeo com restrição de idade. Carregue os cookies da sua conta para confirmar a idade.'
    if 'video unavailable' in m or 'video is unavailable' in m or 'not available' in m:
        return 'Vídeo indisponível (removido, bloqueado na região ou link inválido).'
    if 'unsupported url' in m or 'is not a valid url' in m:
        return 'Este link não é reconhecido. Cole um link de vídeo ou playlist do YouTube.'
    if 'requested format is not available' in m:
        return 'O formato escolhido não está disponível para este vídeo. Tente outra resolução.'
    if 'http error 429' in m or 'too many requests' in m:
        return 'O YouTube limitou as requisições (429). Aguarde alguns minutos ou use cookies.'
    if 'live' in m and ('is a live' in m or 'not yet' in m or 'premiere' in m):
        return 'Transmissões ao vivo ou estreias ainda não disponíveis não podem ser baixadas.'
    return re.sub(r'^\s*ERROR:\s*', '', msg or 'Erro desconhecido').strip()[:400]

def _base_opts():
    o = {
        'quiet': True,
        'no_warnings': True,
        'noprogress': True,
        'nocheckcertificate': True,
        'extractor_retries': 3,
        'retries': 5,
        'fragment_retries': 5,
        'socket_timeout': 30,
        'geo_bypass': True,
        'logger': _SilentLogger(),
    }
    if os.path.exists(COOKIES_PATH):
        o['cookiefile'] = COOKIES_PATH
    rt = _detect_js_runtime()
    if rt:
        o['js_runtimes'] = rt
    return o

class _SilentLogger:
    """Engole a saída do yt-dlp, mas guarda erros para reportar na interface."""
    def __init__(self): self.errors, self.warnings = [], []
    def debug(self, msg):   pass
    def info(self, msg):    pass
    def warning(self, msg): self.warnings.append(str(msg))
    def error(self, msg):   self.errors.append(str(msg))

def _fmt_size(b):
    if not b: return None
    for unit in ('B', 'KB', 'MB', 'GB'):
        if b < 1024: return f'{b:.0f} {unit}' if unit == 'B' else f'{b:.1f} {unit}'
        b /= 1024
    return f'{b:.1f} TB'

def _thumb(info):
    t = info.get('thumbnail')
    if not t and info.get('thumbnails'):
        t = info['thumbnails'][-1].get('url')
    if not t and info.get('id'):
        t = f"https://i.ytimg.com/vi/{info['id']}/hqdefault.jpg"
    return t

def _parse_url(url, mode='auto'):
    """Descobre se o link aponta para vídeo, playlist ou ambos.
    mode: 'auto' (detecta), 'video' (só o vídeo) ou 'playlist' (só a playlist/canal)."""
    u = url.strip()
    if not re.match(r'^https?://', u, re.I):
        u = 'https://' + u
    p = urllib.parse.urlparse(u)
    host = p.netloc.lower().replace('www.', '').replace('m.', '')
    qs = urllib.parse.parse_qs(p.query)
    video_id = None
    playlist_id = (qs.get('list') or [None])[0]
    if host in ('youtu.be',):
        video_id = p.path.strip('/').split('/')[0] or None
    elif 'youtube' in host:
        if p.path == '/watch':
            video_id = (qs.get('v') or [None])[0]
        else:
            m = re.match(r'^/(shorts|live|embed|v)/([A-Za-z0-9_-]{11})', p.path)
            if m: video_id = m.group(2)
        if p.path.startswith('/playlist'):
            video_id = None
    else:
        raise ValueError('unsupported url: apenas links do YouTube são aceitos.')
    is_mix = bool(playlist_id and playlist_id.startswith('RD'))
    channel_url = u if (not video_id and not playlist_id and re.match(r'^/(@[\w.-]+|channel/|c/|user/)', p.path)) else None
    if is_mix and video_id:
        # Mixes ("Minha mix", "Rádio") só existem junto do vídeo de origem
        playlist_url = f'https://www.youtube.com/watch?v={video_id}&list={playlist_id}'
    elif playlist_id:
        playlist_url = f'https://www.youtube.com/playlist?list={playlist_id}'
    elif channel_url:
        playlist_url = channel_url.rstrip('/')
        if not re.search(r'/(videos|shorts|streams|playlists)$', playlist_url):
            playlist_url += '/videos'
    else:
        playlist_url = None
    if mode == 'video':
        if not video_id:
            raise ValueError('Você escolheu "somente o vídeo", mas este link não aponta para um vídeo. Cole o link de um vídeo (watch?v=…, youtu.be/… ou /shorts/…).')
        playlist_id, playlist_url, channel_url = None, None, None
    elif mode == 'playlist':
        if not playlist_url:
            raise ValueError('Você escolheu "playlist completa", mas este link não contém uma playlist. Abra a playlist no YouTube e copie o link que tem "list=" (ou o link de um canal).')
        video_id = None
    if not video_id and not playlist_url:
        raise ValueError('unsupported url: não encontrei um vídeo ou playlist nesse link.')
    return {'url': u, 'video_id': video_id, 'playlist_id': playlist_id, 'playlist_url': playlist_url,
            'channel_url': channel_url, 'is_mix': is_mix}

# ---------- cookies ----------
def _json_cookies_to_netscape(items):
    lines = ['# Netscape HTTP Cookie File', '# gerado pelo YT Downloader Pessoal', '']
    for c in items:
        dom = c.get('domain') or '.youtube.com'
        flag = 'TRUE' if dom.startswith('.') else 'FALSE'
        path = c.get('path') or '/'
        secure = 'TRUE' if c.get('secure') else 'FALSE'
        exp = c.get('expirationDate') or c.get('expires') or c.get('expiry') or 0
        try: exp = int(float(exp))
        except Exception: exp = 0
        lines.append('\t'.join([dom, flag, path, secure, str(exp), str(c.get('name', '')), str(c.get('value', ''))]))
    return '\n'.join(lines) + '\n'

def _header_cookies_to_netscape(header):
    header = re.sub(r'^\s*cookie\s*:\s*', '', header.strip(), flags=re.I)
    items = []
    for part in header.split(';'):
        if '=' in part:
            n, v = part.strip().split('=', 1)
            items.append({'domain': '.youtube.com', 'path': '/', 'secure': True,
                          'expirationDate': int(time.time()) + 365 * 86400, 'name': n.strip(), 'value': v.strip()})
    return _json_cookies_to_netscape(items)

def _normalize_cookies(text):
    t = text.strip().lstrip('﻿')
    if not t:
        raise ValueError('Arquivo de cookies vazio.')
    if t.startswith('[') or t.startswith('{'):
        data = json.loads(t)
        if isinstance(data, dict):
            data = data.get('cookies') or data.get('items') or list(data.values())
        return _json_cookies_to_netscape(data)
    if '\t' in t:
        if not t.startswith('#'):
            t = '# Netscape HTTP Cookie File\n' + t
        return t + '\n'
    if '=' in t and ';' in t and '\n' not in t.strip():
        return _header_cookies_to_netscape(t)
    raise ValueError('Formato de cookies não reconhecido. Use um arquivo cookies.txt (formato Netscape) ou JSON exportado por extensão.')

def _cookie_summary():
    if not os.path.exists(COOKIES_PATH):
        return {'found': False}
    names, total = set(), 0
    with open(COOKIES_PATH, encoding='utf-8', errors='ignore') as f:
        for line in f:
            if line.startswith('#') or not line.strip(): continue
            parts = line.rstrip('\n').split('\t')
            if len(parts) >= 7 and 'youtube.com' in parts[0] or (len(parts) >= 7 and 'google.com' in parts[0]):
                total += 1
                names.add(parts[5])
    logged = bool(names & {'SID', '__Secure-3PSID', 'SAPISID', '__Secure-3PAPISID', 'LOGIN_INFO'})
    src = 'drive' if os.path.exists(os.path.join(DRIVE_ROOT, 'cookies.txt')) else 'sessao'
    return {'found': True, 'total': total, 'logged_in': logged, 'source': src,
            'updated': time.strftime('%d/%m/%Y %H:%M', time.localtime(os.path.getmtime(COOKIES_PATH)))}

def cb_bootstrap():
    """Estado inicial da interface. Também tenta carregar cookies salvos no Drive automaticamente."""
    try:
        if not os.path.exists(COOKIES_PATH) and _drive_on():
            saved = os.path.join(DRIVE_ROOT, 'cookies.txt')
            if os.path.exists(saved):
                shutil.copy(saved, COOKIES_PATH)
        return JSON({'ok': True, 'user': STATE['user'], 'drive': _drive_on(),
                     'cookies': _cookie_summary(), 'ytdlp': yt_dlp.version.__version__,
                     'js_runtime': next(iter(_detect_js_runtime()), None),
                     'port': FILE_PORT})
    except Exception as e:
        return JSON({'ok': False, 'error': str(e)})

def cb_save_cookies(text, persist_drive=True):
    try:
        content = _normalize_cookies(text)
        with open(COOKIES_PATH, 'w', encoding='utf-8') as f:
            f.write(content)
        saved_drive = False
        if persist_drive and _drive_on():
            os.makedirs(DRIVE_ROOT, exist_ok=True)
            shutil.copy(COOKIES_PATH, os.path.join(DRIVE_ROOT, 'cookies.txt'))
            saved_drive = True
        s = _cookie_summary()
        s['saved_drive'] = saved_drive
        return JSON({'ok': True, 'cookies': s})
    except Exception as e:
        return JSON({'ok': False, 'error': _friendly_error(str(e))})

def cb_clear_cookies(also_drive=False):
    try:
        if os.path.exists(COOKIES_PATH): os.remove(COOKIES_PATH)
        if also_drive:
            p = os.path.join(DRIVE_ROOT, 'cookies.txt')
            if os.path.exists(p): os.remove(p)
        return JSON({'ok': True, 'cookies': _cookie_summary()})
    except Exception as e:
        return JSON({'ok': False, 'error': str(e)})

def cb_test_cookies():
    """Valida os cookies pedindo ao YouTube a página da conta."""
    try:
        if not os.path.exists(COOKIES_PATH):
            return JSON({'ok': False, 'error': 'Nenhum cookie carregado.'})
        opts = _base_opts()
        opts.update({'extract_flat': True, 'playlistend': 1, 'ignoreerrors': True})
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info('https://www.youtube.com/feed/history', download=False)
        ok = bool(info and (info.get('entries') is not None))
        return JSON({'ok': True, 'valid': ok,
                     'message': 'Cookies válidos: sua conta foi reconhecida pelo YouTube.' if ok
                     else 'O YouTube não reconheceu a sessão. Exporte os cookies novamente com a conta logada.'})
    except Exception as e:
        return JSON({'ok': True, 'valid': False, 'message': _friendly_error(str(e))})

# ---------- análise / prévia ----------
def _summarize_video(info):
    vids, auds, seen_aud = {}, [], set()
    duration = info.get('duration') or 0
    for f in info.get('formats') or []:
        vcodec, acodec = f.get('vcodec') or 'none', f.get('acodec') or 'none'
        size = f.get('filesize') or f.get('filesize_approx') or 0
        if not size and duration and f.get('tbr'):
            size = int(f['tbr'] * 1000 / 8 * duration)  # estimativa por bitrate
        if vcodec != 'none' and f.get('height'):
            h = int(f['height'])
            cand = {
                'height': h, 'fps': int(round(f.get('fps') or 0)), 'ext': f.get('ext'),
                'vcodec': vcodec.split('.')[0], 'size': size, 'tbr': f.get('tbr') or 0,
                'hdr': (f.get('dynamic_range') or 'SDR') != 'SDR', 'has_audio': acodec != 'none',
            }
            cur = vids.get(h)
            if (cur is None or (cand['fps'], cand['tbr']) > (cur['fps'], cur['tbr'])):
                vids[h] = cand
        elif acodec != 'none' and vcodec == 'none':
            if 'drc' in (f.get('format_id') or '') or 'DRC' in (f.get('format_note') or ''):
                continue
            abr = int(round(f.get('abr') or f.get('tbr') or 0))
            key = (f.get('ext'), acodec.split('.')[0], abr // 8, f.get('language'))
            if key in seen_aud: continue
            seen_aud.add(key)
            auds.append({'format_id': f.get('format_id'), 'ext': f.get('ext'), 'acodec': acodec.split('.')[0],
                         'abr': abr, 'size': size, 'lang': f.get('language'), 'note': f.get('format_note')})
    best_audio = max([a['size'] for a in auds] or [0])
    resolutions = []
    for h in sorted(vids, reverse=True):
        v = vids[h]
        est = (v['size'] + (0 if v['has_audio'] else best_audio)) if v['size'] else 0
        resolutions.append({**v, 'size_label': _fmt_size(est), 'size': est,
                            'label': _res_label(h)})
    auds.sort(key=lambda a: -a['abr'])
    return {
        'id': info.get('id'), 'title': info.get('title'), 'channel': info.get('uploader') or info.get('channel'),
        'channel_url': info.get('uploader_url') or info.get('channel_url'),
        'duration': info.get('duration'), 'duration_str': info.get('duration_string'),
        'views': info.get('view_count'), 'likes': info.get('like_count'),
        'upload_date': info.get('upload_date'), 'thumbnail': _thumb(info),
        'description': (info.get('description') or '')[:600],
        'is_live': bool(info.get('is_live')), 'age_limit': info.get('age_limit') or 0,
        'availability': info.get('availability'),
        'url': info.get('webpage_url') or f"https://www.youtube.com/watch?v={info.get('id')}",
        'resolutions': resolutions,
        'audio_formats': [{**a, 'size_label': _fmt_size(a['size'])} for a in auds],
    }

def _res_label(h):
    names = {4320: '8K', 2160: '4K UHD', 1440: '2K QHD', 1080: 'Full HD', 720: 'HD', 480: 'SD', 360: 'Baixa', 240: 'Muito baixa', 144: 'Mínima'}
    return names.get(h, '')

def _summarize_entry(e, idx):
    vid = e.get('id')
    return {
        'index': idx, 'id': vid, 'title': e.get('title') or f'Vídeo {idx}',
        'url': e.get('url') if (e.get('url') or '').startswith('http') else f'https://www.youtube.com/watch?v={vid}',
        'duration': e.get('duration'), 'channel': e.get('uploader') or e.get('channel'),
        'views': e.get('view_count'),
        'thumbnail': _thumb(e) or f'https://i.ytimg.com/vi/{vid}/mqdefault.jpg',
        'unavailable': (e.get('title') in ('[Private video]', '[Deleted video]')) or e.get('availability') in ('private', 'premium_only', 'needs_auth', 'subscriber_only'),
    }

def _extract_playlist(pl_url, is_mix=False):
    opts = _base_opts(); opts.update({'extract_flat': 'in_playlist', 'ignoreerrors': True, 'playlistend': 1000})
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(pl_url, download=False)
    mix_msg = ('Este link é um Mix automático do YouTube (list=RD…). O YouTube só gera Mixes dentro do player e não permite '
               'listá-los por fora, então não dá para baixá-lo como playlist. Você pode baixar o vídeo, ou salvar os vídeos '
               'do Mix em uma playlist sua no YouTube e colar o link dela aqui.')
    if not info:
        raise RuntimeError(mix_msg if is_mix else 'O YouTube não retornou a playlist (pode exigir login/cookies ou estar indisponível).')
    if info.get('_type') != 'playlist' and not info.get('entries'):
        raise RuntimeError(mix_msg if is_mix else 'Este link não retornou uma playlist.')
    entries = [e for e in (info.get('entries') or []) if e]
    items = [_summarize_entry(e, i + 1) for i, e in enumerate(entries)]
    if not items:
        raise RuntimeError('A playlist veio vazia. Se ela for privada ou "não listada", carregue os cookies da sua conta.')
    total_dur = sum((i['duration'] or 0) for i in items)
    return {
        'id': info.get('id'), 'title': info.get('title') or ('Mix do YouTube' if is_mix else 'Playlist'),
        'channel': info.get('uploader') or info.get('channel') or ('YouTube' if is_mix else None), 'url': pl_url,
        'count': len(items), 'total_duration': total_dur, 'is_mix': is_mix,
        'thumbnail': _thumb(info) or (items[0]['thumbnail'] if items else None),
        'description': (info.get('description') or '')[:400],
        'items': items,
    }

def cb_analyze(url, mode='auto'):
    try:
        parsed = _parse_url(url, mode if mode in ('auto', 'video', 'playlist') else 'auto')
        result = {'ok': True, 'input': parsed['url'], 'mode': mode, 'video': None, 'playlist': None, 'playlist_error': None}
        if parsed['video_id']:
            opts = _base_opts(); opts['noplaylist'] = True
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(f"https://www.youtube.com/watch?v={parsed['video_id']}", download=False)
            if not info:
                raise RuntimeError('video unavailable')
            result['video'] = _summarize_video(info)
        if parsed['playlist_url']:
            try:
                result['playlist'] = _extract_playlist(parsed['playlist_url'], parsed['is_mix'])
            except Exception as e:
                # o vídeo continua utilizável mesmo se a playlist falhar
                if not result['video']:
                    raise
                result['playlist_error'] = _friendly_error(str(e))
        return JSON(result)
    except Exception as e:
        return JSON({'ok': False, 'error': _friendly_error(str(e))})

# ---------- download ----------
def _build_opts(job, item_state, mode, height, audio_format, audio_quality, embed_meta, out_dir):
    opts = _base_opts()
    opts.update({
        'outtmpl': os.path.join(out_dir, '%(title).150B [%(id)s].%(ext)s'),
        'noplaylist': True,
        'overwrites': True,
        'windowsfilenames': True,
        'concurrent_fragment_downloads': 4,
        'progress_hooks': [lambda d: _progress_hook(d, job, item_state)],
        'postprocessor_hooks': [lambda d: _pp_hook(d, job, item_state)],
        'postprocessors': [],
    })
    if mode == 'audio':
        opts['format'] = 'ba/b'
        pp = {'key': 'FFmpegExtractAudio', 'preferredcodec': audio_format}
        if audio_format not in ('best', 'wav', 'flac') and audio_quality and audio_quality != 'best':
            pp['preferredquality'] = str(audio_quality)
        elif audio_format == 'mp3':
            pp['preferredquality'] = '0'  # melhor VBR
        opts['postprocessors'].append(pp)
        if embed_meta:
            opts['postprocessors'].append({'key': 'FFmpegMetadata', 'add_metadata': True})
            if audio_format in ('mp3', 'm4a', 'flac', 'opus', 'aac'):
                opts['writethumbnail'] = True
                opts['postprocessors'].append({'key': 'EmbedThumbnail', 'already_have_thumbnail': False})
    else:
        sort = [f'res:{height}' if height and height != 'best' else 'res', 'fps', 'codec:avc1:m4a', 'ext:mp4:m4a']
        opts['format'] = 'bv*+ba/b'
        opts['format_sort'] = sort
        opts['merge_output_format'] = 'mp4'
        opts['postprocessors'].append({'key': 'FFmpegVideoRemuxer', 'preferedformat': 'mp4'})
        if embed_meta:
            opts['postprocessors'].append({'key': 'FFmpegMetadata', 'add_metadata': True})
    return opts

def _progress_hook(d, job, st):
    if job.get('cancel'):
        raise yt_dlp.utils.DownloadCancelled('Cancelado pelo usuário')
    if d['status'] == 'downloading':
        total = d.get('total_bytes') or d.get('total_bytes_estimate') or 0
        done = d.get('downloaded_bytes') or 0
        info = d.get('info_dict') or {}
        stream = 'áudio' if (info.get('vcodec') in (None, 'none')) else 'vídeo'
        st.update({
            'status': 'downloading', 'percent': (done / total * 100) if total else 0,
            'downloaded': done, 'total': total, 'speed': d.get('speed') or 0, 'eta': d.get('eta'),
            'stage': f'Baixando {stream}…',
        })
    elif d['status'] == 'finished':
        st.update({'percent': 100, 'stage': 'Download concluído, processando…'})

def _pp_hook(d, job, st):
    if job.get('cancel'):
        raise yt_dlp.utils.DownloadCancelled('Cancelado pelo usuário')
    names = {'FFmpegExtractAudio': 'Convertendo áudio…', 'FFmpegVideoRemuxer': 'Empacotando MP4…',
             'FFmpegMerger': 'Juntando vídeo e áudio…', 'FFmpegMetadata': 'Gravando metadados…',
             'EmbedThumbnail': 'Inserindo capa…', 'MoveFiles': 'Finalizando…'}
    if d['status'] in ('started', 'processing'):
        st.update({'status': 'processing', 'stage': names.get(d.get('postprocessor'), 'Processando…')})

def _final_path(info):
    rd = info.get('requested_downloads') or []
    if rd and rd[0].get('filepath') and os.path.exists(rd[0]['filepath']):
        return rd[0]['filepath']
    for k in ('filepath', '_filename', 'filename'):
        p = info.get(k)
        if p and os.path.exists(p): return p
    return None

def _run_job(job_id):
    job = STATE['jobs'][job_id]
    out_dir = os.path.join(DL_DIR, job_id)
    os.makedirs(out_dir, exist_ok=True)
    job['status'] = 'running'
    for st in job['items']:
        if job.get('cancel'):
            st.update({'status': 'cancelled', 'stage': 'Cancelado'}); continue
        st.update({'status': 'downloading', 'stage': 'Preparando…', 'percent': 0})
        try:
            opts = _build_opts(job, st, job['mode'], job['height'], job['audio_format'],
                               job['audio_quality'], job['embed_meta'], out_dir)
            logger = _SilentLogger()
            opts['logger'] = logger
            # erros de pós-processamento (ex.: capa) não devem derrubar o item inteiro
            opts['ignoreerrors'] = True
            before = set(os.listdir(out_dir))
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(st['url'], download=True)
            if job.get('cancel'):
                raise yt_dlp.utils.DownloadCancelled('Cancelado pelo usuário')
            path = _final_path(info) if info else None
            if not path:
                # fallback: arquivo novo mais recente da pasta
                cands = [os.path.join(out_dir, f) for f in os.listdir(out_dir)
                         if f not in before and not f.endswith(('.part', '.ytdl', '.webp', '.jpg', '.png'))]
                path = max(cands, key=os.path.getmtime) if cands else None
            if not path:
                raise RuntimeError(logger.errors[-1] if logger.errors else 'O arquivo final não foi encontrado após o download.')
            if logger.errors:
                st['warning'] = _friendly_error(logger.errors[-1])
            size = os.path.getsize(path)
            drive_path = None
            if job.get('save_drive') and _drive_on():
                sub = os.path.join(DRIVE_ROOT, 'Downloads', job.get('folder') or '')
                os.makedirs(sub, exist_ok=True)
                drive_path = os.path.join(sub, os.path.basename(path))
                shutil.copy2(path, drive_path)
            st.update({'status': 'done', 'percent': 100, 'stage': 'Concluído',
                       'file': os.path.basename(path), 'rel': f"{job_id}/{os.path.basename(path)}",
                       'size': size, 'size_label': _fmt_size(size),
                       'drive_path': drive_path.replace(DRIVE_MYDRIVE, 'Meu Drive') if drive_path else None,
                       'title': (info or {}).get('title') or st.get('title')})
        except yt_dlp.utils.DownloadCancelled:
            st.update({'status': 'cancelled', 'stage': 'Cancelado'})
        except Exception as e:
            st.update({'status': 'error', 'stage': 'Erro', 'error': _friendly_error(str(e))})
        job['completed'] = sum(1 for s in job['items'] if s['status'] in ('done', 'error', 'cancelled'))
    job['status'] = 'cancelled' if job.get('cancel') else 'finished'
    job['finished_at'] = time.time()

def cb_start_download(payload):
    try:
        items = payload.get('items') or []
        if not items:
            return JSON({'ok': False, 'error': 'Nenhum vídeo selecionado.'})
        job_id = uuid.uuid4().hex[:10]
        folder = re.sub(r'[^\w\s.-]', '', (payload.get('folder') or ''))[:80].strip()
        job = {
            'id': job_id, 'status': 'queued', 'cancel': False, 'created': time.time(),
            'mode': payload.get('mode', 'video'), 'height': payload.get('height', 'best'),
            'audio_format': payload.get('audio_format', 'mp3'), 'audio_quality': payload.get('audio_quality', 'best'),
            'embed_meta': bool(payload.get('embed_meta', True)), 'save_drive': bool(payload.get('save_drive')),
            'folder': folder, 'completed': 0,
            'items': [{'id': it.get('id'), 'url': it.get('url'), 'title': it.get('title'), 'thumbnail': it.get('thumbnail'),
                       'status': 'queued', 'percent': 0, 'stage': 'Na fila'} for it in items],
        }
        STATE['jobs'][job_id] = job
        threading.Thread(target=_run_job, args=(job_id,), daemon=True).start()
        return JSON({'ok': True, 'job_id': job_id})
    except Exception as e:
        return JSON({'ok': False, 'error': str(e)})

def cb_job_status(job_id):
    job = STATE['jobs'].get(job_id)
    if not job:
        return JSON({'ok': False, 'error': 'Tarefa não encontrada.'})
    view = {k: v for k, v in job.items() if k != 'cancel'}
    view['ok'] = True
    view['total'] = len(job['items'])
    return JSON(view)

def cb_cancel_job(job_id):
    job = STATE['jobs'].get(job_id)
    if job: job['cancel'] = True
    return JSON({'ok': True})

def cb_zip_job(job_id):
    try:
        job = STATE['jobs'].get(job_id)
        if not job: return JSON({'ok': False, 'error': 'Tarefa não encontrada.'})
        src = os.path.join(DL_DIR, job_id)
        name = re.sub(r'[^\w.-]+', '_', (job.get('folder') or 'downloads'))[:60] or 'downloads'
        zip_base = os.path.join(DL_DIR, f'{job_id}_{name}')
        # zipa apenas os arquivos finais
        tmp = os.path.join(DL_DIR, f'{job_id}_zipsrc'); shutil.rmtree(tmp, ignore_errors=True); os.makedirs(tmp)
        for st in job['items']:
            if st.get('status') == 'done' and st.get('file'):
                shutil.copy2(os.path.join(src, st['file']), os.path.join(tmp, st['file']))
        zp = shutil.make_archive(zip_base, 'zip', tmp)
        shutil.rmtree(tmp, ignore_errors=True)
        return JSON({'ok': True, 'rel': os.path.basename(zp), 'size_label': _fmt_size(os.path.getsize(zp))})
    except Exception as e:
        return JSON({'ok': False, 'error': str(e)})

def cb_cleanup(job_id=None):
    try:
        if job_id:
            shutil.rmtree(os.path.join(DL_DIR, job_id), ignore_errors=True)
            for f in os.listdir(DL_DIR):
                if f.startswith(job_id + '_'): os.remove(os.path.join(DL_DIR, f))
            STATE['jobs'].pop(job_id, None)
        else:
            shutil.rmtree(DL_DIR, ignore_errors=True); os.makedirs(DL_DIR, exist_ok=True)
            STATE['jobs'].clear()
        return JSON({'ok': True})
    except Exception as e:
        return JSON({'ok': False, 'error': str(e)})

def cb_colab_download(rel):
    """Fallback: usa o download nativo do Colab."""
    try:
        from google.colab import files as colab_files
        colab_files.download(os.path.join(DL_DIR, rel))
        return JSON({'ok': True})
    except Exception as e:
        return JSON({'ok': False, 'error': str(e)})

# ---------- servidor de arquivos (download direto pelo navegador) ----------
class _FileHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **k):
        super().__init__(*a, directory=DL_DIR, **k)
    def end_headers(self):
        path = urllib.parse.unquote(self.path.split('?')[0])
        name = os.path.basename(path)
        if name:
            quoted = urllib.parse.quote(name)
            ascii_name = re.sub(r'[^\x20-\x7e]', '_', name).replace('"', '')
            self.send_header('Content-Disposition', f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quoted}")
            self.send_header('Cache-Control', 'no-store')
        self.send_header('Access-Control-Allow-Origin', '*')
        super().end_headers()
    def list_directory(self, path):
        self.send_error(403, 'Listagem desabilitada'); return None
    def log_message(self, *a): pass

def _start_file_server():
    if STATE.get('server'): return
    class _Srv(socketserver.ThreadingTCPServer):
        allow_reuse_address = True
        daemon_threads = True
    try:
        srv = _Srv(('0.0.0.0', FILE_PORT), _FileHandler)
    except OSError:
        return  # já está rodando de uma execução anterior
    STATE['server'] = srv
    threading.Thread(target=srv.serve_forever, daemon=True).start()

_start_file_server()

# ---------- registro das funções para a interface ----------
def _register(name, fn):
    try:
        from google.colab import output as _out
        _out.register_callback(f'ytd.{name}', fn)
    except Exception:
        pass

for _n, _f in {
    'bootstrap': cb_bootstrap, 'save_cookies': cb_save_cookies, 'clear_cookies': cb_clear_cookies,
    'test_cookies': cb_test_cookies, 'analyze': cb_analyze, 'start_download': cb_start_download,
    'job_status': cb_job_status, 'cancel_job': cb_cancel_job, 'zip_job': cb_zip_job,
    'cleanup': cb_cleanup, 'colab_download': cb_colab_download,
}.items():
    _register(_n, _f)

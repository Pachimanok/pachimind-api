"""Synthetic association fixture; never connects to or accepts a real vault."""
import os
from pathlib import Path
import sys
os.environ.update(VAULT_PATH='/tmp/pachimind-association-preview-unused',
                  API_KEYS='{"test-personal":"personal","reader":"ai_context","test-public":"public"}',
                  PM_API_KEY='test-personal', LOG_LEVEL='WARNING', NODE_URL='http://127.0.0.1:18300',
                  NOTEBOOKLM_BIN='/nonexistent/preview-notebooklm')
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from people_preview import create_demo
from app.core.meeting_capture import serialize
from app.core.vault_index import vault_index
root = create_demo()
fixtures = [
    ('huerfana', 'Nota huérfana demo', '', {'area':'Laboral'}),
    ('entrada', 'Referencia recibida demo', '', {'area':'Laboral'}),
    ('puente', 'Puente demo', '[[Referencia recibida demo]] [[Proyecto de ejemplo]]', {'area':'Laboral'}),
    ('rota', 'Referencia sin destino demo', '[[Destino pendiente demo]]', {}),
    ('sin-nodo-a', 'Conexión entre notas demo A', '[[Conexión entre notas demo B]]', {}),
    ('sin-nodo-b', 'Conexión entre notas demo B', '', {}),
    ('xss', '<img src=x onerror=alert(1)>', '', {}),
]
for i in range(22):fixtures.append((f'paginada-{i}', f'Nota paginada demo {i:02d}', '', {'area':'Personal'}))
for name,title,body,extra in fixtures:
    p = root/'07 Conocimiento/Contexto'/f'{name}.md';p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(serialize(dict(titulo=title,tipo='nota',estado='activo',sensibilidad='normal',
                               ia_permiso='allow',ia_indexar=True,**extra),body or '# Datos sintéticos'))
    vault_index.rebuild_file(p)
from app.main import app
@app.get('/health/preview')
def marker():return {'synthetic': True, 'fixture': 'association-demo'}
if __name__=='__main__':
    import uvicorn
    print('Synthetic association demo ready; no real notes used.',flush=True)
    uvicorn.run(app,host='127.0.0.1',port=int(os.environ.get('PREVIEW_API_PORT','18000')),
                access_log=False,log_level='warning')

"""Start an isolated demo API. Always creates a NEW temporary vault; never uses a real vault."""
import os, tempfile
from pathlib import Path


def create_demo():
    from app.core.meeting_capture import serialize
    from app.core.id_utils import path_to_id
    from app.core.vault_index import vault_index
    from app.core import people
    from app.models.people import LinkCommand, ReviewCommand, PersonProposal
    from uuid import uuid4
    root = Path(tempfile.mkdtemp(prefix='pachimind-people-demo-')).resolve()
    from app.config import settings
    settings.vault_path = str(root)
    vault_index.build(root)
    def write(relative, title, content='', **meta):
        values = dict(titulo=title, tipo='nota', estado='activo', sensibilidad='normal', ia_permiso='allow',
                      ia_indexar=True, ia_editar=False, revisado=False)
        values.update(meta)
        file = root/relative; file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(serialize(values, content or ('# '+title+'\n\nDatos sintéticos de prueba.\n')))
        vault_index.rebuild_file(file)
        return path_to_id(relative)
    source = write('06 Reuniones y Registros/fuente-demo.md', 'Fuente de prueba · datos sintéticos',
                   'Documento sintético: Organización de ejemplo. Se menciona a Andrés (demo). No se confirma asistencia. Función registrada para Sabrina Ramirez (demo): Documentación de prueba.\n',
                   tipo='reunion', fuente_inmutable=True, fecha='2026-10-14')
    project = write('05 Proyectos/proyecto-demo.md', 'Proyecto de ejemplo', tipo='proyecto', area='Laboral')
    organization = write('04 Entidades/Organizaciones/demo.md', 'Organización de ejemplo', tipo='organizacion')
    names = ['Andrés', 'Sabrina Ramirez', 'Uriel Cabrera', 'Giovana', 'Genaro']
    ids = []
    for index, name in enumerate(names):
        meta = dict(tipo='persona', nombre=name+' (demo)', aliases=[name], origen='persona_manual',
                    ambitos=[['Trabajo','Formación'],['Trabajo'],['Colegios'],['Apostólico','Formación'],[]][index],
                    organizacion='Organización de ejemplo' if index < 2 else None,
                    funcion='Función declarada en la demo' if index == 0 else None,
                    revisado=index == 0, relacion_conmigo='Relación de ejemplo' if index == 0 else None)
        ids.append(write(f'04 Entidades/Personas/{index}-demo.md', name+' (demo)', **meta))
    write('Bienvenido.md', 'Bienvenido', 'Vault ficticio para validar Personas. No contiene datos reales.\n')
    write('04 Entidades/Personas/manual-demo.md', 'Manual de ejemplo (demo)', tipo='persona')
    write('04 Entidades/Personas/genaro-similar.md', 'Genaro (demó)', tipo='persona')
    write('04 Entidades/Personas/reservada-demo.md', 'Persona reservada de prueba', 'RESERVADO NO DIVULGAR', tipo='persona', sensibilidad='secreto', tags=['oculto'])
    links = LinkCommand(request_id=uuid4(), source_id=ids[0], revision=people.revision(vault_index.get(ids[0])),
                        links=[dict(target_id=project, target_revision=people.revision(vault_index.get(project)), relation='vinculado al proyecto'),
                               dict(target_id=source, target_revision=people.revision(vault_index.get(source)), relation='mencionado en')])
    proposed = people.propose_links(links, 'personal', False)
    people.review(proposed['id'], ReviewCommand(request_id=uuid4(), revision=links.revision, action='apply', authorized_fields=['relations']), 'personal', False)
    body = PersonProposal(request_id=uuid4(), revision=people.revision(vault_index.get(ids[1])), fields={'funcion':'Documentación de prueba'},
                          evidence=[dict(field='funcion', source_id=source, quote='Función registrada para Sabrina Ramirez (demo): Documentación de prueba.')],
                          questions=['¿Cuál es la función confirmada? Verificar vigencia con la persona; no inferirla de una mención.'])
    people.propose_person(ids[1], body, 'personal', True)
    return root

if __name__ == '__main__':
    # Explicit synthetic bindings override ambient variables; never copy .env.
    os.environ.update(VAULT_PATH='/tmp/pachimind-demo-unused', API_KEYS='{"test-personal":"personal","reader":"ai_context","test-public":"public"}',
                      PM_API_KEY='test-personal', LOG_LEVEL='WARNING', NODE_URL='http://127.0.0.1:18300', NOTEBOOKLM_BIN='/nonexistent/preview-notebooklm')
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    root = create_demo()
    print('Vault sintético temporal:', root, flush=True)
    from app.main import app
    @app.get('/health/preview')
    def preview_marker():
        return {'synthetic': True, 'fixture': 'people-demo'}
    import uvicorn
    uvicorn.run(app, host='127.0.0.1', port=int(os.environ.get('PREVIEW_API_PORT', '18000')), access_log=False, log_level='warning')

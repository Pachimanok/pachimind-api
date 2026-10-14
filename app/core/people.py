"""People reuse vault IDs. Review, relationships and audit live outside original bodies."""
from collections import defaultdict
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import PurePosixPath
import json
import os
import re
import tempfile
import unicodedata

import frontmatter
import yaml
from fastapi import HTTPException
from rapidfuzz import fuzz
from app.core.meeting_capture import transaction, path_for, atomic_write, serialize, readable_slug, digest
from app.core.id_utils import path_to_id
from app.core.project_memory import reference, reference_labels
from app.core.vault_index import vault_index
from app.middleware.permissions import is_visible, is_ai_eligible, apply_content_rules
from app.models.people import PersonFields

STORE = '.pachimind'
FIELD_NAMES = set(PersonFields.model_fields)
PENDING_FIELDS = ['organizacion', 'funcion', 'relacion_conmigo', 'ambitos', 'contactos_profesionales']
BASE_METADATA = ['tipo', 'estado', 'revisado', 'ia_permiso', 'ia_indexar', 'ia_editar', 'fuente_inmutable', 'sensibilidad']


def now():
    return datetime.now(timezone.utc).isoformat()


def allowed_path(path):
    return not any(p.startswith(('.', '_privado_')) or p in {'00 Sistema', '10 Sensible', '99 Adjuntos'} for p in PurePosixPath(path).parts)


def visible(note, scope, ai=False):
    return allowed_path(note.path) and is_visible(note, scope) and (not ai or is_ai_eligible(note))


def node(note_id, scope, ai=False):
    n = vault_index.get(note_id)
    if n:
        vault_index.rebuild_file(path_for(n.path))
        n = vault_index.get(note_id)
    if not n or not visible(n, scope, ai) or not path_for(n.path).is_file():
        raise HTTPException(404, 'Nota no disponible')
    return n


def raw(n):
    data = path_for(n.path).read_bytes()
    return data, frontmatter.loads(data.decode('utf-8'))


def records(kind):
    folder = path_for(f'{STORE}/{kind}')
    if not folder.exists():
        return []
    return [json.loads(p.read_text()) for p in sorted(folder.glob('*.json'))]


def record_path(kind, key):
    # Only internally generated UUIDs or hashes; never a user-controlled path.
    if not re.fullmatch(r'[a-f0-9-]{32,64}', str(key)):
        raise HTTPException(422, 'Identificador de operación inválido')
    return f'{STORE}/{kind}/{key}.json'


def save(kind, key, value):
    relative = record_path(kind, key)
    destination = path_for(relative)
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temporary = tempfile.mkstemp(prefix='.people-', dir=destination.parent)
    try:
        with os.fdopen(fd, 'w') as out:
            json.dump(value, out, ensure_ascii=False, sort_keys=True)
            out.flush(); os.fsync(out.fileno())
        os.replace(temporary, destination)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    # JSON sidecars are deliberately not passed to the Markdown index.
    return relative


def load(kind, key):
    path = path_for(record_path(kind, key))
    if not path.exists():
        raise HTTPException(404, 'Operación no encontrada')
    return json.loads(path.read_text())


def person(n):
    return n.metadata.tipo == 'persona' or n.path.startswith('04 Entidades/Personas/')


def canonical(value):
    return ' '.join(unicodedata.normalize('NFC', value).casefold().split())


def fields(n):
    _, post = raw(n)
    m = post.metadata
    values = {key: m.get(key) for key in FIELD_NAMES}
    values['nombre'] = m.get('nombre') or re.sub(r'\[\[([^\]|]+)(?:\|[^\]]+)?\]\]', r'\1', n.title)
    values['aliases'] = n.metadata.aliases
    values['funcion'] = m.get('funcion') or m.get('rol')
    values['organizacion'] = m.get('organizacion')  # A client association is not an organization/employer assertion.
    values['ambitos'] = n.metadata.ambitos if 'ambitos' in m else ({'Laboral': ['Trabajo'], 'Apostolado': ['Apostólico']}.get(m.get('area'), []))
    values['contactos_profesionales'] = m.get('contactos_profesionales') or {}
    values['notas_manuales'] = m.get('notas_manuales')
    return values


def names(n, include_filename=False):
    values = [fields(n)['nombre'], n.title, *n.metadata.aliases]
    if include_filename:
        values.append(PurePosixPath(n.path).stem)
    return {canonical(v) for v in values if v}


def duplicates(n, scope, ai):
    source = names(n)
    result = []
    for other in vault_index.all():
        if other.id != n.id and person(other) and visible(other, scope, ai):
            score = max(fuzz.ratio(a, b) for a in source for b in names(other))
            if score >= 82:
                result.append({'id': other.id, 'title': other.title, 'path': other.path, 'reason': 'Similitud de nombre o alias; identidad sin confirmar'})
    return result


def relation_key(source, target, kind):
    return digest([source, target, kind])


def relation_rows(scope, ai=False):
    notes = vault_index.all()
    allowed = {n.id: n for n in notes if visible(n, scope, ai)}
    labels = defaultdict(set)
    for n in notes:
        for label in reference_labels(n):
            labels[reference(label)].add(n.id)
    overlay = {relation_key(r['source_id'], r['target_id'], r['relation']): r for r in records('relations')}
    rows = {}
    issues = defaultdict(lambda: {'broken': [], 'ambiguous': []})
    for n in allowed.values():
        # Only explicit fields/wikilinks; prose mentions never create relationships.
        refs = [*n.wikilinks, *n.metadata.personas, *n.metadata.proyectos, *n.metadata.fuentes_ids]
        refs += [v for v in [n.metadata.organizacion, n.metadata.cliente] if v]
        for value in refs:
            matches = labels.get(reference(value), set())
            if not matches:
                issues[n.id]['broken'].append(value)
            elif len(matches) > 1:
                if matches <= set(allowed):
                    issues[n.id]['ambiguous'].append(value)
            else:
                target = next(iter(matches))
                if target not in allowed or target == n.id:
                    continue
                key = relation_key(n.id, target, 'referencia')
                if key not in overlay or overlay[key]['active']:
                    rows[key] = {'id': key, 'source_id': n.id, 'target_id': target, 'relation': 'referencia', 'origin': 'legacy', 'evidence': None, 'created_at': None}
    for key, value in overlay.items():
        proof = value.get('evidence')
        proof_allowed = not proof or proof['source_id'] in allowed
        if value['active'] and value['source_id'] in allowed and value['target_id'] in allowed and proof_allowed:
            rows[key] = value
        elif not value['active']:
            rows.pop(key, None)
    return list(rows.values()), issues, allowed


def revision(n):
    data, _ = raw(n)
    overlay = sorted([r for r in records('relations') if n.id in (r['source_id'], r['target_id'])], key=lambda r: r['id'])
    return digest({'file': sha256(data).hexdigest(), 'relations': overlay})


def require_revision(n, expected):
    if revision(n) != expected:
        raise HTTPException(409, 'La nota o sus relaciones cambiaron. Releé antes de editar.')


def safe_evidence(items, scope, ai=False, expected=None):
    result = []
    for item in items:
        value = item.model_dump(mode='json') if hasattr(item, 'model_dump') else dict(item)
        source = node(value['source_id'], scope, ai)
        if source.metadata.sensibilidad in {'privado', 'sensible', 'secreto'}:
            raise HTTPException(409, 'No copiar evidencia reservada a una ficha. Usá una referencia neutral y revisión específica.')
        data, post = raw(source)
        if value['quote'] not in post.content:
            raise HTTPException(422, 'La evidencia debe ser una cita literal de la fuente disponible')
        source_revision = sha256(data).hexdigest()
        if expected and value.get('source_revision') != source_revision:
            raise HTTPException(409, 'Una fuente cambió. Revisá la evidencia antes de aplicar.')
        value.update({'source_revision': source_revision, 'path': source.path, 'fecha': source.metadata.fecha})
        no_credentials(value)
        result.append(value)
    return result


def proposal_visible(value, scope, ai):
    ids = [value['target_id']]
    ids += [e['source_id'] for e in value.get('evidence', [])]
    ids += [link['target_id'] for link in value.get('links', [])]
    return all(vault_index.get(i) and visible(vault_index.get(i), scope, ai) for i in ids)


def profile(note_id, scope, ai=False):
    n = node(note_id, scope, ai)
    if not person(n):
        raise HTTPException(404, 'Ficha no disponible')
    data, post = raw(n)
    values = fields(n)
    sources = {}
    for key, proof in (post.metadata.get('datos_fuente') or {}).items():
        if key not in FIELD_NAMES:
            continue
        if all(vault_index.get(p['source_id']) and visible(vault_index.get(p['source_id']), scope, ai) for p in proof):
            sources[key] = proof
        else:
            values[key] = None
    rows, issues, nodes = relation_rows(scope, ai)
    outgoing = [r for r in rows if r['source_id'] == n.id]
    incoming = [r for r in rows if r['target_id'] == n.id]
    related = []
    for row, direction in [(r, 'saliente') for r in outgoing] + [(r, 'entrante') for r in incoming]:
        other = nodes[row['target_id'] if direction == 'saliente' else row['source_id']]
        proof = row.get('evidence')
        if proof and (not vault_index.get(proof['source_id']) or not visible(vault_index.get(proof['source_id']), scope, ai)):
            continue
        related.append({**{k: v for k, v in row.items() if k != 'active'}, 'direction': direction,
                        'other_id': other.id, 'title': other.title, 'path': other.path, 'tipo': other.metadata.tipo})
    pending = [c for c in records('changes') if (c['target_id'] == n.id or any(l['target_id'] == n.id for l in c.get('links', [])))
               and c['state'] == 'pending' and proposal_visible(c, scope, ai)]
    history = []
    for h in records('history'):
        if n.id not in h.get('involved_ids', [h['target_id']]):
            continue
        owner = vault_index.get(h['target_id'])
        if owner and visible(owner, scope, ai):
            history.append({'id': h['id'], 'at': h['at'], 'origin': h['origin'], 'operation': h['operation'],
                            'undone': h.get('undone', False), 'target_id': owner.id, 'target_revision': revision(owner)})
    warning = None
    if n.metadata.tipo != 'persona':
        warning = 'Archivo en Personas clasificado como ' + (n.metadata.tipo or 'sin tipo') + '. Revisar ubicación, sin mover automáticamente.'
    elif re.search(r'\b(idea|manual|tutorial|guía)\b', n.title, re.I):
        warning = 'El título parece material de conocimiento. Proponer revisar tipo; no se reclasifica automáticamente.'
    return {'id': n.id, 'path': n.path, 'title': n.title, 'revision': revision(n), 'fields': values,
            'metadata': {k: getattr(n.metadata, k, None) for k in BASE_METADATA},
            'pending_fields': [key for key in PENDING_FIELDS if not values.get(key)], 'field_sources': sources,
            'relations': related, 'incoming_count': len(incoming), 'outgoing_count': len(outgoing),
            'broken_links': sorted(set(issues[n.id]['broken'])), 'ambiguous_links': sorted(set(issues[n.id]['ambiguous'])),
            'pending_changes': len(pending), 'possible_duplicates': duplicates(n, scope, ai), 'classification_warning': warning,
            'history': sorted(history, key=lambda h: h['at'], reverse=True), 'last_review': n.metadata.ultima_revision,
            'change_origin': post.metadata.get('origen'),
            'original_content': next((v for v in apply_content_rules(n, scope) if v is not None), '')}


def directory(scope, ai=False, query='', ambito=None, view=None, page=1, per_page=20):
    results = []
    for n in vault_index.all():
        if not person(n) or not visible(n, scope, ai) or n.metadata.estado == 'archivado':
            continue
        item = profile(n.id, scope, ai)
        haystack = ' '.join([str(item['fields'].get(k) or '') for k in ['nombre', 'aliases', 'organizacion']])
        if query and canonical(query) not in canonical(haystack):
            continue
        if ambito and ambito not in (item['fields'].get('ambitos') or []):
            continue
        if view == 'incomplete' and not item['pending_fields']:
            continue
        if view == 'pending' and not item['pending_changes']:
            continue
        if view == 'unconnected' and item['incoming_count'] + item['outgoing_count']:
            continue
        if view == 'no_outgoing' and item['outgoing_count']:
            continue
        if view == 'duplicates' and not item['possible_duplicates']:
            continue
        results.append(item)
    results.sort(key=lambda x: canonical(x['fields']['nombre']))
    start = (page - 1) * per_page
    return {'total': len(results), 'page': page, 'per_page': per_page, 'results': results[start:start + per_page]}


def no_credentials(value):
    text = json.dumps(value, ensure_ascii=False)
    if re.search(r'-----BEGIN .*PRIVATE KEY-----|(?:password|api[_-]?key|access_token|client_secret)["\s]*[:=]["\s]*[^\s,}]{8,}', text, re.I):
        raise HTTPException(422, 'No incluyas credenciales en fichas o borradores')


def replay(body, operation, scope, ai):
    key = str(body.request_id)
    path = path_for(record_path('requests', key))
    fingerprint = digest({'operation': operation, 'payload': body.model_dump(mode='json')})
    if path.exists():
        previous = load('requests', key)
        if previous['fingerprint'] != fingerprint:
            raise HTTPException(409, 'request_id reutilizado con otra operación o contenido')
        target = previous['result'].get('id')
        if target and previous['operation'] in {'create_person', 'update_person'}:
            node(target, scope, ai)
        return previous['result'], fingerprint
    return None, fingerprint


def remember(body, operation, fingerprint, result):
    save('requests', str(body.request_id), {'operation': operation, 'fingerprint': fingerprint, 'result': result})
    return result


def create_person(body, scope, ai):
    no_credentials(body.model_dump(mode='json'))
    with transaction():
        result, fingerprint = replay(body, 'create_person', scope, ai)
        if result:
            return {**result, 'created': False}
        requested = canonical(body.nombre)
        matches = [n for n in vault_index.all() if person(n) and requested in names(n, include_filename=True)]
        if matches:
            available = [n for n in matches if visible(n, scope, ai)]
            if len(matches) != 1 or len(available) != 1:
                raise HTTPException(409, 'Nombre ya utilizado o identidad ambigua; revisión humana necesaria')
            n = available[0]
            result = {'id': n.id, 'path': n.path, 'created': False, 'revision': revision(n), 'state': 'existing', 'needs_identity_review': True}
            return remember(body, 'create_person', fingerprint, result)
        candidates = [n for n in vault_index.all() if person(n) and visible(n, scope, ai) and
                      max(fuzz.ratio(requested, label) for label in names(n)) >= 82]
        if any(n.id not in body.distinct_from for n in candidates):
            raise HTTPException(409, 'Hay nombres similares. Revisá las fichas y confirmá las identidades distintas, sin fusionarlas.')
        relative = f'04 Entidades/Personas/{readable_slug(body.nombre)}-{body.request_id}.md'
        if path_for(relative).exists():
            n = node(path_to_id(relative), scope, ai)
            _, old = raw(n)
            if old.metadata.get('request_hash') != fingerprint:
                raise HTTPException(409, 'Destino ocupado por otro contenido')
        else:
            meta = {'titulo': body.nombre.strip(), 'nombre': body.nombre.strip(), 'tipo': 'persona', 'estado': 'para_revisar',
                    'aliases': [], 'ambitos': [], 'sensibilidad': 'normal', 'ia_permiso': 'allow', 'ia_indexar': True,
                    'ia_editar': ai, 'revisado': False, 'origen': 'persona_asistente' if ai else 'persona_manual',
                    'creada_en': now(), 'request_hash': fingerprint}
            history = history_start(body, path_to_id(relative), 'assistant' if ai else 'manual', 'create_person', {relative: None})
            atomic_write(relative, serialize(meta, '# ' + body.nombre.strip() + '\n\nFicha mínima. Datos pendientes de revisión.\n'))
            n = node(path_to_id(relative), scope, ai)
            history_finish(history)
        result = {'id': n.id, 'path': relative, 'created': True, 'revision': revision(n), 'state': 'pending'}
        return remember(body, 'create_person', fingerprint, result)


def assistant_editable(n):
    if n.metadata.fuente_inmutable or n.metadata.revisado or not n.metadata.ia_editar:
        raise HTTPException(409, 'Ficha protegida para edición por IA. Conservá la propuesta para revisión manual.')


def history_start(body, n, origin, operation, before):
    snapshots = {}
    for relative, previous in before.items():
        if previous is not None and relative.endswith('.md'):
            match = re.match(r'\A---\r?\n.*?\r?\n---(?:\r?\n|$)', previous, re.S)
            if not match:
                raise HTTPException(409, 'Frontmatter inválido para registrar el cambio')
            snapshots[relative] = {'header': previous[:match.end()], 'body_sha256': sha256(previous[match.end():].encode()).hexdigest()}
        else:
            snapshots[relative] = previous
    value = {'id': str(body.request_id), 'target_id': n if isinstance(n, str) else n.id, 'at': now(), 'origin': origin,
             'operation': operation, 'before': snapshots, 'after': {}, 'undone': False}
    save('history', value['id'], value)
    return value


def history_finish(value):
    value['after'] = {relative: sha256(path_for(relative).read_bytes()).hexdigest() for relative in value['before']}
    save('history', value['id'], value)


def update_person(note_id, body, scope, ai):
    with transaction():
        result, fingerprint = replay(body, 'update_person', scope, ai)
        if result:
            if result['id'] != note_id:
                raise HTTPException(409, 'Operación asociada a otra ficha')
            return result
        n = node(note_id, scope, ai)
        if not person(n):
            raise HTTPException(404, 'Ficha no disponible')
        if ai:
            assistant_editable(n)
            if body.confirm_review:
                raise HTTPException(403, 'La IA no puede marcar una ficha como revisada')
        if n.metadata.fuente_inmutable:
            raise HTTPException(409, 'Fuente inmutable: proponé una corrección separada')
        require_revision(n, body.revision)
        changes = body.fields.model_dump(exclude_unset=True)
        if not changes:
            raise HTTPException(422, 'No hay campos para cambiar')
        if changes.get('nombre', 'not-null') is None or changes.get('tipo', 'not-null') is None:
            raise HTTPException(422, 'Nombre y tipo no pueden quedar vacíos')
        no_credentials(changes)
        if changes.get('nombre') and any(other.id != n.id and person(other) and canonical(changes['nombre']) in names(other) for other in vault_index.all()):
            raise HTTPException(409, 'Nombre ya utilizado: revisar identidad sin fusionar fichas')
        if ai:
            raise HTTPException(403, 'La IA debe aplicar una propuesta autorizada, no editar directamente')
        proof = safe_evidence(body.evidence, scope, ai)
        data, post = raw(n)
        match = re.match(r'\A---\r?\n.*?\r?\n---(?:\r?\n|$)', data.decode(), re.S)
        if not match:
            raise HTTPException(409, 'Frontmatter inválido; no se reescribe el archivo')
        history = history_start(body, n, 'manual', 'person_update', {n.path: data.decode()})
        post.metadata.update(changes)
        if 'nombre' in changes:
            if changes['nombre'] != n.title:
                post.metadata['titulos_anteriores'] = list(dict.fromkeys([*n.metadata.titulos_anteriores, n.title]))
            post.metadata['titulo'] = changes['nombre']
        if 'funcion' in changes:
            post.metadata['rol'] = changes['funcion']
        sources = post.metadata.get('datos_fuente') or {}
        for key in changes:
            sources.pop(key, None)
            selected = [p for p in proof if p['field'] == key]
            if selected:
                sources[key] = selected
        post.metadata.update({'datos_fuente': sources, 'origen': 'persona_manual', 'modificada_en': now()})
        if body.confirm_review:
            post.metadata.update({'revisado': True, 'ultima_revision': now(), 'estado': 'activo'})
        text = '---\n' + yaml.safe_dump(post.metadata, allow_unicode=True, sort_keys=False) + '---\n' + data.decode()[match.end():]
        atomic_write(n.path, text, replace=True)
        history_finish(history)
        result = {'id': n.id, 'path': n.path, 'revision': revision(node(n.id, scope, ai)), 'history_id': history['id']}
        return remember(body, 'update_person', fingerprint, result)


def propose_person(note_id, body, scope, ai):
    with transaction():
        n = node(note_id, scope, ai)
        if not person(n):
            raise HTTPException(404, 'Ficha no disponible')
        existing = path_for(record_path('changes', str(body.request_id)))
        fingerprint = digest({'kind': 'person', 'target_id': note_id, 'payload': body.model_dump(mode='json')})
        if existing.exists():
            previous = load('changes', str(body.request_id))
            if previous['fingerprint'] != fingerprint:
                raise HTTPException(409, 'Propuesta existente con otro contenido')
            if not proposal_visible(previous, scope, ai):
                raise HTTPException(404, 'Propuesta no disponible')
            return previous
        require_revision(n, body.revision)
        changes = body.fields.model_dump(exclude_unset=True)
        if not changes and not body.questions:
            raise HTTPException(422, 'Propuesta vacía')
        no_credentials({'fields': changes, 'questions': body.questions})
        proof = safe_evidence(body.evidence, scope, ai)
        no_credentials(proof)
        if any(key not in {p['field'] for p in proof} for key in changes):
            raise HTTPException(422, 'Cada campo propuesto necesita evidencia propia')
        if ai:
            for key, value in changes.items():
                if key in {'notas_manuales', 'tipo', 'ambitos'} or value is None:
                    continue  # Derived text/classification stays explicitly pending.
                values = list(value.values()) if isinstance(value, dict) else value if isinstance(value, list) else [value]
                quotes = ' '.join(p['quote'] for p in proof if p['field'] == key)
                if any(canonical(str(v)) not in canonical(quotes) for v in values if v):
                    raise HTTPException(422, 'No deduzcas datos personales: proponé sólo valores explícitos de la evidencia o una pregunta pendiente')
        value = {'id': str(body.request_id), 'kind': 'person', 'target_id': note_id, 'base_revision': body.revision,
                 'state': 'pending', 'origin': 'assistant' if ai else 'manual', 'created_at': now(), 'fields': changes,
                 'evidence': proof, 'questions': body.questions, 'fingerprint': fingerprint}
        save('changes', value['id'], value)
        return value


def validate_links(n, links, scope, ai):
    result = []
    seen = set()
    for item in links:
        target = node(item.target_id, scope, ai)
        require_revision(target, item.target_revision)
        if target.id == n.id:
            raise HTTPException(422, 'No vincular una nota consigo misma')
        kind = item.relation
        key = (item.target_id, kind)
        if key in seen:
            raise HTTPException(422, 'Relación repetida en el lote')
        seen.add(key)
        if kind in {'participó en', 'mencionado en', 'trabaja con'} and n.metadata.tipo != 'persona':
            raise HTTPException(422, 'La relación necesita una persona como origen')
        if kind == 'participó en' and target.metadata.tipo != 'reunion':
            raise HTTPException(422, 'Participación requiere una reunión como destino')
        if kind == 'vinculado al proyecto' and target.metadata.tipo != 'proyecto':
            raise HTTPException(422, 'El destino debe ser un proyecto')
        if kind == 'trabaja con' and target.metadata.tipo not in {'persona', 'organizacion', 'cliente'}:
            raise HTTPException(422, 'Destino incompatible con trabaja con')
        proof = safe_evidence([item.evidence], scope, ai) if item.evidence else []
        if ai and item.action == 'add' and not proof:
            raise HTTPException(422, 'Una relación del asistente necesita evidencia literal; una mención no prueba participación')
        if ai and kind == 'participó en' and item.action == 'add':
            participants = {canonical(p) for p in target.metadata.personas}
            if target.metadata.origen != 'captura_reunion' or not (participants & names(n)):
                raise HTTPException(422, 'Una mención no identifica participantes; requiere confirmación humana explícita')
        result.append({**item.model_dump(mode='json'), 'evidence': proof[0] if proof else None})
    return result


def propose_links(body, scope, ai):
    with transaction():
        n = node(body.source_id, scope, ai)
        key = str(body.request_id)
        fingerprint = digest({'kind': 'links', 'payload': body.model_dump(mode='json')})
        if path_for(record_path('changes', key)).exists():
            value = load('changes', key)
            if value['fingerprint'] != fingerprint:
                raise HTTPException(409, 'Propuesta existente con otro contenido')
            if not proposal_visible(value, scope, ai):
                raise HTTPException(404, 'Propuesta no disponible')
            return value
        require_revision(n, body.revision)
        links = validate_links(n, body.links, scope, ai)
        value = {'id': key, 'kind': 'links', 'target_id': n.id, 'base_revision': body.revision,
                 'state': 'pending', 'origin': 'assistant' if ai else 'manual', 'created_at': now(), 'links': links,
                 'evidence': [p['evidence'] for p in links if p['evidence']],
                 'reserved_segments': [s.model_dump() for s in body.reserved_segments], 'fingerprint': fingerprint}
        save('changes', key, value)
        return value


def pending(scope, ai, note_id=None, page=1, per_page=20):
    values = [v for v in records('changes') if v['state'] == 'pending' and
              (not note_id or v['target_id'] == note_id or any(l['target_id'] == note_id for l in v.get('links', []))) and proposal_visible(v, scope, ai)]
    start = (page - 1) * per_page
    selected = []
    for value in values[start:start + per_page]:
        display = dict(value)
        source = vault_index.get(value['target_id'])
        display['source'] = {'id': source.id, 'title': source.title, 'path': source.path}
        if value['kind'] == 'links':
            display['links'] = []
            for link in value['links']:
                target = vault_index.get(link['target_id'])
                display['links'].append({**link, 'target': {'id': target.id, 'path': target.path, 'title': target.title, 'tipo': target.metadata.tipo}})
        selected.append(display)
    return {'total': len(values), 'page': page, 'per_page': per_page, 'results': selected}


def review(change_id, body, scope, ai):
    with transaction():
        value = load('changes', change_id)
        if body.expected_kind and body.expected_kind != value['kind']:
            raise HTTPException(422, 'La herramienta no corresponde al tipo de propuesta')
        if not proposal_visible(value, scope, ai):
            raise HTTPException(404, 'Propuesta no disponible')
        n = node(value['target_id'], scope, ai)
        result, fingerprint = replay(body, 'review:' + change_id, scope, ai)
        if result:
            return result
        if value['state'] != 'pending':
            if value.get('review_request_id') == str(body.request_id) and value.get('review_fingerprint') == fingerprint:
                return remember(body, 'review:' + change_id, fingerprint, value['result'])
            raise HTTPException(409, 'La propuesta ya fue resuelta')
        if body.action == 'apply':
            if value['kind'] == 'person' and not value['fields']:
                raise HTTPException(422, 'Las preguntas no se aplican como hechos. Prepará una respuesta con evidencia nueva.')
            require_revision(n, body.revision)
            if body.revision != value['base_revision']:
                raise HTTPException(409, 'La ficha cambió desde la propuesta. Prepará una propuesta nueva.')
            keys = set(value['fields']) if value['kind'] == 'person' else {'relations'}
            if set(body.authorized_fields) != keys:
                raise HTTPException(422, 'Autorizá explícitamente todos y sólo los campos mostrados en esta propuesta')
            safe_evidence(value['evidence'], scope, ai, expected=True)
            if ai:
                assistant_editable(n)
            before = {}
            if value['kind'] == 'person':
                if n.metadata.fuente_inmutable:
                    raise HTTPException(409, 'Fuente inmutable: conservar la corrección separada')
                data, post = raw(n)
                match = re.match(r'\A---\r?\n.*?\r?\n---(?:\r?\n|$)', data.decode(), re.S)
                if not match:
                    raise HTTPException(409, 'Frontmatter inválido')
                value['fields'] = PersonFields.model_validate(value['fields']).model_dump(exclude_unset=True)
                no_credentials(value['fields'])
                for key, proposed in value['fields'].items():
                    if key not in FIELD_NAMES or (key in {'nombre', 'tipo'} and not proposed):
                        raise HTTPException(422, 'Campo inválido')
                before[n.path] = data.decode()
                history = history_start(body, n, 'assistant' if ai else 'manual', 'apply_person', before)
                post.metadata.update(value['fields'])
                if 'nombre' in value['fields']:
                    if value['fields']['nombre'] != n.title:
                        post.metadata['titulos_anteriores'] = list(dict.fromkeys([*n.metadata.titulos_anteriores, n.title]))
                    post.metadata['titulo'] = value['fields']['nombre']
                if 'funcion' in value['fields']:
                    post.metadata['rol'] = value['fields']['funcion']
                sources = post.metadata.get('datos_fuente') or {}
                for key in value['fields']:
                    sources[key] = [p for p in value['evidence'] if p['field'] == key]
                post.metadata.update({'datos_fuente': sources, 'origen': 'persona_asistente' if ai else 'persona_manual', 'modificada_en': now()})
                if not ai:
                    post.metadata.update({'revisado': True, 'ultima_revision': now(), 'estado': 'activo'})
                atomic_write(n.path, '---\n' + yaml.safe_dump(post.metadata, allow_unicode=True, sort_keys=False) + '---\n' + data.decode()[match.end():], replace=True)
            else:
                for item in value['links']:
                    target = node(item['target_id'], scope, ai)
                    require_revision(target, item['target_revision'])
                    key = relation_key(n.id, target.id, item['relation'])
                    relative = record_path('relations', key)
                    before[relative] = path_for(relative).read_text() if path_for(relative).exists() else None
                history = history_start(body, n, 'assistant' if ai else 'manual', 'apply_links', before)
                history['involved_ids'] = list(dict.fromkeys([n.id, *[item['target_id'] for item in value['links']]]))
                for item in value['links']:
                    key = relation_key(n.id, item['target_id'], item['relation'])
                    save('relations', key, {'id': key, 'source_id': n.id, 'target_id': item['target_id'], 'relation': item['relation'],
                         'active': item['action'] == 'add', 'origin': 'assistant' if ai else 'manual', 'created_at': now(),
                         'evidence': item['evidence'], 'reserved_segments': value.get('reserved_segments', [])})
            history_finish(history)
            value['state'] = 'applied'
            result = {'id': n.id, 'revision': revision(node(n.id, scope, ai)), 'history_id': history['id'], 'state': 'applied'}
        else:
            value['state'] = 'rejected'
            result = {'id': n.id, 'revision': revision(n), 'state': 'rejected'}
        value.update({'reviewed_at': now(), 'review_request_id': str(body.request_id), 'review_fingerprint': fingerprint, 'result': result})
        save('changes', value['id'], value)
        return remember(body, 'review:' + change_id, fingerprint, result)


def knowledge(body, scope, ai):
    no_credentials(body.model_dump(mode='json'))
    with transaction():
        result, fingerprint = replay(body, 'knowledge', scope, ai)
        if result:
            for source_id in body.source_ids:
                node(source_id, scope, ai)
            return {**result, 'created': False}
        sources = [node(i, scope, ai) for i in body.source_ids]
        if any(s.metadata.sensibilidad in {'privado', 'sensible', 'secreto'} for s in sources):
            raise HTTPException(409, 'Fuente reservada: usar sólo referencia neutral a segmento, sin copiar contenido')
        relative = f'07 Conocimiento/{"Recursos" if body.kind == "lectura" else "Contexto"}/{readable_slug(body.title)}-{body.request_id}.md'
        if path_for(relative).exists():
            post = frontmatter.load(str(path_for(relative)))
            if post.metadata.get('request_hash') != fingerprint:
                raise HTTPException(409, 'Borrador existente con otro contenido')
        else:
            sensitivity_order = {'normal': 0, 'interno': 1, 'privado': 2, 'sensible': 3, 'secreto': 4}
            sensitivity = max((s.metadata.sensibilidad for s in sources), key=lambda v: sensitivity_order.get(v, 4), default='normal')
            meta = {'titulo': body.title, 'tipo': 'recurso' if body.kind == 'lectura' else 'nota', 'estado': 'borrador',
                    'clase_conocimiento': body.kind, 'origen': 'borrador_conocimiento', 'revisado': False, 'ia_editar': False,
                    'ia_indexar': False, 'ia_permiso': 'allow' if all(is_ai_eligible(s) for s in sources) else 'deny', 'sensibilidad': sensitivity, 'creada_en': now(),
                    'fuentes_ids': body.source_ids, 'fuentes': [s.path for s in sources],
                    'segmentos_reservados': [{'source_reference': s.source_reference, 'start_seconds': s.start_seconds,
                                             'end_seconds': s.end_seconds, 'label': 'Segmento reservado; contenido no importado'} for s in body.reserved_segments],
                    'request_hash': fingerprint}
            history = history_start(body, path_to_id(relative), 'assistant' if ai else 'manual', 'create_knowledge', {relative: None})
            atomic_write(relative, serialize(meta, body.content))
            history_finish(history)
        return remember(body, 'knowledge', fingerprint, {'id': path_to_id(relative), 'path': relative, 'created': True, 'state': 'pending'})


def undo(history_id, body, scope, ai):
    if ai:
        raise HTTPException(403, 'La reversión requiere revisión manual')
    with transaction():
        entry = load('history', history_id)
        result, fingerprint = replay(body, 'undo:' + history_id, scope, ai)
        if result:
            return result
        n = node(entry['target_id'], scope)
        require_revision(n, body.revision)
        if entry.get('undone'):
            raise HTTPException(409, 'Cambio ya revertido')
        if set(entry['after']) != set(entry['before']):
            raise HTTPException(409, 'Operación incompleta; revisar antes de revertir')
        if n.metadata.fuente_inmutable and n.path in entry['before']:
            raise HTTPException(409, 'Fuente inmutable: no restaurar encima')
        for relative, expected in entry['after'].items():
            if not path_for(relative).exists() or sha256(path_for(relative).read_bytes()).hexdigest() != expected:
                raise HTTPException(409, 'Hay cambios posteriores; no se sobrescriben')
        for relative, previous in entry['before'].items():
            if previous is None:
                path_for(relative).unlink()
                if relative.endswith('.md'):
                    vault_index.remove_file(path_for(relative))
            elif isinstance(previous, dict):
                current = path_for(relative).read_bytes().decode()
                match = re.match(r'\A---\r?\n.*?\r?\n---(?:\r?\n|$)', current, re.S)
                if not match or sha256(current[match.end():].encode()).hexdigest() != previous['body_sha256']:
                    raise HTTPException(409, 'El cuerpo cambió; no se sobrescribe')
                atomic_write(relative, previous['header'] + current[match.end():], replace=True)
            elif relative.endswith('.md'):
                atomic_write(relative, previous, replace=True)
            else:
                save('relations', PurePosixPath(relative).stem, json.loads(previous))
        entry.update({'undone': True, 'undone_at': now()})
        save('history', history_id, entry)
        result = {'id': n.id, 'revision': revision(node(n.id, scope)) if path_for(n.path).exists() else None, 'state': 'reverted', 'history_id': history_id}
        return remember(body, 'undo:' + history_id, fingerprint, result)

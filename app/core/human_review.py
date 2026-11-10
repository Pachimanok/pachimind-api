"""Owner's human decision inbox. No automatic approvals or permission changes."""
from collections import Counter
from hashlib import sha256
from uuid import UUID
import re
from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field
from typing import Literal
from app.core import people, meeting_capture as capture
from app.core.vault_index import vault_index
from app.core.human_note_review import review_path
from app.models.people import ReviewCommand

Kind = Literal['links', 'person', 'meeting', 'note']


class Decision(BaseModel):
    model_config = ConfigDict(extra='forbid')
    request_id: UUID
    revision: str = Field(min_length=64, max_length=64)
    decision: Literal['approve', 'decline', 'answer']
    authorized_fields: list[str] = Field(default_factory=list, max_length=50)
    answer: str | None = Field(default=None, max_length=10000)


def title(n):
    return n.title.split('\n', 1)[0].split('|', 1)[0].strip()[:180]


def visible(n, seen=None):
    if not n or not people.visible(n, 'personal'):
        return False
    seen = set(seen or ())
    if n.id in seen:
        return True
    seen.add(n.id)
    return all(visible(vault_index.get(i), seen) for i in n.metadata.fuentes_ids)


def brief(n):
    return {'id': n.id, 'title': title(n), 'path': n.path, 'tipo': n.metadata.tipo}


def pending_note(n):
    return (visible(n) and (not n.metadata.revisado or n.metadata.estado in {'borrador', 'para_revisar', 'en_revision'}) and
            n.metadata.estado != 'archivado' and n.metadata.origen != 'propuesta_reunion')


def load(kind, item_id):
    if kind in {'links', 'person'}:
        value = people.load('changes', item_id)
        if value.get('kind') != kind or not people.proposal_visible(value, 'personal', False):
            raise HTTPException(404, 'Propuesta no disponible para esta cuenta')
        n = people.node(value['target_id'], 'personal')
        if not visible(n):raise HTTPException(404, 'Fuente no disponible')
        return n, value
    n = people.node(item_id, 'personal')
    if not visible(n):raise HTTPException(404, 'Nota no disponible')
    if kind == 'meeting':
        _, post = people.raw(n); value = post.metadata
        if value.get('origen') != 'propuesta_reunion':raise HTTPException(404, 'Propuesta no disponible')
        if not visible(vault_index.get(value.get('meeting_id'))) or not visible(vault_index.get(value.get('project_id'))):
            raise HTTPException(404, 'Fuente o proyecto no disponible')
        return n, value
    if n.metadata.origen == 'propuesta_reunion':raise HTTPException(404, 'Usá la revisión de propuesta')
    return n, None


def version(kind, n, value):
    if kind in {'links', 'person'}:return capture.digest(value)
    raw = sha256(capture.path_for(n.path).read_bytes()).hexdigest()
    if kind == 'note':
        p = review_path(capture.root(), n.id)
        return capture.digest({'file': raw, 'review': sha256(p.read_bytes()).hexdigest() if p.is_file() else None})
    return raw


def is_pending(kind, n, value):
    if kind in {'links', 'person'}:return value.get('state') == 'pending'
    if kind == 'meeting':return not value.get('review')
    return pending_note(n)


def row(kind, n, value, item_id=None):
    item_id = item_id or n.id
    labels = {'links': 'Vínculos', 'person': 'Ficha y aclaraciones', 'meeting': 'Propuesta de reunión', 'note': 'Revisión de nota'}
    return {'id': item_id, 'key': kind + ':' + item_id, 'kind': kind, 'category': labels[kind],
            'title': title(n), 'source': brief(n), 'state': 'pending',
            'revision': version(kind, n, value),
            'created_at': str((value or {}).get('created_at') or (value or {}).get('fecha') or n.last_modified.isoformat()),
            'summary': (str(len(value.get('links', []))) + ' vínculos para revisar' if kind == 'links' else
                        'Preguntas que necesitan tu respuesta' if kind == 'person' and not value.get('fields') else
                        str(len(value.get('fields', {}))) + ' campos propuestos' if kind == 'person' else
                        'Crear una actividad pendiente' if kind == 'meeting' and value.get('tipo') == 'accion' else
                        'Registrar una decisión' if kind == 'meeting' else
                        'Revisar el contenido; conservar texto, ubicación y permisos')}


def queue(kind='all', q='', page=1, per_page=20):
    items = []
    for value in people.records('changes'):
        if value.get('state') != 'pending' or value.get('kind') not in {'links', 'person'}:continue
        try:
            n, current = load(value['kind'], value['id'])
            items.append(row(value['kind'], n, current, value['id']))
        except HTTPException:continue
    for candidate in vault_index.all():
        if not visible(candidate):continue
        if candidate.metadata.origen == 'propuesta_reunion':
            try:
                n, value = load('meeting', candidate.id)
                if is_pending('meeting', n, value):items.append(row('meeting', n, value))
            except HTTPException:continue
        elif pending_note(candidate):items.append(row('note', candidate, None))
    counts = Counter(item['kind'] for item in items)
    counts = {k: counts[k] for k in ['links', 'person', 'meeting', 'note']}
    selected = [i for i in items if (kind == 'all' or i['kind'] == kind) and
                (not q or people.canonical(q) in people.canonical(i['title'] + ' ' + i['source']['path']))]
    selected.sort(key=lambda i: (i['created_at'], i['key']), reverse=True)
    start = (page - 1) * per_page
    return {'total': len(selected), 'total_pending': len(items), 'counts': counts, 'page': page,
            'per_page': per_page, 'results': selected[start:start + per_page]}


def validation(kind, n, value):
    try:
        if kind in {'links', 'person'}:
            people.require_revision(n, value['base_revision'])
            if kind == 'person' and not value.get('fields'):
                return {'ok': False, 'reason': 'Necesita una respuesta; una pregunta no se aprueba como un hecho.'}
            if kind == 'person' and n.metadata.fuente_inmutable:
                return {'ok': False, 'reason': 'La fuente es inmutable. Conservá la corrección separada.'}
            people.safe_evidence(value.get('evidence', []), 'personal', False, expected=True)
            for link in value.get('links', []):
                target = people.node(link['target_id'], 'personal')
                people.require_revision(target, link['target_revision'])
        elif kind == 'meeting':
            _, _, content = capture.source_for(value['project_id'], value['meeting_id'])
            if not value.get('evidencia') or value['evidencia'] not in content:
                raise HTTPException(409, 'La propuesta perdió su evidencia. Necesita corrección antes de aprobar.')
        elif kind == 'note' and n.metadata.ia_permiso == 'summary_only':
            return {'ok': False, 'reason': 'Esta nota permite sólo un resumen. No se puede aprobar el contenido completo desde esta vista.'}
        return {'ok': True, 'reason': 'Revisiones comprobadas. Se validarán otra vez al aprobar.'}
    except HTTPException as exc:
        return {'ok': False, 'reason': str(exc.detail)}


def detail(kind, item_id):
    n, value = load(kind, item_id)
    if not is_pending(kind, n, value):raise HTTPException(409, 'Este pendiente ya fue resuelto. Actualizá la lista.')
    result = row(kind, n, value, item_id)
    result['validation'] = validation(kind, n, value)
    if kind in {'links', 'person'}:
        result['evidence'] = value.get('evidence', [])
        result['questions'] = value.get('questions', [])
        result['fields'] = value.get('fields', {})
        result['links'] = [{**link, 'target': brief(vault_index.get(link['target_id']))} for link in value.get('links', [])]
        result['authorized_fields'] = ['relations'] if kind == 'links' else list(value.get('fields', {}))
        result['effect'] = ('Aplicar únicamente los vínculos mostrados, sin reescribir las notas.' if kind == 'links' else
                            'Aplicar sólo los campos mostrados; conservar el cuerpo original de la ficha.')
        if kind == 'person' and not value.get('fields'):result['effect'] = 'Guardar tu aclaración separada; no convertirla en campos ni tareas.'
    elif kind == 'meeting':
        result['proposal'] = {k: value.get(k) for k in ['tipo', 'detalle', 'evidencia', 'responsable', 'vencimiento']}
        result['authorized_fields'] = ['proposal']
        result['effect'] = ('Crear una actividad pendiente, sin inventar responsable ni fecha.' if value.get('tipo') == 'accion' else
                            'Registrar esta decisión con su evidencia y conservar la reunión original.')
    else:
        result['content'] = n.content if n.metadata.ia_permiso != 'summary_only' else None
        result['excerpt'] = n.content_text[:400] if result['content'] is None else None
        result['authorized_fields'] = ['review']
        result['metadata'] = {k: getattr(n.metadata, k) for k in ['estado', 'revisado', 'ia_permiso', 'ia_indexar', 'ia_editar', 'fuente_inmutable']}
        result['effect'] = 'Marcar la nota revisada y, si es borrador, activa. Conservar texto, ubicación y permisos.'
        result['decline_effect'] = 'Archivar en la vista, conservando íntegro el original y su historial.'
    return result


def _note_decision(n, command):
    with capture.transaction():
        n = people.node(n.id, 'personal')
        path = review_path(capture.root(), n.id)
        current = None
        if path.is_file():
            import json
            current = json.loads(path.read_text())
        if current and current.get('request_id') == str(command.request_id):
            if current.get('source_sha256') != sha256(capture.path_for(n.path).read_bytes()).hexdigest():
                raise HTTPException(409, 'La fuente cambió después de esta revisión; necesita una decisión nueva.')
            vault_index.rebuild_file(capture.path_for(n.path))
            return {'id': n.id, 'state': 'approved' if command.decision == 'approve' else 'declined'}
        if version('note', n, None) != command.revision or not pending_note(n):
            raise HTTPException(409, 'La nota cambió o ya fue revisada. Releela antes de decidir.')
        raw = capture.path_for(n.path).read_bytes()
        record = {'note_id': n.id, 'source_sha256': sha256(raw).hexdigest(), 'decision': command.decision,
                  'reviewed_by': 'owner', 'reviewed_at': people.now(), 'request_id': str(command.request_id)}
        people.save('human_history', str(command.request_id), {**record, 'previous_review': current})
        people.save('human_notes', sha256(n.id.encode()).hexdigest(), record)
        vault_index.rebuild_file(capture.path_for(n.path))
        return {'id': n.id, 'state': 'approved' if command.decision == 'approve' else 'declined'}


def decide(kind, item_id, command):
    n, value = load(kind, item_id)
    fingerprint = capture.digest({'kind': kind, 'id': item_id, **command.model_dump(mode='json')})
    journal_path = capture.path_for(people.record_path('human_requests', str(command.request_id)))
    with capture.transaction():
        if journal_path.exists():
            previous = people.load('human_requests', str(command.request_id))
            if previous['fingerprint'] != fingerprint:raise HTTPException(409, 'Este identificador ya se usó para otra decisión.')
            if previous.get('result'):return previous['result']
        else:
            n, value = load(kind, item_id)
            if not is_pending(kind, n, value) or version(kind, n, value) != command.revision:
                raise HTTPException(409, 'El pendiente cambió o ya fue resuelto. Releé antes de decidir.')
            required = ['relations'] if kind == 'links' else list(value.get('fields', {})) if kind == 'person' else ['proposal'] if kind == 'meeting' else ['review']
            if command.decision == 'approve':
                if not required or set(command.authorized_fields) != set(required):raise HTTPException(422, 'Autorizá todos y sólo los cambios mostrados.')
                check = validation(kind, n, value)
                if not check['ok']:raise HTTPException(409, check['reason'])
            elif command.authorized_fields:raise HTTPException(422, 'Declinar o responder no autoriza aplicar campos.')
            if command.decision == 'answer':
                if kind != 'person' or value.get('fields') or not value.get('questions') or not (command.answer or '').strip():
                    raise HTTPException(422, 'Esta opción sólo resuelve preguntas sin campos propuestos.')
                people.no_credentials({'answer': command.answer})
            elif command.answer:raise HTTPException(422, 'La aclaración no se aplica como campos ni como una aprobación.')
            people.save('human_requests', str(command.request_id), {'fingerprint': fingerprint, 'kind': kind, 'item_id': item_id, 'state': 'prepared'})
    # Native operations take the process-shared lock themselves; never nest it.
    if kind in {'links', 'person'} and command.decision != 'answer':
        result = people.review(item_id, ReviewCommand(request_id=command.request_id, revision=value['base_revision'],
                      action='apply' if command.decision == 'approve' else 'reject', authorized_fields=command.authorized_fields,
                      expected_kind=kind), 'personal', False)
        state = 'approved' if result['state'] == 'applied' else 'declined'
    elif kind == 'meeting':
        result = capture.review_proposal(value['project_id'], value['meeting_id'], item_id,
                   'approve' if command.decision == 'approve' else 'discard',
                   expected_revision=command.revision, review_request_id=str(command.request_id))
        state = 'approved' if result['review'] == 'approve' else 'declined'
    elif kind == 'note':
        result = _note_decision(n, command); state = result['state']
    else:
        with capture.transaction():
            fresh = people.load('changes', item_id)
            if fresh.get('state') != 'answered' and version(kind, n, fresh) != command.revision:
                raise HTTPException(409, 'La pregunta cambió antes de guardar la respuesta.')
            if fresh.get('state') == 'answered' and fresh.get('human_request_id') != str(command.request_id):
                raise HTTPException(409, 'La pregunta ya fue respondida.')
            people.save('human_answers', str(command.request_id), {'change_id': item_id, 'note_id': n.id,
                        'answer': command.answer.strip(), 'at': people.now(), 'author': 'owner'})
            fresh.update(state='answered', human_request_id=str(command.request_id), reviewed_at=people.now())
            people.save('changes', item_id, fresh)
        result = {'id': n.id}; state = 'answered'
    if kind in {'links', 'person'}:
        expected_state = 'answered' if command.decision == 'answer' else 'applied' if state == 'approved' else 'rejected'
        if people.load('changes', item_id).get('state') != expected_state:
            raise HTTPException(409, 'La decisión se guardó pero su verificación quedó incompleta. Comprobá el resultado antes de reintentar.')
    elif kind == 'meeting':
        _, post = people.raw(people.node(item_id, 'personal'))
        if post.metadata.get('review') != ('approve' if state == 'approved' else 'discard'):
            raise HTTPException(409, 'El resultado de la propuesta necesita verificación.')
    else:
        current = people.node(item_id, 'personal')
        if not current.metadata.revisado or (state == 'declined' and current.metadata.estado != 'archivado'):
            raise HTTPException(409, 'El estado de revisión necesita verificación.')
    receipt = {'id': item_id, 'kind': kind, 'state': state, 'request_id': str(command.request_id),
               'verified': True, 'result': result}
    with capture.transaction():
        people.save('human_requests', str(command.request_id), {'fingerprint': fingerprint, 'kind': kind, 'item_id': item_id,
                    'state': 'complete', 'result': receipt})
    return receipt


def request_result(request_id):
    value = people.load('human_requests', request_id)
    load(value['kind'], value['item_id'])  # Recheck the caller's visibility before returning a receipt.
    return value.get('result') or {'request_id': request_id, 'state': 'prepared', 'verified': False}

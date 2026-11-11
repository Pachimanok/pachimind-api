"""Owner's human decision inbox. No automatic approvals or permission changes."""
from collections import Counter
from datetime import date
from hashlib import sha256
from uuid import UUID
import re
from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field
from typing import Literal
from app.core import people, meeting_capture as capture
from app.core.vault_index import vault_index
from app.core.id_utils import path_to_id
from app.core.human_note_review import review_path
from app.models.people import ReviewCommand, LinkCommand

Kind = Literal['links', 'person', 'meeting', 'note']
OPTIONAL_VISIBILITY_KEY = sha256(b'owner-optional-review-visibility-v1').hexdigest()


class RefreshLinks(BaseModel):
    model_config = ConfigDict(extra='forbid')
    request_id: UUID
    revision: str = Field(pattern=r'^[a-f0-9]{64}$')
    current_revision: str = Field(pattern=r'^[a-f0-9]{64}$')


class OptionalVisibility(BaseModel):
    model_config = ConfigDict(extra='forbid')
    request_id: UUID
    action: Literal['hide', 'restore']
    q: str = Field(default='', max_length=200)
    revision: str = Field(pattern=r'^[a-f0-9]{64}$')


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


def meeting_context(value):
    """Explicit provenance only; no bodies in the queue or inferred dates/relations."""
    project = people.node(value['project_id'], 'personal')
    source = people.node(value['meeting_id'], 'personal')
    if not all(visible(n) for n in [project, source]):
        raise HTTPException(404, 'Fuente o proyecto no disponible')
    raw_date = source.metadata.fecha or ''
    try:
        meeting_date = date.fromisoformat(raw_date).isoformat() if re.fullmatch(r'\d{4}-\d{2}-\d{2}', raw_date) else None
    except ValueError:
        meeting_date = None
    return {'project': brief(project), 'source': brief(source), 'meeting_date': meeting_date,
            'proposal_type': value.get('tipo')}


def pending_note(n):
    return (visible(n) and (not n.metadata.revisado or n.metadata.estado in {'borrador', 'para_revisar', 'en_revision'}) and
            n.metadata.estado != 'archivado' and n.metadata.origen != 'propuesta_reunion')


def load(kind, item_id):
    if kind in {'links', 'person'}:
        value = people.load('changes', item_id)
        if value.get('kind') != kind or not people.proposal_visible(value, 'personal', False):
            raise HTTPException(404, 'Propuesta no disponible para esta cuenta')
        n = people.node(value['target_id'], 'personal')
        if not visible(n) or not all(visible(vault_index.get(i)) for i in
                [*[e['source_id'] for e in value.get('evidence', [])], *[l['target_id'] for l in value.get('links', [])]]):
            raise HTTPException(404, 'Fuente o destino no disponible')
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
            **({'context': meeting_context(value)} if kind == 'meeting' else {}),
            'revision': version(kind, n, value),
            'created_at': str((value or {}).get('created_at') or (value or {}).get('fecha') or n.last_modified.isoformat()),
            'summary': (str(len(value.get('links', []))) + ' vínculos para revisar' if kind == 'links' else
                        'Preguntas que necesitan tu respuesta' if kind == 'person' and not value.get('fields') else
                        str(len(value.get('fields', {}))) + ' campos propuestos' if kind == 'person' else
                        'Crear una actividad pendiente' if kind == 'meeting' and value.get('tipo') == 'accion' else
                        'Registrar una decisión' if kind == 'meeting' else
                        'Revisar el contenido; conservar texto, ubicación y permisos')}


def optional_preferences():
    path = capture.path_for(people.record_path('optional_visibility', OPTIONAL_VISIBILITY_KEY))
    return people.load('optional_visibility', OPTIONAL_VISIBILITY_KEY) if path.exists() else {'generation': 0, 'notes': {}, 'receipts': {}}


def optional_hidden(n, preferences):
    return preferences.get('notes', {}).get(n.id, {}).get('revision') == version('note', n, None)


def optional_snapshot(notes, preferences, q, hidden):
    selected = [n for n in notes if optional_hidden(n, preferences) == hidden and
                (not q or people.canonical(q) in people.canonical(title(n) + ' ' + n.path))]
    digest = capture.digest({'generation': preferences['generation'], 'query': q, 'hidden': hidden,
                             'notes': sorted((n.id, version('note', n, None)) for n in selected)})
    return selected, digest


def queue(kind='all', q='', page=1, per_page=20, hidden=False):
    items = []; notes = []
    preferences = optional_preferences()
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
        elif pending_note(candidate):notes.append(candidate)
    hidden_count = sum(optional_hidden(n, preferences) for n in notes)
    counts = Counter(item['kind'] for item in items)
    counts = {k: counts[k] for k in ['links', 'person', 'meeting', 'note']}
    counts['note'] = len(notes) - hidden_count
    selected = [i for i in items if (kind == 'all' or i['kind'] == kind) and
                (not q or people.canonical(q) in people.canonical(i['title'] + ' ' + i['source']['path'] + ' ' +
                    ' '.join(i.get('context', {}).get(k, {}).get('title', '') for k in ['project', 'source'])))]
    optional = None
    if kind == 'note':
        selected_notes, digest = optional_snapshot(notes, preferences, q, hidden)
        selected = [row('note', n, None) for n in selected_notes]
        optional = {'hidden': hidden, 'hidden_count': hidden_count, 'visible_count': counts['note'],
                    'selection_count': len(selected), 'selection_revision': digest, 'query': q}
    selected.sort(key=lambda i: (i['created_at'], i['key']), reverse=True)
    start = (page - 1) * per_page
    return {'total': len(selected), 'total_pending': sum(v for k, v in counts.items() if k != 'note'),
            'counts': counts, 'page': page, 'per_page': per_page, 'results': selected[start:start + per_page],
            'optional': optional}


def optional_visibility(command):
    """Dismiss/restore optional notices; never review, archive or rewrite notes."""
    fingerprint = capture.digest(command.model_dump(mode='json'))
    key = str(command.request_id)
    with capture.transaction():
        preferences = optional_preferences()
        previous = preferences.get('receipts', {}).get(key)
        if previous:
            if previous['fingerprint'] != fingerprint:raise HTTPException(409, 'Este identificador ya corresponde a otra operación.')
            return previous['result']
        # Refresh only indexed notes so external edits cannot be hidden by an old snapshot.
        notes = []
        for candidate in vault_index.all():
            if not pending_note(candidate):continue
            try:n = people.node(candidate.id, 'personal')
            except HTTPException:continue
            if pending_note(n):notes.append(n)
        selected, revision = optional_snapshot(notes, preferences, command.q, command.action == 'restore')
        if revision != command.revision:
            raise HTTPException(409, 'La lista cambió. Aplicá la búsqueda o actualizá antes de limpiar los avisos.')
        for n in selected:
            if command.action == 'hide':preferences['notes'][n.id] = {'revision': version('note', n, None), 'request_id': key}
            else:preferences['notes'].pop(n.id, None)
        result = {'request_id': key, 'action': command.action, 'affected': len(selected), 'verified': True}
        preferences['generation'] += 1
        preferences.setdefault('receipts', {})[key] = {'fingerprint': fingerprint, 'result': result}
        # One atomic sidecar commits both visibility preferences and idempotent receipt.
        people.save('optional_visibility', OPTIONAL_VISIBILITY_KEY, preferences)
        return result


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
        return {'ok': False, 'reason': str(exc.detail), 'code': 'revision_conflict' if exc.status_code == 409 else 'invalid_proposal'}


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
        if kind == 'links' and not result['validation']['ok']:
            result['refresh'] = link_refresh_preview(n, value)
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


def link_refresh_preview(n, value):
    """Read-only snapshot: same intent, current nodes, valid literal evidence."""
    try:
        source_revision = people.revision(n)
        links = []
        changed_targets = []
        for old in value.get('links', []):
            target = people.node(old['target_id'], 'personal')
            if not visible(target):raise HTTPException(404, 'Destino no disponible')
            current = people.revision(target)
            if current != old['target_revision']:changed_targets.append(brief(target))
            proof = old.get('evidence')
            links.append({**{k: old[k] for k in ('target_id', 'relation', 'action')},
                          'target_revision': current,
                          'evidence': {k: proof[k] for k in ('field', 'source_id', 'quote')} if proof else None})
        command = LinkCommand(request_id=value['id'], source_id=n.id, revision=source_revision,
                              links=links, reserved_segments=value.get('reserved_segments', []))
        validated = people.validate_links(n, command.links, 'personal', False)
        source_changed = source_revision != value['base_revision']
        if not source_changed and not changed_targets:
            # Never offer a refresh for invalid evidence or unrelated validation failures.
            raise HTTPException(409, 'La propuesta no necesita actualizar revisiones. Revisá el motivo indicado.')
        fingerprint = capture.digest({'proposal': version('links', n, value), 'source': source_revision,
                                      'links': validated, 'reserved_segments': value.get('reserved_segments', [])})
        return {'available': True, 'revision': fingerprint, 'source_changed': source_changed,
                'changed_targets': changed_targets,
                'reason': 'Preparar los mismos vínculos con las revisiones actuales. Todavía no se aplicará ninguno.'}
    except HTTPException as exc:
        return {'available': False, 'reason': str(exc.detail)}


def refresh_links(item_id, command, ai=False):
    """Replace a pending proposal on explicit request; never apply its links."""
    new_id = str(command.request_id)
    if new_id == item_id:raise HTTPException(422, 'La propuesta nueva necesita un identificador distinto.')
    fingerprint = capture.digest({'item_id': item_id, **command.model_dump(mode='json')})
    with capture.transaction():
        n, old = load('links', item_id)
        if ai and not people.proposal_visible(old, 'personal', True):
            raise HTTPException(404, 'Propuesta no disponible para IA')
        existing_path = capture.path_for(people.record_path('changes', new_id))
        new = people.load('changes', new_id) if existing_path.exists() else None
        if new:
            if new.get('refresh_fingerprint') != fingerprint or new.get('previous_proposal_id') != item_id:
                raise HTTPException(409, 'Este identificador pertenece a otra propuesta.')
            if old.get('state') == 'superseded' and old.get('superseded_by') == new_id:
                return {'id': new_id, 'kind': 'links', 'state': new['state'], 'replaces': item_id, 'verified': True}
        if old.get('state') != 'pending' or version('links', n, old) != command.revision:
            raise HTTPException(409, 'La propuesta cambió o ya fue resuelta. Releela antes de actualizar.')
        preview = link_refresh_preview(n, old)
        if not preview['available']:raise HTTPException(409, preview['reason'])
        if preview['revision'] != command.current_revision:
            raise HTTPException(409, 'La fuente o un destino volvió a cambiar. Comprobá las revisiones de nuevo.')
        links = []
        for item in old['links']:
            proof = item.get('evidence')
            links.append({**{k: item[k] for k in ('target_id', 'relation', 'action')},
                          'target_revision': people.revision(people.node(item['target_id'], 'personal')),
                          'evidence': {k: proof[k] for k in ('field', 'source_id', 'quote')} if proof else None})
        body = LinkCommand(request_id=command.request_id, source_id=n.id, revision=people.revision(n),
                           links=links, reserved_segments=old.get('reserved_segments', []))
        validated = people.validate_links(n, body.links, 'personal', ai)
        value = new or {'id': new_id, 'kind': 'links', 'target_id': n.id, 'base_revision': body.revision,
                       'state': 'pending', 'origin': old.get('origin', 'manual'), 'created_at': people.now(),
                       'links': validated, 'evidence': [i['evidence'] for i in validated if i['evidence']],
                       'reserved_segments': old.get('reserved_segments', []),
                       'fingerprint': capture.digest({'kind': 'links', 'payload': body.model_dump(mode='json')}),
                       'previous_proposal_id': item_id, 'refresh_fingerprint': fingerprint, 'refreshed_by': 'assistant' if ai else 'owner'}
        # Two atomic records under the shared lock. A retry completes the pair if interrupted.
        people.save('changes', new_id, value)
        old.update(state='superseded', superseded_by=new_id, superseded_at=people.now())
        people.save('changes', item_id, old)
        return {'id': new_id, 'kind': 'links', 'state': value['state'], 'replaces': item_id, 'verified': True}


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
            if previous.get('result'):return present_receipt(previous['result'])
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
    return present_receipt(receipt)


def meeting_destination(note):
    """Resolve a real approved record and its visible project/source, never create one."""
    try:
        n = people.node(note.id, 'personal')
        if not visible(n) or n.metadata.origen != 'revision_reunion' or n.metadata.tipo not in {'accion', 'decision'}:return None
        _, post = people.raw(n); meta = post.metadata
        request_id = str(UUID(str(meta.get('request_id'))))
        proposal = people.node(path_to_id(capture.proposal_path(request_id)), 'personal')
        _, proposed = people.raw(proposal); old = proposed.metadata
        if (old.get('review') != 'approve' or old.get('origen') != 'propuesta_reunion' or
                old.get('tipo') != n.metadata.tipo or old.get('approved_path') != n.path or
                old.get('project_id') != meta.get('project_id') or old.get('meeting_id') != meta.get('meeting_id')):return None
        project = people.node(meta['project_id'], 'personal'); source = people.node(meta['meeting_id'], 'personal')
        if not all(visible(x) for x in [proposal, project, source]):return None
        from app.core.todo import ACTIVE
        todo = n.metadata.tipo == 'accion' and n.metadata.estado in ACTIVE and not n.metadata.fuente_inmutable
        return {**brief(n), 'view': 'todo' if todo else 'note', 'estado': n.metadata.estado,
                'revision': people.revision(n), 'area': n.metadata.area or project.metadata.area,
                'project': brief(project), 'source': brief(source), 'proposal_id': proposal.id,
                'context': meeting_context(meta),
                'approved_at': str(old.get('reviewed_at') or ''),
                'responsable': str(meta['responsable']) if meta.get('responsable') else None,
                'vencimiento': str(meta['vencimiento']) if meta.get('vencimiento') else None}
    except (HTTPException, ValueError, TypeError, KeyError):return None


def present_receipt(receipt):
    if receipt.get('kind') != 'meeting' or receipt.get('state') != 'approved':return receipt
    result = dict(receipt.get('result') or {})
    path = result.get('approved_path')
    note = vault_index.get(path_to_id(path)) if isinstance(path, str) else None
    destination = meeting_destination(note) if note else None
    if not destination:result.pop('approved_path', None)
    return {**receipt, 'result': result, 'destination': destination}


def meeting_results(kind='all', q='', page=1, per_page=20):
    results = []
    for n in vault_index.all():
        if n.metadata.origen != 'revision_reunion' or n.metadata.tipo not in {'accion', 'decision'}:continue
        if kind != 'all' and n.metadata.tipo != kind:continue
        destination = meeting_destination(n)
        if not destination:continue
        if q and people.canonical(q) not in people.canonical(destination['title'] + ' ' + destination['project']['title'] + ' ' + destination['source']['title']):continue
        results.append(destination)
    results.sort(key=lambda n: (n['approved_at'], n['id']), reverse=True)
    start = (page - 1) * per_page
    return {'total': len(results), 'page': page, 'per_page': per_page, 'results': results[start:start + per_page]}


def request_result(request_id):
    value = people.load('human_requests', request_id)
    load(value['kind'], value['item_id'])  # Recheck the caller's visibility before returning a receipt.
    return present_receipt(value['result']) if value.get('result') else {'request_id': request_id, 'state': 'prepared', 'verified': False}

"""Proposals are separate from originals; only the owner confirms processing."""
from hashlib import sha256
from typing import Literal
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field
from fastapi import HTTPException
from app.core import people, meeting_capture as capture
from app.core.vault_index import vault_index
from app.middleware.permissions import is_ai_eligible

class Classification(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    title: str = Field(min_length=1, max_length=200)
    tipo: Literal['nota', 'recurso', 'idea', 'registro'] = 'nota'
    area: Literal['Laboral', 'Personal', 'Familia', 'Amigos', 'Apostolado']
    tags: list[str] = Field(default_factory=list, max_length=30)
    content: str | None = Field(default=None, max_length=50000)
    comment: str = Field(default='', max_length=2000)

class Propose(BaseModel):
    model_config = ConfigDict(extra='forbid')
    request_id: UUID
    revision: str = Field(pattern=r'^[a-f0-9]{64}$')
    classification: Classification

class Decision(BaseModel):
    model_config = ConfigDict(extra='forbid')
    request_id: UUID
    revision: str = Field(pattern=r'^[a-f0-9]{64}$')
    decision: Literal['approve', 'decline']
    confirmed: bool = False
    classification: Classification | None = None


def key(note_id): return sha256(note_id.encode()).hexdigest()

def record(note_id):
    p = capture.path_for(people.record_path('inbox_classifications', key(note_id)))
    if p.is_symlink(): raise HTTPException(409, 'Registro de clasificación inválido')
    return people.load('inbox_classifications', key(note_id)) if p.exists() else None


def view(n, value):
    return {'id': n.id, 'title': n.title, 'revision': capture.digest({'source': people.revision(n), 'proposal': value}),
            'proposal': value, 'source_revision': people.revision(n),
            'source_changed': bool(value and value['source_revision'] != people.revision(n)),
            'effect': 'La clasificación se revisa por separado. Confirmarla guarda una nota derivada y retira el original del Inbox sin reescribirlo. No crea tareas, decisiones ni amplía permisos.'}


def get(note_id, scope, ai):
    n = people.node(note_id, scope, ai)
    return view(n, record(note_id))


def propose(note_id, body, scope, ai):
    fingerprint = capture.digest({'note_id': note_id, **body.model_dump(mode='json')})
    with capture.transaction():
        n = people.node(note_id, scope, ai)
        # Eligibility is checked again for retries, including revoked access.
        if not is_ai_eligible(n) or n.metadata.segmentos_reservados:
            raise HTTPException(403, 'La nota no permite preparar una clasificación por IA')
        operation = str(body.request_id)
        receipt = capture.path_for(people.record_path('inbox_classification_requests', operation))
        old = record(note_id)
        if receipt.exists():
            previous = people.load('inbox_classification_requests', operation)
            if previous['fingerprint'] != fingerprint: raise HTTPException(409, 'Identificador utilizado para otra clasificación')
            if not old or old['request_id'] != operation: raise HTTPException(409, 'Otra propuesta reemplazó esta clasificación')
            return view(n, old)
        if n.metadata.estado != 'borrador': raise HTTPException(409, 'La nota ya no está pendiente en Inbox')
        people.require_revision(n, body.revision)
        if old and old['state'] == 'pending' and old['request_id'] != operation and old['source_revision'] == people.revision(n):
            raise HTTPException(409, 'Ya hay una clasificación pendiente; revisala antes de reemplazarla')
        raw, _ = people.raw(n)
        value = {'request_id': operation, 'state': 'pending', 'note_id': n.id,
                 'source_sha256': sha256(raw).hexdigest(), 'source_revision': body.revision,
                 'classification': body.classification.model_dump(mode='json'), 'created_at': people.now()}
        if old and old['request_id'] == operation:
            if old.get('fingerprint') != fingerprint: raise HTTPException(409, 'Identificador utilizado para otra clasificación')
            value = old  # Recover a proposal saved before its receipt.
        else:
            if old: people.save('inbox_classification_history', old['request_id'], old)
            value['fingerprint'] = fingerprint
            people.save('inbox_classifications', key(note_id), value)
        people.save('inbox_classification_requests', operation, {'fingerprint': fingerprint})
        return view(n, value)


def decide(note_id, body):
    fingerprint = capture.digest({'note_id': note_id, **body.model_dump(mode='json')})
    operation = str(body.request_id)
    with capture.transaction():
        n = people.node(note_id, 'personal')
        value = record(note_id)
        if not value: raise HTTPException(404, 'No hay una clasificación propuesta')
        receipt = capture.path_for(people.record_path('inbox_classification_decisions', operation))
        if receipt.exists():
            previous = people.load('inbox_classification_decisions', operation)
            if previous['fingerprint'] != fingerprint: raise HTTPException(409, 'Identificador utilizado para otra decisión')
            return previous['result']
        if value.get('decision_request') == operation:
            if value.get('decision_fingerprint') != fingerprint: raise HTTPException(409, 'Identificador utilizado para otra decisión')
            result = value['result']  # Recover approval persisted before its receipt.
        else:
            state = view(n, value)
            if value['state'] != 'pending' or state['revision'] != body.revision:
                raise HTTPException(409, 'La propuesta cambió. Volvé a leer antes de decidir')
            if not body.confirmed: raise HTTPException(422, 'Confirmá explícitamente esta clasificación')
            result = {'id': n.id, 'state': 'declined', 'request_id': operation, 'verified': True}
            if body.decision == 'approve':
                if state['source_changed'] or n.metadata.estado != 'borrador':
                    raise HTTPException(409, 'La nota cambió. Prepará una clasificación actualizada')
                if not is_ai_eligible(n) or n.metadata.segmentos_reservados:
                    raise HTTPException(409, 'El acceso de la nota cambió; revisalo antes de clasificar')
                c = body.classification or Classification.model_validate(value['classification'])
                folders = {'nota': '07 Conocimiento/Contexto', 'recurso': '07 Conocimiento/Recursos',
                           'idea': '07 Conocimiento/Ideas', 'registro': '06 Reuniones y Registros'}
                path = folders[c.tipo] + '/clasificacion-' + value['request_id'] + '.md'
                meta = {'titulo': c.title, 'tipo': c.tipo, 'area': c.area, 'tags': c.tags,
                        'estado': 'activo', 'revisado': True, 'ia_permiso': n.metadata.ia_permiso,
                        'ia_indexar': n.metadata.ia_indexar, 'ia_editar': False,
                        'sensibilidad': n.metadata.sensibilidad, 'fuentes_ids': [n.id],
                        'origen': 'clasificacion_inbox_confirmada', 'request_id': operation}
                text = capture.serialize(meta, c.content if c.content is not None else n.content)
                destination = capture.path_for(path)
                if destination.exists():
                    if destination.read_text() != text: raise HTTPException(409, 'Ya existe una nota derivada distinta; requiere revisión')
                else: capture.atomic_write(path, text)
                result.update(state='approved', derived_id=people.path_to_id(path), path=path)
            value = {**value, 'state': result['state'], 'decision_request': operation,
                     'decision_fingerprint': fingerprint, 'reviewed_at': people.now(), 'result': result}
            people.save('inbox_classifications', key(note_id), value)
        people.save('inbox_classification_decisions', operation, {'fingerprint': fingerprint, 'result': result})
        if result.get('path'): vault_index.rebuild_file(capture.path_for(result['path']))
        vault_index.rebuild_file(capture.path_for(n.path))
        return result


def summary(n):
    value = record(n.id)
    if not value: return None
    return {'state': value['state'], 'source_changed': value['source_revision'] != people.revision(n)}

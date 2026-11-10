"""Read-only association audit using explicit, permission-filtered relationships."""
from collections import defaultdict

from fastapi import HTTPException
from app.core.people import canonical, relation_rows
from app.middleware.permissions import is_reserved_path

GENERAL_TYPES = {'proyecto', 'persona', 'organizacion', 'cliente'}
AREA_LABELS = {'Laboral': 'Trabajo', 'Apostólico': 'Apostolado'}


def declared_ambitos(note):
    values = [*note.metadata.ambitos]
    if note.metadata.area:
        values.append(note.metadata.area)
    return sorted({AREA_LABELS.get(value, value) for value in values if value})


class AssociationGraph:
    def __init__(self, scope, ai=False):
        self.rows, self.issues, self.notes = relation_rows(scope, ai)
        self.incoming, self.outgoing = defaultdict(list), defaultdict(list)
        self.neighbors = defaultdict(set)
        for row in self.rows:
            source, target = row['source_id'], row['target_id']
            if source == target:
                continue
            self.outgoing[source].append(row)
            self.incoming[target].append(row)
            self.neighbors[source].add(target)
            self.neighbors[target].add(source)
        self.ai = ai

    def brief(self, note_id):
        n = self.notes[note_id]
        return {'id': n.id, 'title': n.title, 'path': n.path, 'tipo': n.metadata.tipo}

    def general_nodes(self, note_id):
        """At most two explicit hops. A connection is not membership or identity."""
        direct = self.neighbors[note_id]
        found = {target: {**self.brief(target), 'depth': 1, 'via': None}
                 for target in direct if self.notes[target].metadata.tipo in GENERAL_TYPES}
        for via in sorted(direct):
            for target in self.neighbors[via] - direct - {note_id}:
                if self.notes[target].metadata.tipo in GENERAL_TYPES and target not in found:
                    found[target] = {**self.brief(target), 'depth': 2, 'via': self.brief(via)}
        return sorted(found.values(), key=lambda n: (n['depth'], canonical(n['title']), n['id']))

    def entry(self, note_id, detail=False):
        n = self.notes[note_id]
        general = self.general_nodes(note_id)
        issue = self.issues[note_id]
        broken = sorted(set(v for v in issue['broken'] if not is_reserved_path(v)))
        ambiguous = sorted(set(v for v in issue['ambiguous'] if not is_reserved_path(v)))
        result = {**self.brief(note_id), 'estado': n.metadata.estado,
                  'ambitos': declared_ambitos(n), 'incoming_count': len(self.incoming[note_id]),
                  'outgoing_count': len(self.outgoing[note_id]),
                  'connection_count': len(self.neighbors[note_id]),
                  'orphan': not self.neighbors[note_id],
                  'is_general_node': n.metadata.tipo in GENERAL_TYPES,
                  'no_general_node': n.metadata.tipo not in GENERAL_TYPES and not general,
                  'general_nodes': general[:100 if detail else 6], 'general_node_count': len(general),
                  'broken_links': broken, 'ambiguous_links': ambiguous,
                  'unresolved_count': len(broken) + len(ambiguous)}
        if detail:
            connections = []
            for direction, rows in [('entrante', self.incoming[note_id]), ('saliente', self.outgoing[note_id])]:
                for row in rows:
                    other = row['source_id'] if direction == 'entrante' else row['target_id']
                    connections.append({'direction': direction, 'relation': row['relation'],
                                        'origin': row['origin'], 'node': self.brief(other)})
            result['connections'] = sorted(connections, key=lambda r: (r['direction'], canonical(r['node']['title'])))
        return result

    def audit(self, view='orphans', q='', ambito='', page=1, per_page=20):
        entries = [self.entry(note_id) for note_id in self.notes]
        summary = {'notes': len(entries), 'orphans': sum(n['orphan'] for n in entries),
                   'no_general_node': sum(n['no_general_node'] for n in entries),
                   'unresolved': sum(bool(n['unresolved_count']) for n in entries),
                   'no_ambito': sum(not n['ambitos'] for n in entries)}
        choices = sorted({v for n in entries for v in n['ambitos']})
        selected = [n for n in entries if (view == 'all' or
                    (view == 'orphans' and n['orphan']) or
                    (view == 'no_general' and n['no_general_node']) or
                    (view == 'unresolved' and n['unresolved_count']))
                    and (not ambito or ambito in n['ambitos'])
                    and (not q or canonical(q) in canonical(n['title'] + ' ' + n['path']))]
        selected.sort(key=lambda n: (canonical(n['title']), n['id']))
        start = (page - 1) * per_page
        return {'summary': summary, 'ambitos': choices, 'total': len(selected), 'page': page,
                'per_page': per_page, 'results': selected[start:start + per_page],
                'visibility': 'ia' if self.ai else 'cuenta',
                'scope_note': 'Sólo se cuentan notas y conexiones visibles con estos permisos. Las referencias pendientes no cuentan como conexiones.',
                'general_node_note': 'Los nodos generales son proyectos, personas, organizaciones y clientes a un máximo de dos enlaces. Una conexión indirecta no confirma pertenencia.'}

    def detail(self, note_id):
        if note_id not in self.notes:
            raise HTTPException(404, 'Nota no disponible')
        return self.entry(note_id, detail=True)

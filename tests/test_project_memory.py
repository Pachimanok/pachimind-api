import os
os.environ.setdefault('VAULT_PATH', '/tmp/pachimind-memory-test-unused')
import unittest
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.core.project_memory import build_memory, as_markdown
from app.core.vault_parser import parse_note
from app.core.vault_index import vault_index
from app.models.note import NoteModel, NoteMetadata
from app.routers.projects import router
from app.middleware.auth import get_scope


def note(id, title, **meta):
    content=meta.pop('content',title)
    links=meta.pop('links',[])
    return NoteModel(id=id,title=title,path=f'05 Proyectos/{id}.md',metadata=NoteMetadata(**meta),
                     content=content,content_text=content,wikilinks=links,last_modified=datetime.now())


class MemoryTests(unittest.TestCase):
    def setUp(self):
        self.project=note('project','TotalView',tipo='proyecto',estado='activo')

    def test_relations_dates_and_nonrelations(self):
        old=note('old','Primera',tipo='reunion',fecha='2026-01-01',proyectos=['[[TotalView|TTV]]'])
        recent=note('recent','Segunda',tipo='decision',fecha='2026-07-01',links=['TotalView'])
        unknown=note('unknown','Sin fecha',tipo='accion',fecha='2026-99-99',links=['TotalView'])
        unrelated=note('other','Otro proyecto',cliente='TTG')
        archived=note('arch','Archivada',estado='archivado',links=['TotalView'])
        result=build_memory(self.project,[self.project,old,recent,unknown,unrelated,archived],'personal')
        self.assertEqual([n.id for n in result.sources],['project','recent','old','unknown'])
        self.assertIsNone(result.sources[-1].fecha)

    def test_permissions_and_export(self):
        denied=note('deny','No IA',ia_permiso='deny',links=['TotalView'])
        unindexed=note('noindex','No indexar',ia_indexar=False,links=['TotalView'])
        private=note('private','Privada',sensibilidad='privado',links=['TotalView'])
        visible=note('allowed','Permitida',links=['TotalView'],content='x'*600)
        notes=[self.project,denied,unindexed,private,visible]
        personal=build_memory(self.project,notes,'personal')
        self.assertEqual(len(personal.sources),5)
        ai=build_memory(self.project,notes,'ai_context',True)
        self.assertEqual([n.id for n in ai.sources],['project','allowed'])
        self.assertIsNone(ai.sources[-1].content)
        self.assertTrue(ai.sources[-1].truncated)
        export=as_markdown(build_memory(self.project,notes,'personal',True))
        self.assertNotIn('No IA',export)
        self.assertNotIn('Privada',export)
        self.assertIn('x'*600,export)

    def test_ambiguous_names_do_not_link(self):
        duplicate=note('duplicate','TotalView',tipo='proyecto')
        source=note('source','Reunión',links=['TotalView'])
        exact=note('exact','Reunión exacta',links=['05 Proyectos/project'])
        result=build_memory(self.project,[self.project,duplicate,source,exact],'personal')
        self.assertEqual([n.id for n in result.sources],['project','exact'])

    def test_singular_project_parser_preserves_disk(self):
        with TemporaryDirectory() as tmp:
            path=Path(tmp)/'reunion.md'
            text='---\ntipo: reunion\nproyecto: "[[TotalView]]"\nproyectos: ["[[Rail]]"]\nfecha: 2026-07-01\n---\n# Reunión\nOriginal intacto'
            path.write_text(text)
            result=parse_note(path,Path(tmp))
            self.assertEqual(result.metadata.proyectos,['[[Rail]]','[[TotalView]]'])
            self.assertEqual(path.read_text(),text)

    def test_endpoints_and_scope(self):
        original=vault_index._notes
        try:
            vault_index._notes={self.project.id:self.project}
            app=FastAPI();app.include_router(router)
            app.dependency_overrides[get_scope]=lambda:'personal'
            client=TestClient(app)
            self.assertEqual(client.get('/projects/memory').json()[0]['id'],'project')
            self.assertEqual(client.get('/projects/project/memory').status_code,200)
            exported=client.get('/projects/project/memory.md')
            self.assertEqual(exported.status_code,200)
            self.assertIn('text/markdown',exported.headers['content-type'])
            self.assertEqual(client.get('/projects/missing/memory').status_code,404)
            self.project.metadata.ia_permiso='deny'
            self.assertEqual(client.get('/projects/project/memory.md').status_code,404)
            app.dependency_overrides[get_scope]=lambda:'ai_context'
            self.assertEqual(client.get('/projects/project/memory').status_code,404)
            app.dependency_overrides[get_scope]=lambda:'public'
            self.assertEqual(client.get('/projects/memory').status_code,403)
            self.assertEqual(client.get('/projects/project/memory').status_code,403)
        finally:vault_index._notes=original

if __name__=='__main__':unittest.main()

import hashlib
import json
from types import SimpleNamespace
import pytest
from ai_trader import projection_transfer as t


class Connection:
    info=SimpleNamespace(host='test',port=5432,dbname='test',user='reader')
    def __init__(self):
        self.rows=[{'id':1,'text':'first'}, {'id':2,'text':'second'}]
        self.sent=[]
    def execute(self, sql, params):
        known=set(json.loads(params[-1]))
        pairs=[(hashlib.md5(raw.encode()).hexdigest(),raw) for raw in
               (json.dumps(r,separators=(',',':')) for r in self.rows)]
        changed={h:r for h,r in pairs if h not in known}
        self.sent.append(changed)
        return SimpleNamespace(fetchone=lambda:dict(ordering=[h for h,r in pairs],changed=changed))


@pytest.fixture
def conn(tmp_path,monkeypatch):
    monkeypatch.setattr(t.tempfile,'gettempdir',lambda:str(tmp_path))
    return Connection()


def test_only_changed_rows_transferred_and_old_corrections_seen(conn):
    assert t.read(conn,'SELECT example',('yesterday',))==conn.rows
    assert len(conn.sent[-1])==2
    result=t.read(conn,'SELECT example',('today',))
    assert conn.sent[-1]=={}  # rolling query parameter does not defeat reuse
    result[0]['text']='caller mutation'
    conn.rows[0]['text']='late correction'
    assert t.read(conn,'SELECT example')==conn.rows
    assert len(conn.sent[-1])==1


def test_removal_order_duplicates_and_empty(conn):
    t.read(conn,'SELECT example')
    conn.rows=[conn.rows[1],conn.rows[0],conn.rows[1]]
    assert t.read(conn,'SELECT example')==conn.rows
    assert conn.sent[-1]=={}
    conn.rows=[]
    assert t.read(conn,'SELECT example')==[]


def test_corrupt_cache_is_miss_and_db_failure_never_uses_stale_data(conn,monkeypatch):
    t.read(conn,'SELECT example')
    monkeypatch.setattr(t,'_cache',lambda *a:{})
    assert t.read(conn,'SELECT example')==conn.rows
    assert len(conn.sent[-1])==2
    def fail(*a): raise RuntimeError('database unavailable')
    monkeypatch.setattr(conn,'execute',fail)
    with pytest.raises(RuntimeError): t.read(conn,'SELECT example')


def test_identity_and_schema_column_change(conn):
    t.read(conn,'SELECT example')
    conn.info=SimpleNamespace(host='other',port=5432,dbname='test',user='reader')
    t.read(conn,'SELECT example')
    assert len(conn.sent[-1])==2
    conn.rows=[{**r,'new_column':None} for r in conn.rows]
    assert t.read(conn,'SELECT example')==conn.rows
    assert len(conn.sent[-1])==2


def test_table_partitions_survive_alternating_reads(conn):
    original=list(conn.rows)
    t.read(conn,'SELECT example',partition='table-a')
    conn.rows=[{'id':9,'text':'other table'}]
    t.read(conn,'SELECT example',partition='table-b')
    conn.rows=original
    assert t.read(conn,'SELECT example',partition='table-a')==original
    assert conn.sent[-1]=={}

-- Additive rollout. Policy remains disabled until ALL readers are deployed.
CREATE TABLE IF NOT EXISTS decision_evidence_blobs (
    evidence_hash TEXT PRIMARY KEY,
    payload_json TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (evidence_hash = encode(sha256(convert_to(payload_json, 'UTF8')), 'hex'))
);
CREATE TABLE IF NOT EXISTS decision_storage_policy (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    enabled BOOLEAN NOT NULL DEFAULT false
);
INSERT INTO decision_storage_policy(id, enabled) VALUES (1, false) ON CONFLICT DO NOTHING;
CREATE TABLE IF NOT EXISTS decision_storage_migrations (
    source_table TEXT NOT NULL,
    source_id BIGINT NOT NULL,
    original_hash TEXT NOT NULL,
    compact_hash TEXT NOT NULL,
    original_bytes INTEGER NOT NULL,
    compact_bytes INTEGER NOT NULL,
    migrated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY(source_table, source_id)
);
ALTER TABLE decision_evidence_blobs ENABLE ROW LEVEL SECURITY;
ALTER TABLE decision_storage_policy ENABLE ROW LEVEL SECURITY;
ALTER TABLE decision_storage_migrations ENABLE ROW LEVEL SECURITY;

CREATE OR REPLACE FUNCTION compact_decision_payload(original TEXT) RETURNS TEXT
LANGUAGE plpgsql AS $$
DECLARE
    doc JSONB; part JSONB; path TEXT[]; body TEXT; digest TEXT;
BEGIN
    IF NOT coalesce((SELECT enabled FROM decision_storage_policy WHERE id=1),false) THEN RETURN original; END IF;
    doc := original::jsonb;
    FOREACH path SLICE 1 IN ARRAY ARRAY[['intelligence',NULL],['proposal','intelligence']] LOOP
        path := array_remove(path,NULL);
        part := doc #> path;
        IF jsonb_typeof(part) = 'object' AND NOT (part ? '__decision_evidence_sha256_v1')
           AND octet_length(part::text) >= 1024 THEN
            body := part::text;
            digest := encode(sha256(convert_to(body,'UTF8')),'hex');
            INSERT INTO decision_evidence_blobs(evidence_hash,payload_json)
                VALUES(digest,body) ON CONFLICT DO NOTHING;
            doc := jsonb_set(doc,path,jsonb_build_object('__decision_evidence_sha256_v1',digest));
        END IF;
    END LOOP;
    RETURN doc::text;
END $$;

CREATE OR REPLACE FUNCTION expand_decision_payload(original TEXT) RETURNS TEXT
LANGUAGE plpgsql STABLE AS $$
DECLARE
    doc JSONB; part JSONB; path TEXT[]; body TEXT; digest TEXT;
BEGIN
    doc := original::jsonb;
    FOREACH path SLICE 1 IN ARRAY ARRAY[['intelligence',NULL],['proposal','intelligence']] LOOP
        path := array_remove(path,NULL);
        part := doc #> path;
        IF jsonb_typeof(part) = 'object' AND part ? '__decision_evidence_sha256_v1' THEN
            digest := part ->> '__decision_evidence_sha256_v1';
            SELECT payload_json INTO body FROM decision_evidence_blobs WHERE evidence_hash=digest;
            IF body IS NULL OR encode(sha256(convert_to(body,'UTF8')),'hex') <> digest THEN
                RAISE EXCEPTION 'Missing or corrupt decision evidence';
            END IF;
            doc := jsonb_set(doc,path,body::jsonb);
        END IF;
    END LOOP;
    RETURN doc::text;
END $$;

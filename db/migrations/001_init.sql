-- LLB Sutra — initial schema.
-- Content is modelled as LAW (subjects, modules, topics, provisions, cases, questions),
-- not as PDFs. Chunks hang off that structure so retrieval can be FILTERED BEFORE RANKED,
-- which is the single biggest accuracy win over a generic vector store.

CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- ---------------------------------------------------------------------------
-- Enums
-- ---------------------------------------------------------------------------

-- What a document IS. Drives chunking strategy in ingest/chunk.py.
CREATE TYPE doc_type AS ENUM (
    'bare_act',
    'judgment',
    'treaty',
    'syllabus',
    'pyq',
    'notes',
    'textbook'
);

-- What we are ALLOWED TO SERVE. Enforced in backend/app/retrieval.py at
-- serialization time — never by prompt instruction. See licence_max_chars().
CREATE TYPE licence AS ENUM (
    'public',          -- treaties, UN/ICJ material: full text servable
    'govt-public',     -- Indian bare acts, judgments: full text servable
    'owned-licensed',  -- your legally-owned books/notes: retrieval only, 200-char excerpt
    'excerpt-only'     -- most restricted: 50-char excerpt
);

-- ---------------------------------------------------------------------------
-- Syllabus structure
-- ---------------------------------------------------------------------------

CREATE TABLE subject (
    id          serial PRIMARY KEY,
    code        text NOT NULL,
    name        text NOT NULL,
    slug        text NOT NULL UNIQUE,
    semester    int  NOT NULL,
    university  text NOT NULL DEFAULT 'University of Mumbai',
    UNIQUE (university, semester, code)
);

CREATE TABLE module (
    id          serial PRIMARY KEY,
    subject_id  int  NOT NULL REFERENCES subject(id) ON DELETE CASCADE,
    number      int  NOT NULL,
    title       text NOT NULL,
    UNIQUE (subject_id, number)
);

CREATE TABLE topic (
    id          serial PRIMARY KEY,
    module_id   int  NOT NULL REFERENCES module(id) ON DELETE CASCADE,
    title       text NOT NULL,
    slug        text NOT NULL UNIQUE,
    keywords    text[] NOT NULL DEFAULT '{}'
);

-- ---------------------------------------------------------------------------
-- Legislation
-- ---------------------------------------------------------------------------

CREATE TABLE act (
    id            serial PRIMARY KEY,
    short_title   text NOT NULL,
    year          int,
    act_number    text,           -- e.g. 'Act No. 46 of 2023'
    jurisdiction  text NOT NULL DEFAULT 'India',
    slug          text NOT NULL UNIQUE
);

CREATE TABLE provision (
    id             bigserial PRIMARY KEY,
    act_id         int  NOT NULL REFERENCES act(id) ON DELETE CASCADE,
    section_no     text NOT NULL,   -- text, not int: '11', '41A', 'O.7 R.11'
    marginal_note  text,            -- the section heading
    text           text NOT NULL,   -- VERBATIM statutory text; never paraphrase this
    parent_id      bigint REFERENCES provision(id) ON DELETE CASCADE,
    ord            int  NOT NULL DEFAULT 0,
    UNIQUE (act_id, section_no)
);

-- Old law -> new law. Powers "what is CrPC 154 now?" from DATA, not from the model.
-- IPC->BNS, CrPC->BNSS, Evidence Act->BSA.
CREATE TABLE provision_map (
    old_provision_id  bigint NOT NULL REFERENCES provision(id) ON DELETE CASCADE,
    new_provision_id  bigint NOT NULL REFERENCES provision(id) ON DELETE CASCADE,
    relation          text   NOT NULL DEFAULT 'corresponds_to',
                             -- corresponds_to | split_into | merged_into | omitted | new
    note              text,
    PRIMARY KEY (old_provision_id, new_provision_id)
);

-- ---------------------------------------------------------------------------
-- Case law
-- ---------------------------------------------------------------------------

CREATE TABLE case_law (
    id                bigserial PRIMARY KEY,
    name              text NOT NULL,
    court             text NOT NULL DEFAULT 'Supreme Court of India',
    year              int,
    url               text,
    neutral_citation  text,   -- e.g. '2023 INSC 456' — stable, machine-friendly
    scr_citation      text,   -- official Supreme Court Reports — what examiners expect
    reported_as       text,   -- any other citation as printed on the source document
    facts             text,
    issue             text,
    held              text,
    ratio             text,
    slug              text NOT NULL UNIQUE
);

-- A case can be authority on several topics; a topic has many cases.
CREATE TABLE case_topic (
    case_id   bigint NOT NULL REFERENCES case_law(id) ON DELETE CASCADE,
    topic_id  int    NOT NULL REFERENCES topic(id) ON DELETE CASCADE,
    PRIMARY KEY (case_id, topic_id)
);

-- ---------------------------------------------------------------------------
-- Previous-year questions — the basis of the PYQ analytics differentiator
-- ---------------------------------------------------------------------------

CREATE TABLE pyq (
    id             bigserial PRIMARY KEY,
    subject_id     int  NOT NULL REFERENCES subject(id) ON DELETE CASCADE,
    topic_id       int  REFERENCES topic(id) ON DELETE SET NULL,
    year           int  NOT NULL,
    exam           text,          -- e.g. 'Nov 2024', 'ATKT Apr 2025'
    marks          int,
    question_no    text,
    question_text  text NOT NULL
);

-- ---------------------------------------------------------------------------
-- Documents and chunks
-- ---------------------------------------------------------------------------

CREATE TABLE document (
    id           bigserial PRIMARY KEY,
    title        text NOT NULL,
    source_url   text,
    local_path   text,
    doc_type     doc_type NOT NULL,
    licence      licence  NOT NULL,
    checksum     text NOT NULL,      -- sha256 of the raw file; makes ingest idempotent
    subject_id   int REFERENCES subject(id) ON DELETE SET NULL,
    act_id       int REFERENCES act(id) ON DELETE SET NULL,
    case_id      bigint REFERENCES case_law(id) ON DELETE SET NULL,
    ingested_at  timestamptz NOT NULL DEFAULT now(),
    UNIQUE (checksum)
);

CREATE TABLE chunk (
    id            bigserial PRIMARY KEY,
    document_id   bigint NOT NULL REFERENCES document(id) ON DELETE CASCADE,
    topic_id      int    REFERENCES topic(id) ON DELETE SET NULL,
    provision_id  bigint REFERENCES provision(id) ON DELETE SET NULL,
    case_id       bigint REFERENCES case_law(id) ON DELETE SET NULL,
    ord           int    NOT NULL,
    heading       text,
    text          text   NOT NULL,
    n_tokens      int,
    tsv           tsvector,
    embedding     vector(384)
);

-- ---------------------------------------------------------------------------
-- Full-text search: trigger-maintained tsvector.
-- Weight A = heading, B = body, so a section's marginal note outranks a passing mention.
-- ---------------------------------------------------------------------------

CREATE FUNCTION chunk_tsv_update() RETURNS trigger AS $$
BEGIN
    NEW.tsv :=
        setweight(to_tsvector('english', coalesce(NEW.heading, '')), 'A') ||
        setweight(to_tsvector('english', coalesce(NEW.text, '')),    'B');
    RETURN NEW;
END
$$ LANGUAGE plpgsql;

CREATE TRIGGER chunk_tsv_trigger
    BEFORE INSERT OR UPDATE OF heading, text ON chunk
    FOR EACH ROW EXECUTE FUNCTION chunk_tsv_update();

-- ---------------------------------------------------------------------------
-- Indexes
-- ---------------------------------------------------------------------------

CREATE INDEX chunk_tsv_idx        ON chunk USING gin (tsv);
CREATE INDEX chunk_document_idx   ON chunk (document_id);
CREATE INDEX chunk_topic_idx      ON chunk (topic_id);
CREATE INDEX chunk_provision_idx  ON chunk (provision_id);
CREATE INDEX chunk_case_idx       ON chunk (case_id);

-- HNSW for cosine similarity. Built empty here; pgvector fills it incrementally.
-- If a bulk load ever feels slow, DROP this index, load, then re-CREATE.
CREATE INDEX chunk_embedding_idx ON chunk
    USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

-- Section lookup is exact and hot: "Section 11 CPC" must hit the provision directly.
CREATE INDEX provision_section_idx ON provision (act_id, section_no);
CREATE INDEX provision_trgm_idx    ON provision USING gin (section_no gin_trgm_ops);

-- Case-name matching tolerates the way students actually type case names.
CREATE INDEX case_name_trgm_idx ON case_law USING gin (name gin_trgm_ops);

CREATE INDEX pyq_subject_year_idx ON pyq (subject_id, year);
CREATE INDEX pyq_topic_idx        ON pyq (topic_id);

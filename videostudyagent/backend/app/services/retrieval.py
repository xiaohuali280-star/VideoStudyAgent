import re

from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from app.schemas.retrieval import EvidenceHit, EvidenceSearchResult
from app.services.indexing import read_source

SCAN_LIMIT = 10000


def terms(query):
    # No caller-supplied MATCH operators, column selectors, quotes or SQL syntax.
    return list(dict.fromkeys(re.findall(r"[\w.+-]+", query.lower(), re.UNICODE)))[:12]


def retrieve(repository, root, task_id, query):
    scope, digest = read_source(
        repository, root, task_id, query.snapshot_id, query.snapshot_type, query.notes_revision_id
    )
    canonical = {(s["source_type"], s["source_id"]): s for s in scope.items}

    def allowed(item):
        return (
            item["source_type"] in query.source_types
            and (query.start_ms is None or item["end_ms"] >= query.start_ms)
            and (query.end_ms is None or item["start_ms"] <= query.end_ms)
        )

    scoped = [s for s in scope.items if allowed(s)]
    tokens = terms(query.query)

    def lexical_score(item):
        value = re.sub(r"(?<=[\u3400-\u9fff])\s+(?=[\u3400-\u9fff])", "", item["text"].lower())
        return (2.0 if query.query.lower() in value else 0.0) + sum(t in value for t in tokens)

    warnings = []
    generation = None
    scores = {}
    try:
        with repository.engine.connect() as connection:
            parameters = dict(
                task=str(task_id), snapshot=str(query.snapshot_id), kind=query.snapshot_type
            )
            manifest = connection.execute(
                text(
                    "SELECT source_sha256,tokenizer_version,generation "
                    "FROM evidence_index_manifests WHERE task_id=:task AND snapshot_id=:snapshot "
                    "AND snapshot_type=:kind AND state='ready'"
                ),
                parameters,
            ).first()
            if not manifest or manifest[0] != digest or manifest[1] != "trigram-v1":
                raise ValueError("Stale or missing index")
            generation = manifest[2]
            fts_count = connection.scalar(
                text(
                    "SELECT COUNT(*) FROM evidence_fts f "
                    "JOIN evidence_documents d ON d.id=f.rowid WHERE d.task_id=:task "
                    "AND d.snapshot_id=:snapshot AND d.snapshot_type=:kind "
                    "AND f.raw_text=d.raw_text"
                ),
                parameters,
            )
            if fts_count != len(scope.items):
                raise ValueError("Incomplete FTS index")
            # Verify index scope/content against immutable sources before trusting hits.
            rows = connection.execute(
                text(
                    "SELECT source_type,source_id,raw_text,start_ms,end_ms "
                    "FROM evidence_documents WHERE task_id=:task AND snapshot_id=:snapshot "
                    "AND snapshot_type=:kind"
                ),
                parameters,
            ).fetchall()
            if len(rows) != len(scope.items) or any(
                (r[0], r[1]) not in canonical
                or (r[2], r[3], r[4])
                != (
                    canonical[(r[0], r[1])]["text"],
                    canonical[(r[0], r[1])]["start_ms"],
                    canonical[(r[0], r[1])]["end_ms"],
                )
                for r in rows
            ):
                raise ValueError("Corrupt index")
            full = [t for t in tokens if len(t) >= 3]
            if full:
                match = " OR ".join('"' + t.replace('"', '""') + '"' for t in full)
                filters = "d.task_id=:task AND d.snapshot_id=:snapshot AND d.snapshot_type=:kind"
                if query.start_ms is not None:
                    filters += " AND d.end_ms>=:start"
                    parameters["start"] = query.start_ms
                if query.end_ms is not None:
                    filters += " AND d.start_ms<=:end"
                    parameters["end"] = query.end_ms
                if len(set(query.source_types)) == 1:
                    filters += " AND d.source_type=:source"
                    parameters["source"] = query.source_types[0]
                rows = connection.execute(
                    text(
                        "SELECT d.source_type,d.source_id,bm25(evidence_fts) "
                        "FROM evidence_fts JOIN evidence_documents d ON d.id=evidence_fts.rowid "
                        "WHERE evidence_fts MATCH :match AND "
                        + filters
                        + " ORDER BY bm25(evidence_fts),d.id LIMIT :limit"
                    ),
                    parameters | dict(match=match, limit=query.top_k * 4),
                ).fetchall()
                scores = {(r[0], r[1]): max(0.0, -r[2]) for r in rows}
            mode = "lexical_fts5"
            candidates = scoped
    except (OperationalError, ValueError):
        warnings.append("INDEX_UNAVAILABLE_SCOPED_FALLBACK")
        mode = "scoped_source_fallback"
        candidates = scoped[:SCAN_LIMIT]
        if len(scoped) > SCAN_LIMIT:
            warnings.append("RETRIEVAL_SCAN_LIMIT")
    ranked = []
    for item in candidates:
        exact = lexical_score(item)
        fts = scores.get((item["source_type"], item["source_id"]), 0.0)
        if exact > 0 or fts > 0:
            ranked.append((exact + fts, item, dict(exact_terms=exact, fts5=fts)))
    ranked.sort(key=lambda v: (-v[0], v[1]["start_ms"], v[1]["source_type"], v[1]["source_id"]))
    hits = [
        EvidenceHit(
            task_id=task_id,
            snapshot_id=query.snapshot_id,
            source_type=item["source_type"],
            source_id=item["source_id"],
            start_ms=item["start_ms"],
            end_ms=item["end_ms"],
            raw_text=item["text"],
            frame_id=item.get("frame_id"),
            score_components=score,
        )
        for _, item, score in ranked[: query.top_k]
    ]
    return EvidenceSearchResult(
        hits=hits,
        warnings=warnings,
        mode=mode,
        scanned_sources=len(candidates),
        total_sources=len(scoped),
        index_generation=generation,
    )

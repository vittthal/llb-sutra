import { useEffect, useState } from 'react';
import { getActs, getPyq, getStats, getSyllabus, getTopics, search } from '../api';

function Empty({ children }) {
  return <div className="empty">{children}</div>;
}

function SubjectSelect({ value, onChange, subjects }) {
  return (
    <select value={value} onChange={(e) => onChange(e.target.value)} aria-label="Subject">
      <option value="">All subjects</option>
      {subjects.map((s) => (
        <option key={s.code} value={s.code}>
          {s.code} — {s.name.slice(0, 46)}
        </option>
      ))}
    </select>
  );
}

/* ------------------------------- Search ------------------------------- */

export function SearchView({ subjects, query, setQuery }) {
  const [q, setQ] = useState(query || '');
  const [subject, setSubject] = useState('');
  const [state, setState] = useState({ status: 'idle', results: [] });

  useEffect(() => {
    if (query) {
      setQ(query);
      run(query, subject);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [query]);

  async function run(text, subj) {
    if (!text?.trim()) return;
    setState({ status: 'loading', results: [] });
    try {
      const d = await search(text, subj);
      setState({ status: 'done', results: d.results });
    } catch (e) {
      setState({ status: 'error', results: [], message: e.message });
    }
  }

  const submit = (e) => {
    e.preventDefault();
    setQuery(q);
    run(q, subject);
  };

  return (
    <>
      <h2>Search</h2>
      <p className="lede">
        Keyword and meaning together. Naming a section returns that exact section, not
        something similar to it.
      </p>

      <form className="searchbar" onSubmit={submit}>
        <input
          type="search"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="e.g. Section 173 BNSS, condonation of delay…"
          aria-label="Search"
        />
        <SubjectSelect value={subject} onChange={setSubject} subjects={subjects} />
        <button className="go" type="submit" disabled={!q.trim()}>
          Search
        </button>
      </form>

      {state.status === 'loading' && [0, 1, 2].map((i) => <div className="skel" key={i} style={{ height: 110 }} />)}
      {state.status === 'error' && <Empty>{state.message}</Empty>}
      {state.status === 'done' && state.results.length === 0 && (
        <Empty>Nothing found. Try a section number, or fewer words.</Empty>
      )}

      {state.results.map((r) => (
        <div className={`card${r.pinned ? ' pin' : ''}`} key={r.chunk_id}>
          <div className="cite">{r.citation}</div>
          {r.heading && r.heading !== r.citation && <div className="head">{r.heading}</div>}
          <div className="txt">{r.text.length > 780 ? r.text.slice(0, 780) + '…' : r.text}</div>
          <div className="meta">
            {r.pinned && <span className="tag pin">exact section</span>}
            {r.matched_by.map((m) => (
              <span className="tag" key={m}>
                {m}
              </span>
            ))}
            <span className="tag">{r.doc_type.replace('_', ' ')}</span>
            {r.truncated && <span className="tag trunc">licensed — excerpt only</span>}
          </div>
        </div>
      ))}
    </>
  );
}

/* ------------------------------ Syllabus ------------------------------ */

export function SyllabusView({ onSearch }) {
  const [subs, setSubs] = useState(null);

  useEffect(() => {
    getSyllabus().then(setSubs).catch(() => setSubs([]));
  }, []);

  if (!subs) return [0, 1, 2].map((i) => <div className="skel" key={i} style={{ height: 70 }} />);

  return (
    <>
      <h2>Semester V syllabus</h2>
      <p className="lede">
        Every module and topic from the university syllabus. Click a topic to search the
        bare acts, papers and notes for it.
      </p>
      {subs.map((s, i) => {
        const nTopics = s.modules.reduce((a, m) => a + m.topics.length, 0);
        return (
          <details className="subj" key={s.code} open={i === 0}>
            <summary>
              <span className="code">{s.code}</span>
              <span className="nm">{s.name}</span>
              <span className="ct">
                {s.modules.length} modules · {nTopics} topics
              </span>
            </summary>
            {s.modules.length === 0 && <Empty>Modules not parsed for this paper.</Empty>}
            {s.modules.map((m) => (
              <div className="mod" key={m.number}>
                <div className="mod-h">
                  <span className="mod-n">MODULE {m.number}</span>
                  <span className="mod-t">{m.title}</span>
                </div>
                {m.topics.length > 0 ? (
                  <div className="tops">
                    {m.topics.map((t) => (
                      <button className="top" key={t.slug} onClick={() => onSearch(t.title.slice(0, 70))}>
                        {t.title.length > 70 ? t.title.slice(0, 70) + '…' : t.title}
                      </button>
                    ))}
                  </div>
                ) : (
                  <div style={{ font: '12.5px var(--sans)', color: 'var(--faint)' }}>
                    Topics are not itemised for this module in the source syllabus.
                  </div>
                )}
              </div>
            ))}
          </details>
        );
      })}
    </>
  );
}

/* ------------------------------- Topics ------------------------------- */

export function TopicsView({ subjects, onSearch }) {
  const [subject, setSubject] = useState('');
  const [rows, setRows] = useState(null);

  useEffect(() => {
    setRows(null);
    getTopics(subject).then(setRows).catch(() => setRows([]));
  }, [subject]);

  const max = rows?.length ? Math.max(...rows.map((r) => r.times_asked)) : 1;

  return (
    <>
      <h2>What gets asked</h2>
      <p className="lede">
        Counted from the 75-25 papers in the corpus — measured, not guessed. Revise from the
        top down.
      </p>
      <div className="searchbar">
        <SubjectSelect value={subject} onChange={setSubject} subjects={subjects} />
      </div>

      {!rows && [0, 1, 2].map((i) => <div className="skel" key={i} />)}
      {rows?.length === 0 && <Empty>No questions loaded.</Empty>}
      {rows?.length > 0 && (
        <table>
          <thead>
            <tr>
              <th>Topic</th>
              <th>Subject</th>
              <th style={{ textAlign: 'right' }}>Asked</th>
              <th style={{ textAlign: 'right' }}>Papers</th>
              <th style={{ textAlign: 'right' }}>Years</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((t) => (
              <tr key={t.topic} data-clickable="true" onClick={() => onSearch(t.topic.split(' / ')[0])}>
                <td>
                  <span className="bar" style={{ width: Math.round((t.times_asked / max) * 100) }} />
                  {t.topic}
                  {t.times_asked >= max * 0.6 && <span className="tag hot"> high yield</span>}
                </td>
                <td>
                  {t.subjects.map((s) => (
                    <span className="tag" key={s}>
                      {s}
                    </span>
                  ))}
                </td>
                <td className="num">
                  <b>{t.times_asked}</b>
                </td>
                <td className="num">{t.in_papers}</td>
                <td className="num">
                  {t.first_seen === t.last_seen ? t.first_seen : `${t.first_seen}–${t.last_seen}`}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </>
  );
}

/* ------------------------------ Past papers --------------------------- */

export function PyqView({ subjects, onSearch }) {
  const [subject, setSubject] = useState('');
  const [rows, setRows] = useState(null);

  useEffect(() => {
    setRows(null);
    getPyq(subject).then(setRows).catch(() => setRows([]));
  }, [subject]);

  const grouped = {};
  (rows || []).forEach((q) => {
    const k = `${q.subject} — ${q.exam}`;
    (grouped[k] ||= []).push(q);
  });

  return (
    <>
      <h2>Past papers</h2>
      <p className="lede">Questions from the 75-25 papers, grouped by exam.</p>
      <div className="searchbar">
        <SubjectSelect value={subject} onChange={setSubject} subjects={subjects} />
      </div>

      {!rows && [0, 1].map((i) => <div className="skel" key={i} style={{ height: 130 }} />)}
      {rows?.length === 0 && <Empty>No questions.</Empty>}

      {Object.entries(grouped).map(([k, qs]) => (
        <div className="card" key={k}>
          <div className="cite">
            {k} · {qs.length} questions
          </div>
          {qs.map((q) => (
            <div className="q" key={q.id}>
              <span className="qno">Q{q.question_no}</span>
              {q.question_text.slice(0, 320)}
              <button className="link" onClick={() => onSearch(q.question_text.slice(0, 60))}>
                find material
              </button>
            </div>
          ))}
        </div>
      ))}
    </>
  );
}

/* ------------------------------- Library ------------------------------ */

export function LibraryView() {
  const [data, setData] = useState(null);

  useEffect(() => {
    Promise.all([getStats(), getActs()])
      .then(([stats, acts]) => setData({ stats, acts }))
      .catch(() => setData({ stats: null, acts: [] }));
  }, []);

  if (!data) return [0, 1].map((i) => <div className="skel" key={i} style={{ height: 90 }} />);

  const { stats, acts } = data;
  return (
    <>
      <h2>Library</h2>
      <p className="lede">What is loaded, and how completely each act was parsed.</p>
      <div className="statrow">
        {stats &&
          [
            ['Sections', stats.provisions],
            ['Documents', stats.documents],
            ['Questions', stats.pyqs],
            ['Passages', stats.chunks],
            ['Embedded', stats.chunks_embedded],
          ].map(([l, v]) => (
            <div className="stat" key={l}>
              <b>{v?.toLocaleString?.() ?? v}</b>
              <span>{l}</span>
            </div>
          ))}
      </div>
      <table>
        <thead>
          <tr>
            <th>Act</th>
            <th style={{ textAlign: 'right' }}>Year</th>
            <th style={{ textAlign: 'right' }}>Sections parsed</th>
          </tr>
        </thead>
        <tbody>
          {acts.map((a) => (
            <tr key={a.id}>
              <td>{a.short_title}</td>
              <td className="num">{a.year ?? ''}</td>
              <td className="num">{a.sections}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  );
}

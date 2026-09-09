import { useEffect, useState } from 'react';
import { getStats, getSyllabus, getTopics } from '../api';

const EXAMPLES = [
  'Section 35 BNSS',
  'res judicata',
  'anticipatory bail',
  'gig worker',
  'law of treaties',
  'juvenile justice',
];

/**
 * The landing page answers three questions a student actually has:
 * what is on my syllabus, what gets asked most, and where do I look it up.
 * Those are the three blocks below, in that order.
 */
export default function Home({ onSearch, onGo }) {
  const [q, setQ] = useState('');
  const [stats, setStats] = useState(null);
  const [subjects, setSubjects] = useState([]);
  const [topics, setTopics] = useState([]);
  const [slow, setSlow] = useState(false);

  useEffect(() => {
    const onSlow = () => setSlow(true);
    Promise.all([
      getStats({ onSlow }).catch(() => null),
      getSyllabus({ onSlow }).catch(() => []),
      getTopics(null, { onSlow }).catch(() => []),
    ]).then(([s, syl, t]) => {
      setStats(s);
      setSubjects(syl.filter((x) => x.code !== 'MOOT'));
      setTopics(t.slice(0, 6));
      setSlow(false);
    });
  }, []);

  const submit = (e) => {
    e.preventDefault();
    if (q.trim()) onSearch(q.trim());
  };

  const maxAsked = topics.length ? topics[0].times_asked : 1;

  return (
    <>
      <section className="hero">
        <h2>
          Everything for <em>Semester V</em>, with the section it comes from.
        </h2>
        <p>
          Bare acts, past papers and the university syllabus in one place. Search in plain
          English or by section number — every answer carries its citation.
        </p>

        <form className="homesearch" onSubmit={submit}>
          <input
            type="search"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Ask anything, or type a section number…"
            aria-label="Search the corpus"
          />
          <button className="go" type="submit" disabled={!q.trim()}>
            Search
          </button>
        </form>

        <div className="chips">
          {EXAMPLES.map((t) => (
            <button key={t} className="chip" onClick={() => onSearch(t)}>
              {t}
            </button>
          ))}
        </div>
      </section>

      {slow && (
        <div className="note" style={{ marginTop: 24 }}>
          Waking the server — the free tier sleeps after 15 minutes of no visitors, so the
          first load can take up to a minute. Everything after this is fast.
        </div>
      )}

      <div className="statrow">
        {stats ? (
          [
            ['Sections', stats.provisions],
            ['Past questions', stats.pyqs],
            ['Documents', stats.documents],
            ['Searchable passages', stats.chunks],
          ].map(([label, value]) => (
            <div className="stat" key={label}>
              <b>{value?.toLocaleString?.() ?? value}</b>
              <span>{label}</span>
            </div>
          ))
        ) : (
          [0, 1, 2, 3].map((i) => <div className="skel" key={i} />)
        )}
      </div>

      <div className="sectionhead">
        <h3>Your papers</h3>
        <button className="more" onClick={() => onGo('syllabus')}>
          Full syllabus →
        </button>
      </div>
      <div className="subjgrid">
        {subjects.map((s) => {
          const nTopics = s.modules.reduce((a, m) => a + m.topics.length, 0);
          return (
            <button key={s.code} className="subjcard" onClick={() => onGo('syllabus')}>
              <span className="code">{s.code}</span>
              <span className="nm">{s.name.length > 90 ? s.name.slice(0, 90) + '…' : s.name}</span>
              <span className="ct">
                {s.modules.length} modules · {nTopics} topics
              </span>
            </button>
          );
        })}
      </div>

      {topics.length > 0 && (
        <>
          <div className="sectionhead">
            <h3>Asked most often</h3>
            <button className="more" onClick={() => onGo('topics')}>
              All topics →
            </button>
          </div>
          <div className="hotlist">
            {topics.map((t, i) => (
              <button
                key={t.topic}
                className="hot"
                onClick={() => onSearch(t.topic.split(' / ')[0])}
              >
                <span className="rank">{i + 1}</span>
                <span className="name">{t.topic}</span>
                <span className="track">
                  <span
                    className="fill"
                    style={{ width: `${Math.round((t.times_asked / maxAsked) * 100)}%` }}
                  />
                </span>
                <span className="n">{t.times_asked}×</span>
              </button>
            ))}
          </div>
        </>
      )}
    </>
  );
}

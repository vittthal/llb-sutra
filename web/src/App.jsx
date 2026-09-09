import { useEffect, useState } from 'react';
import { getSubjects } from './api';
import Home from './components/Home';
import { LibraryView, PyqView, SearchView, SyllabusView, TopicsView } from './components/Views';

const TABS = [
  ['home', 'Home'],
  ['syllabus', 'Syllabus'],
  ['search', 'Search'],
  ['topics', 'What gets asked'],
  ['pyq', 'Past papers'],
  ['library', 'Library'],
];

export default function App() {
  // The hash is the router: it survives refresh and makes tabs linkable, without
  // pulling in a routing library for six views.
  const [tab, setTab] = useState(() => window.location.hash.slice(1) || 'home');
  const [query, setQuery] = useState('');
  const [subjects, setSubjects] = useState([]);

  useEffect(() => {
    getSubjects()
      .then((s) => setSubjects(s.filter((x) => x.code !== 'MOOT')))
      .catch(() => setSubjects([]));
  }, []);

  useEffect(() => {
    const onHash = () => setTab(window.location.hash.slice(1) || 'home');
    window.addEventListener('hashchange', onHash);
    return () => window.removeEventListener('hashchange', onHash);
  }, []);

  const go = (next) => {
    window.location.hash = next;
    setTab(next);
    window.scrollTo({ top: 0 });
  };

  const runSearch = (text) => {
    setQuery(text);
    go('search');
  };

  return (
    <>
      <header>
        <div className="wrap">
          <div className="brand" onClick={() => go('home')}>
            <h1>
              LLB <span>Sutra</span>
            </h1>
            <small>MUMBAI UNIVERSITY · LL.B. SEMESTER V</small>
          </div>
          <nav>
            {TABS.map(([id, label]) => (
              <button key={id} data-on={tab === id} onClick={() => go(id)}>
                {label}
              </button>
            ))}
          </nav>
        </div>
      </header>

      <main>
        <div className="wrap">
          {tab === 'home' && <Home onSearch={runSearch} onGo={go} />}
          {tab === 'syllabus' && <SyllabusView onSearch={runSearch} />}
          {tab === 'search' && (
            <SearchView subjects={subjects} query={query} setQuery={setQuery} />
          )}
          {tab === 'topics' && <TopicsView subjects={subjects} onSearch={runSearch} />}
          {tab === 'pyq' && <PyqView subjects={subjects} onSearch={runSearch} />}
          {tab === 'library' && <LibraryView />}
        </div>
      </main>

      <footer>
        Bare acts from India Code · treaties from the UN · questions from past papers ·
        every passage carries its citation
      </footer>
    </>
  );
}

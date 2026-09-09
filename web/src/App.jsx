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

/**
 * Theme: follow the system by default, remember an explicit choice.
 *
 * Stored per browser, so it never travels between devices — which is the right
 * scope for a display preference on a site with no accounts.
 */
function useTheme() {
  const [theme, setTheme] = useState(() => {
    try {
      return localStorage.getItem('theme') || 'system';
    } catch {
      return 'system'; // private mode / blocked storage
    }
  });

  useEffect(() => {
    const root = document.documentElement;
    if (theme === 'system') root.removeAttribute('data-theme');
    else root.setAttribute('data-theme', theme);
    try {
      if (theme === 'system') localStorage.removeItem('theme');
      else localStorage.setItem('theme', theme);
    } catch {
      /* storage unavailable; the theme still applies for this session */
    }
  }, [theme]);

  const prefersDark =
    typeof window !== 'undefined' &&
    window.matchMedia?.('(prefers-color-scheme: dark)').matches;
  const isDark = theme === 'dark' || (theme === 'system' && prefersDark);

  return [isDark, () => setTheme(isDark ? 'light' : 'dark')];
}

export default function App() {
  // The hash is the router: it survives refresh and makes tabs linkable, without
  // pulling in a routing library for six views.
  const [tab, setTab] = useState(() => window.location.hash.slice(1) || 'home');
  const [query, setQuery] = useState('');
  const [subjects, setSubjects] = useState([]);
  const [isDark, toggleTheme] = useTheme();

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
          <div className="headrow">
            <div className="brand" onClick={() => go('home')}>
              <h1>
                LLB <span>Sutra</span>
              </h1>
              <small>MUMBAI UNIVERSITY · LL.B. SEMESTER V</small>
            </div>
            <button
              className="themebtn"
              onClick={toggleTheme}
              title={isDark ? 'Switch to light' : 'Switch to dark'}
              aria-label={isDark ? 'Switch to light theme' : 'Switch to dark theme'}
            >
              {isDark ? '☀' : '☾'}
            </button>
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
        <div className="credit">Developed by Vitthal Mokhare</div>
        <div>
          Bare acts from India Code · treaties from the UN · questions from past papers ·
          every passage carries its citation
        </div>
      </footer>
    </>
  );
}

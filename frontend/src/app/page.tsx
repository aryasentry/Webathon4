"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";

interface Repo {
  id: string;
  github_id: number;
  owner_login: string;
  name: string;
  full_name: string;
  private: boolean;
  archived: boolean;
  default_branch: string;
  language?: string;
  stargazers_count: number;
  forks_count: number;
  open_issues_count: number;
  role: string;
  last_synced_at?: string;
}

export default function Home() {
  const router = useRouter();
  const [token, setToken] = useState<string | null>(null);
  const [user, setUser] = useState<any | null>(null); // Added user state
  const [repos, setRepos] = useState<Repo[]>([]);
  const [loading, setLoading] = useState(true); // Changed initial loading state to true
  const [error, setError] = useState<string | null>(null); // Changed error type
  const [filter, setFilter] = useState<'all' | 'owned' | 'collaborating'>('all'); // Added filter state

  useEffect(() => {
    // Check URL for token on mount
    if (typeof window !== "undefined") {
      const params = new URLSearchParams(window.location.search);
      const urlToken = params.get("token");

      if (urlToken) {
        localStorage.setItem("ugie_token", urlToken);
        // Clean URL without reloading
        window.history.replaceState({}, document.title, "/");
        setToken(urlToken);
      } else {
        setToken(localStorage.getItem("ugie_token"));
      }
    }
  }, []);

  useEffect(() => {
    if (token) {
      fetchUser(token);
      fetchRepos(token);
    } else {
      setUser(null);
      setRepos([]);
      setLoading(false); // Set loading to false if no token
    }
  }, [token]);

  const fetchUser = async (authToken: string) => {
    try {
      const res = await fetch("http://localhost:8000/auth/me", {
        headers: { Authorization: `Bearer ${authToken}` },
      });
      if (!res.ok) {
        throw new Error("Failed to fetch user info.");
      }
      const data = await res.json();
      setUser(data.user);
    } catch (err: any) {
      console.error("Error fetching user:", err);
      setError(err.message);
      localStorage.removeItem("ugie_token");
      setToken(null);
    }
  };

  const fetchRepos = async (authToken: string) => {
    setLoading(true);
    setError(null); // Changed to null
    try {
      const res = await fetch("http://localhost:8000/repos?page=1&page_size=100", {
        headers: { Authorization: `Bearer ${authToken}` },
      });
      if (!res.ok) {
        if (res.status === 401) {
          localStorage.removeItem("ugie_token");
          setToken(null);
          setUser(null); // Clear user on 401
        }
        throw new Error("Failed to fetch repositories. Please sign in again.");
      }
      const data = await res.json();
      setRepos(data.repositories || []);
    } catch (err: any) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  const rescanRepos = async () => {
    if (!token) return;
    setLoading(true);
    setError(null); // Changed to null
    try {
      await fetch("http://localhost:8000/repos/rescan", {
        method: "POST",
        headers: { Authorization: `Bearer ${token}` }
      });
      setTimeout(() => fetchRepos(token), 1000);
    } catch (err: any) {
      console.error(err);
      setError("Failed to rescan repositories.");
      setLoading(false);
    }
  };

  const handleLogin = () => {
    window.location.href = "http://localhost:8000/auth/github";
  };

  const handleLogout = () => {
    localStorage.removeItem("ugie_token");
    setToken(null);
    setUser(null); // Clear user on logout
    setRepos([]);
  };

  const ownedRepos = repos.filter(r => r.role === 'owner');
  const collaboratingRepos = repos.filter(r => r.role !== 'owner');

  const filteredRepos = repos.filter(r => {
    if (filter === 'all') return true;
    if (filter === 'owned') return r.role === 'owner';
    if (filter === 'collaborating') return r.role !== 'owner';
    return true;
  });

  return (
    <div className="min-h-screen bg-[#0A0A0B] text-white selection:bg-indigo-500/30 font-sans pb-20">
      {/* Dynamic Background */}
      <div className="fixed inset-0 z-0 overflow-hidden pointer-events-none">
        <div className="absolute top-[-20%] left-[-10%] w-[50%] h-[50%] bg-indigo-600/10 blur-[120px] rounded-full mix-blend-screen" />
        <div className="absolute top-[40%] right-[-10%] w-[40%] h-[60%] bg-purple-600/10 blur-[120px] rounded-full mix-blend-screen" />
      </div>

      <div className="relative z-10 max-w-6xl mx-auto px-6 pt-12">
        {/* Header */}
        <header className="flex flex-col sm:flex-row items-center justify-between mb-16 gap-6 animate-in fade-in slide-in-from-top-4 duration-700">
          <div className="flex items-center gap-4">
            <div className="w-12 h-12 rounded-xl bg-gradient-to-br from-indigo-500 to-purple-600 flex items-center justify-center shadow-lg shadow-indigo-500/20">
              <svg className="w-6 h-6 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 10V3L4 14h7v7l9-11h-7z" />
              </svg>
            </div>
            <div>
              <h1 className="text-3xl font-extrabold tracking-tight bg-clip-text text-transparent bg-gradient-to-r from-white to-white/60">UGIE</h1>
              <p className="text-sm text-zinc-400 font-medium">Universal GitHub Intelligence Engine</p>
            </div>
          </div>

          <div className="flex items-center gap-4 bg-white/[0.03] p-1.5 rounded-2xl border border-white/[0.05] backdrop-blur-md">
            {user ? (
              <>
                <div className="flex items-center gap-3 px-3">
                  <img src={user.avatar_url} alt="Profile" className="w-8 h-8 rounded-full ring-2 ring-white/10" />
                  <span className="text-sm font-medium text-zinc-300">{user.login}</span>
                </div>
                <div className="w-px h-6 bg-white/[0.1]" />
                <button
                  onClick={handleLogout}
                  className="px-4 py-2 text-sm font-medium text-zinc-400 hover:text-white transition-colors"
                >
                  Disconnect
                </button>
              </>
            ) : null}
          </div>
        </header>

        {!user && !loading ? (
          <div className="flex flex-col items-center justify-center py-32 animate-in fade-in slide-in-from-bottom-8 duration-700">
            <div className="w-24 h-24 mb-8 relative">
              <div className="absolute inset-0 bg-indigo-500/20 rounded-full blur-xl animate-pulse" />
              <img src="/github-mark-white.svg" alt="GitHub" className="w-full h-full relative z-10 drop-shadow-2xl" />
            </div>
            <h2 className="text-5xl font-extrabold tracking-tight mb-6 text-center">
              Intelligence for your <br />
              <span className="bg-clip-text text-transparent bg-gradient-to-r from-indigo-400 to-purple-500">
                development graph
              </span>
            </h2>
            <p className="text-xl text-zinc-400 mb-10 max-w-2xl text-center leading-relaxed">
              Connect your GitHub account to instantly map your repositories, track contributions, and uncover collaborative analytics.
            </p>
            <button
              onClick={handleLogin}
              className="group relative px-8 py-4 bg-white text-black rounded-full font-bold text-lg hover:scale-105 transition-all duration-300 shadow-[0_0_40px_-10px_rgba(255,255,255,0.3)]"
            >
              <div className="absolute inset-0 bg-gradient-to-r from-indigo-500 to-purple-500 rounded-full opacity-0 group-hover:opacity-10 transition-opacity" />
              <span className="flex items-center gap-3">
                <svg className="w-6 h-6" fill="currentColor" viewBox="0 0 24 24"><path d="M12 0c-6.626 0-12 5.373-12 12 0 5.302 3.438 9.8 8.207 11.387.599.111.793-.261.793-.577v-2.234c-3.338.726-4.033-1.416-4.033-1.416-.546-1.387-1.333-1.756-1.333-1.756-1.089-.745.083-.729.083-.729 1.205.084 1.839 1.237 1.839 1.237 1.07 1.834 2.807 1.304 3.492.997.107-.775.418-1.305.762-1.604-2.665-.305-5.467-1.334-5.467-5.931 0-1.311.469-2.381 1.236-3.221-.124-.303-.535-1.524.117-3.176 0 0 1.008-.322 3.301 1.23.957-.266 1.983-.399 3.003-.404 1.02.005 2.047.138 3.006.404 2.291-1.552 3.297-1.23 3.297-1.23.653 1.653.242 2.874.118 3.176.77.84 1.235 1.911 1.235 3.221 0 4.609-2.807 5.624-5.479 5.921.43.372.823 1.102.823 2.222v3.293c0 .319.192.694.801.576 4.765-1.589 8.199-6.086 8.199-11.386 0-6.627-5.373-12-12-12z" /></svg>
                Connect GitHub
              </span>
            </button>
          </div>
        ) : null}

        {user && (
          <div className="space-y-8 animate-in fade-in slide-in-from-bottom-8 duration-700">
            {/* Project Management Summary Metrics */}
            <div className="grid grid-cols-1 md:grid-cols-3 gap-6 mb-8">
              <div className="bg-white/[0.02] border border-white/[0.05] rounded-2xl p-6 backdrop-blur-sm">
                <div className="text-zinc-400 text-sm font-medium mb-2">Total Managed Projects</div>
                <div className="text-3xl font-bold text-white">{repos.length}</div>
              </div>
              <div className="bg-white/[0.02] border border-white/[0.05] rounded-2xl p-6 backdrop-blur-sm">
                <div className="text-zinc-400 text-sm font-medium mb-2">Owned (Project Manager)</div>
                <div className="text-3xl font-bold text-indigo-400">{ownedRepos.length}</div>
              </div>
              <div className="bg-white/[0.02] border border-white/[0.05] rounded-2xl p-6 backdrop-blur-sm">
                <div className="text-zinc-400 text-sm font-medium mb-2">Collaborating (Project Member)</div>
                <div className="text-3xl font-bold text-purple-400">{collaboratingRepos.length}</div>
              </div>
            </div>

            <div className="flex flex-col sm:flex-row sm:justify-between sm:items-center gap-4 pb-6 border-b border-white/[0.08]">
              <div>
                <h2 className="text-3xl font-bold tracking-tight text-white mb-2">Project Portfolio</h2>
                <p className="text-zinc-400">Manage and monitor all your GitHub repositories.</p>
              </div>
              <div className="flex items-center gap-3 bg-white/[0.03] p-1.5 rounded-xl border border-white/[0.05]">
                <button onClick={() => setFilter('all')} className={`px-4 py-2 rounded-lg text-sm font-medium transition-colors ${filter === 'all' ? 'bg-white/10 text-white' : 'text-zinc-400 hover:text-white'}`}>All</button>
                <button onClick={() => setFilter('owned')} className={`px-4 py-2 rounded-lg text-sm font-medium transition-colors ${filter === 'owned' ? 'bg-white/10 text-white' : 'text-zinc-400 hover:text-white'}`}>Owned</button>
                <button onClick={() => setFilter('collaborating')} className={`px-4 py-2 rounded-lg text-sm font-medium transition-colors ${filter === 'collaborating' ? 'bg-white/10 text-white' : 'text-zinc-400 hover:text-white'}`}>Collaborating</button>
                <div className="w-px h-6 bg-white/[0.1] mx-1" />
                <button onClick={rescanRepos} disabled={loading} className="p-2 bg-indigo-500/20 hover:bg-indigo-500/30 text-indigo-300 rounded-lg transition-colors border border-indigo-500/20 disabled:opacity-50">
                  <svg className={`w-5 h-5 ${loading ? 'animate-spin' : ''}`} fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" /></svg>
                </button>
              </div>
            </div>

            {error && (
              <div className="p-4 bg-red-900/20 border border-red-500/50 rounded-xl text-red-400 text-sm font-medium">
                {error}
              </div>
            )}

            {loading && repos.length === 0 ? (
              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6 pt-4">
                {[1, 2, 3, 4, 5, 6].map(i => (
                  <div key={i} className="h-48 bg-white/[0.02] border border-white/[0.05] rounded-2xl animate-pulse" />
                ))}
              </div>
            ) : (
              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6 pt-4">
                {filteredRepos.map((repo: Repo) => (
                  <div
                    key={repo.id}
                    onClick={() => router.push(`/repos/${repo.id}`)}
                    className="group bg-white/[0.02] border border-white/[0.05] rounded-3xl p-6 hover:bg-white/[0.04] hover:border-white/[0.1] transition-all duration-300 cursor-pointer relative overflow-hidden flex flex-col h-full"
                  >
                    <div className="absolute top-0 right-0 w-32 h-32 bg-gradient-to-br from-indigo-500/10 to-purple-500/10 blur-2xl group-hover:opacity-100 opacity-50 transition-opacity" />

                    <div className="relative z-10 flex-col h-full flex">
                      <div className="flex justify-between items-start mb-4">
                        <div className="flex items-center gap-3">
                          <svg className="w-6 h-6 text-zinc-500 group-hover:text-indigo-400 transition-colors" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M3 7v10a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-6l-2-2H5a2 2 0 00-2 2z" /></svg>
                          <h3 className="text-xl font-bold text-white truncate max-w-[180px]" title={repo.name}>{repo.name}</h3>
                        </div>
                        <a
                          href={`https://github.com/${repo.full_name}`}
                          target="_blank"
                          rel="noreferrer"
                          onClick={(e) => e.stopPropagation()}
                          className="p-1.5 text-zinc-500 hover:text-white bg-white/[0.05] hover:bg-white/[0.1] rounded-lg transition-colors"
                          title="View on GitHub"
                        >
                          <svg className="w-4 h-4" fill="currentColor" viewBox="0 0 24 24"><path d="M12 0c-6.626 0-12 5.373-12 12 0 5.302 3.438 9.8 8.207 11.387.599.111.793-.261.793-.577v-2.234c-3.338.726-4.033-1.416-4.033-1.416-.546-1.387-1.333-1.756-1.333-1.756-1.089-.745.083-.729.083-.729 1.205.084 1.839 1.237 1.839 1.237 1.07 1.834 2.807 1.304 3.492.997.107-.775.418-1.305.762-1.604-2.665-.305-5.467-1.334-5.467-5.931 0-1.311.469-2.381 1.236-3.221-.124-.303-.535-1.524.117-3.176 0 0 1.008-.322 3.301 1.23.957-.266 1.983-.399 3.003-.404 1.02.005 2.047.138 3.006.404 2.291-1.552 3.297-1.23 3.297-1.23.653 1.653.242 2.874.118 3.176.77.84 1.235 1.911 1.235 3.221 0 4.609-2.807 5.624-5.479 5.921.43.372.823 1.102.823 2.222v3.293c0 .319.192.694.801.576 4.765-1.589 8.199-6.086 8.199-11.386 0-6.627-5.373-12-12-12z" /></svg>
                        </a>
                      </div>

                      <p className="text-sm text-zinc-400 mb-6 font-medium break-all">{repo.full_name}</p>

                      <div className="mt-auto flex items-center justify-between">
                        <div className="flex items-center gap-2">
                          {repo.role === 'owner' ? (
                            <span className="px-2.5 py-1 text-xs font-semibold bg-indigo-500/10 text-indigo-400 border border-indigo-500/20 rounded-md">Manager</span>
                          ) : (
                            <span className="px-2.5 py-1 text-xs font-semibold bg-purple-500/10 text-purple-400 border border-purple-500/20 rounded-md">Member</span>
                          )}
                          {repo.language && (
                            <span className="px-2.5 py-1 text-xs font-medium bg-zinc-800 text-zinc-300 rounded-md border border-white/[0.05]">{repo.language}</span>
                          )}
                        </div>
                        <div className="flex items-center gap-3 text-sm font-medium text-zinc-500">
                          <span className="flex items-center gap-1.5" title="Stars"><svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M11.049 2.927c.3-.921 1.603-.921 1.902 0l1.519 4.674a1 1 0 00.95.69h4.915c.969 0 1.371 1.24.588 1.81l-3.976 2.888a1 1 0 00-.363 1.118l1.518 4.674c.3.922-.755 1.688-1.538 1.118l-3.976-2.888a1 1 0 00-1.176 0l-3.976 2.888c-.783.57-1.838-.197-1.538-1.118l1.518-4.674a1 1 0 00-.363-1.118l-3.976-2.888c-.784-.57-.38-1.81.588-1.81h4.914a1 1 0 00.951-.69l1.519-4.674z" /></svg>{repo.stargazers_count}</span>
                          <span className="flex items-center gap-1.5 text-blue-400/80" title="Open Issues"><svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" /></svg>{repo.open_issues_count}</span>
                        </div>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

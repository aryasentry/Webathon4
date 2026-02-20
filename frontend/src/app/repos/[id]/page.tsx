"use client";

import { useEffect, useState, use, useCallback } from "react";
import { useRouter } from "next/navigation";

// Types
interface Repository {
    id: string;
    name: string;
    full_name: string;
    private: boolean;
    language?: string;
    stargazers_count: number;
    open_issues_count: number;
    role: string;
    last_synced_at?: string;
    backfill_complete: boolean;
}

interface Commit {
    id: string;
    sha: string;
    message: string;
    author_login?: string;
    authored_at: string;
    additions: number;
    deletions: number;
    files_changed: number;
}

interface Issue {
    id: string;
    number: number;
    title: string;
    state: string;
    author_login?: string;
    assignee_login?: string;
    comments_count: number;
    created_at: string;
}

interface PullRequest {
    id: string;
    number: number;
    title: string;
    state: string;
    author_login?: string;
    merged: boolean;
    additions: number;
    deletions: number;
    changed_files: number;
    created_at: string;
    merged_at?: string;
}

interface Collaborator {
    login: string;
    github_id?: number;
    avatar_url?: string;
    name?: string;
    permission: string;          // read | triage | write | maintain | admin
    role_name?: string;
    is_site_user: boolean;
    site_user_id?: string;
    commits: number;
    assigned_issues: number;
    closed_issues: number;
    opened_prs: number;
    merged_prs: number;
    fetched_at?: string;
}

interface BoardItem {
    id: string;
    number: number;
    title: string;
    type: "issue" | "pull_request";
    state: string;
    author?: string;
    assignee?: string;
    merged?: boolean;
    updated_at: string;
}

interface BoardData {
    todo: BoardItem[];
    in_progress: BoardItem[];
    review: BoardItem[];
    done: BoardItem[];
}

export default function RepoDetailsPage({ params }: { params: Promise<{ id: string }> }) {
    // Unwrap the params Promise safely (Next.js 15+ convention for dynamic routes)
    const resolvedParams = use(params);
    const repoId = resolvedParams.id;

    const router = useRouter();
    const [repo, setRepo] = useState<Repository | null>(null);
    const [activeTab, setActiveTab] = useState<"commits" | "issues" | "pulls" | "team" | "board">("commits");
    const [loading, setLoading] = useState(true);
    const [syncing, setSyncing] = useState(false);
    const [error, setError] = useState<string | null>(null);

    // Tab Data
    const [commits, setCommits] = useState<Commit[]>([]);
    const [issues, setIssues] = useState<Issue[]>([]);
    const [pulls, setPulls] = useState<PullRequest[]>([]);
    const [collaborators, setCollaborators] = useState<Collaborator[]>([]);
    const [boardData, setBoardData] = useState<BoardData | null>(null);

    // Function to load all data
    const loadData = useCallback(async (showLoading = true) => {
        const token = localStorage.getItem("ugie_token");
        if (!token) {
            router.push("/");
            return;
        }

        if (showLoading) setLoading(true);
        setError(null);

        try {
            const headers = { Authorization: `Bearer ${token}` };

            // 1. Fetch Repo info
            const repoRes = await fetch(`http://localhost:8000/repos/${repoId}`, { headers });
            if (!repoRes.ok) throw new Error("Failed to load repository details.");
            const repoData = await repoRes.json();
            setRepo(repoData);

            // 2. Fetch Commits
            const commitsRes = await fetch(`http://localhost:8000/repos/${repoId}/commits?page_size=30`, { headers });
            if (commitsRes.ok) {
                const cData = await commitsRes.json();
                setCommits(cData.commits || []);
            }

            // 3. Fetch Issues
            const issuesRes = await fetch(`http://localhost:8000/repos/${repoId}/issues?page_size=30`, { headers });
            if (issuesRes.ok) {
                const iData = await issuesRes.json();
                setIssues(iData.issues || []);
            }

            // 4. Fetch Pull Requests
            const pullsRes = await fetch(`http://localhost:8000/repos/${repoId}/pulls?page_size=30`, { headers });
            if (pullsRes.ok) {
                const pData = await pullsRes.json();
                setPulls(pData.pull_requests || []);
            }

            // 5. Fetch Collaborators (Team Tab)
            const teamRes = await fetch(`http://localhost:8000/repos/${repoId}/collaboration/collaborators`, { headers });
            if (teamRes.ok) {
                const tData = await teamRes.json();
                setCollaborators(tData);
            }

            // 6. Fetch Board Data
            const boardRes = await fetch(`http://localhost:8000/repos/${repoId}/collaboration/board`, { headers });
            if (boardRes.ok) {
                const bData = await boardRes.json();
                setBoardData(bData);
            }

        } catch (err: any) {
            setError(err.message);
        } finally {
            if (showLoading) setLoading(false);
        }
    }, [repoId, router]);

    // Initial load and Deep Sync trigger
    useEffect(() => {
        let mounted = true;

        async function init() {
            // Load existing data visually first
            await loadData();

            // Fire Deep Sync in the background automatically (as requested)
            const token = localStorage.getItem("ugie_token");
            if (token) {
                try {
                    setSyncing(true);
                    await fetch(`http://localhost:8000/repos/${repoId}/rescan`, {
                        method: "POST",
                        headers: { Authorization: `Bearer ${token}` }
                    });
                    // After 2 seconds, re-fetch data quietly to start showing incoming deep sync results
                    setTimeout(() => {
                        if (mounted) loadData(false);
                    }, 2000);
                } catch (e) {
                    console.error("Deep sync trigger failed", e);
                } finally {
                    if (mounted) setSyncing(false);
                }
            }
        }
        init();

        // Polling mechanism every 10 seconds to show dynamic updates as background worker processes
        const pollInterval = setInterval(() => {
            loadData(false);
        }, 10000);

        return () => {
            mounted = false;
            clearInterval(pollInterval);
        };
    }, [loadData, repoId]);


    if (loading) {
        return (
            <div className="min-h-screen bg-black text-white flex items-center justify-center">
                <div className="animate-spin h-8 w-8 border-t-2 border-b-2 border-blue-500 rounded-full"></div>
            </div>
        );
    }

    if (error || !repo) {
        return (
            <div className="min-h-screen bg-black text-white flex flex-col items-center justify-center p-8">
                <h2 className="text-xl text-red-400 mb-4">{error || "Repository not found"}</h2>
                <button onClick={() => router.push("/")} className="px-4 py-2 bg-gray-800 rounded-lg hover:bg-gray-700">
                    Back to Dashboard
                </button>
            </div>
        );
    }

    return (
        <div className="min-h-screen bg-black text-white font-sans p-8 pt-20">
            <div className="max-w-6xl mx-auto">

                {/* Header */}
                <div className="flex items-center justify-between mb-8">
                    <div>
                        <button onClick={() => router.push("/")} className="text-gray-400 hover:text-white mb-4 flex items-center gap-2 text-sm transition-colors">
                            &larr; Back to Dashboard
                        </button>
                        <h1 className="text-4xl font-bold tracking-tight bg-clip-text text-transparent bg-gradient-to-r from-blue-400 to-indigo-500">
                            {repo.full_name}
                        </h1>
                        <div className="flex items-center gap-3 mt-3 text-sm text-gray-400">
                            <span className={`px-2 py-0.5 rounded-full text-xs font-medium border ${repo.private ? 'border-amber-900 text-amber-500 bg-amber-900/20' : 'border-emerald-900 text-emerald-400 bg-emerald-900/20'}`}>
                                {repo.private ? "Private" : "Public"}
                            </span>
                            <span>{repo.language || "Unknown Language"}</span>
                            <span>★ {repo.stargazers_count}</span>
                            {syncing && (
                                <span className="flex items-center gap-2 ml-4 text-blue-400 animate-pulse">
                                    <div className="h-2 w-2 bg-blue-500 rounded-full animate-ping"></div>
                                    Deep Sync in progress...
                                </span>
                            )}
                        </div>
                    </div>
                    <button
                        onClick={async () => {
                            if (!repoId) return;
                            const t = localStorage.getItem("ugie_token");
                            if (!t) return;
                            setSyncing(true);
                            try {
                                await fetch(`http://localhost:8000/repos/${repoId}/rescan`, {
                                    method: "POST",
                                    headers: { Authorization: `Bearer ${t}` }
                                });
                                setTimeout(() => loadData(false), 2000);
                            } catch (e) { console.error(e); }
                            finally { setTimeout(() => setSyncing(false), 2000); }
                        }}
                        disabled={syncing}
                        className="px-4 py-2 bg-indigo-500/10 text-indigo-400 font-medium border border-indigo-500/20 rounded-lg text-sm hover:bg-indigo-500/20 transition-colors disabled:opacity-50"
                    >
                        Sync Now
                    </button>
                </div>

                {/* Dynamic Activity Tabs */}
                <div className="border-b border-gray-800 mb-6">
                    <div className="flex gap-6 -mb-px overflow-x-auto pb-2">
                        {["commits", "issues", "pulls", "team", "board"].map((tab) => (
                            <button
                                key={tab}
                                onClick={() => setActiveTab(tab as any)}
                                className={`pb-4 text-sm font-medium transition-colors border-b-2 whitespace-nowrap ${activeTab === tab
                                    ? "border-blue-500 text-blue-400"
                                    : "border-transparent text-gray-500 hover:text-gray-300"
                                    }`}
                            >
                                {tab.charAt(0).toUpperCase() + tab.slice(1).replace("pulls", "Pull Requests").replace("team", "Team").replace("board", "Active Work")}
                                <span className="ml-2 py-0.5 px-2 bg-gray-900 text-xs rounded-full">
                                    {tab === "commits" ? commits.length : tab === "issues" ? issues.length : tab === "pulls" ? pulls.length : tab === "team" ? collaborators.length : boardData ? Object.values(boardData).reduce((a, b) => a + b.length, 0) : 0}
                                </span>
                            </button>
                        ))}
                    </div>
                </div>

                {/* Tab Content Panels */}
                <div className="bg-gray-900/30 border border-gray-800 rounded-xl overflow-hidden backdrop-blur-sm">

                    {/* COMMITS */}
                    {activeTab === "commits" && (
                        <div className="divide-y divide-gray-800/60">
                            {commits.length === 0 ? (
                                <div className="p-8 text-center text-gray-500">No commits recorded yet.</div>
                            ) : (
                                commits.map((c) => (
                                    <div key={c.id} className="p-4 hover:bg-gray-800/40 transition-colors">
                                        <div className="flex justify-between items-start">
                                            <div>
                                                <p className="font-medium text-gray-200">{c.message}</p>
                                                <p className="text-xs text-gray-500 mt-1">
                                                    <span className="text-blue-400">{c.author_login || "Unknown"}</span> committed on {new Date(c.authored_at).toLocaleDateString()}
                                                </p>
                                            </div>
                                            <div className="text-right">
                                                <span className="font-mono text-xs text-gray-500">{c.sha.substring(0, 7)}</span>
                                                <div className="flex gap-2 text-xs mt-1 justify-end">
                                                    <span className="text-emerald-500">+{c.additions}</span>
                                                    <span className="text-red-500">-{c.deletions}</span>
                                                </div>
                                            </div>
                                        </div>
                                    </div>
                                ))
                            )}
                        </div>
                    )}

                    {/* ISSUES */}
                    {activeTab === "issues" && (
                        <div className="divide-y divide-gray-800/60">
                            {issues.length === 0 ? (
                                <div className="p-8 text-center text-gray-500">No issues recorded yet.</div>
                            ) : (
                                issues.map((i) => (
                                    <div key={i.id} className="p-4 hover:bg-gray-800/40 transition-colors">
                                        <div className="flex justify-between items-start">
                                            <div>
                                                <div className="flex items-center gap-2">
                                                    <span className={`h-2 w-2 rounded-full ${i.state === 'open' ? 'bg-emerald-500' : 'bg-purple-500'}`}></span>
                                                    <p className="font-medium text-gray-200">{i.title}</p>
                                                </div>
                                                <p className="text-xs text-gray-500 mt-1">
                                                    #{i.number} opened by <span className="text-blue-400">{i.author_login}</span> on {new Date(i.created_at).toLocaleDateString()}
                                                </p>
                                            </div>
                                            <div className="text-xs text-gray-500 flex items-center gap-1">
                                                💬 {i.comments_count}
                                            </div>
                                        </div>
                                    </div>
                                ))
                            )}
                        </div>
                    )}

                    {/* PULL REQUESTS */}
                    {activeTab === "pulls" && (
                        <div className="divide-y divide-gray-800/60">
                            {pulls.length === 0 ? (
                                <div className="p-8 text-center text-gray-500">No pull requests recorded yet.</div>
                            ) : (
                                pulls.map((p) => (
                                    <div key={p.id} className="p-4 hover:bg-gray-800/40 transition-colors">
                                        <div className="flex justify-between items-start">
                                            <div>
                                                <div className="flex items-center gap-2">
                                                    <span className={`h-2 w-2 rounded-full ${p.merged ? 'bg-purple-500' : p.state === 'open' ? 'bg-emerald-500' : 'bg-red-500'}`}></span>
                                                    <p className="font-medium text-gray-200">{p.title}</p>
                                                </div>
                                                <p className="text-xs text-gray-500 mt-1">
                                                    #{p.number} by <span className="text-blue-400">{p.author_login}</span>
                                                </p>
                                            </div>
                                            <div className="text-right">
                                                <span className={`text-xs px-2 py-1 rounded-md ${p.merged ? 'bg-purple-900/30 text-purple-400' : p.state === 'open' ? 'bg-emerald-900/30 text-emerald-400' : 'bg-gray-800 text-gray-400'}`}>
                                                    {p.merged ? 'Merged' : p.state === 'open' ? 'Open' : 'Closed'}
                                                </span>
                                                {(p.additions > 0 || p.deletions > 0) && (
                                                    <div className="flex gap-2 text-xs mt-2 justify-end">
                                                        <span className="text-emerald-500">+{p.additions}</span>
                                                        <span className="text-red-500">-{p.deletions}</span>
                                                    </div>
                                                )}
                                            </div>
                                        </div>
                                    </div>
                                ))
                            )}
                        </div>
                    )}

                    {/* TEAM — Rich Collaborator Cards */}
                    {activeTab === "team" && (() => {
                        const permColors: Record<string, string> = {
                            admin: "bg-red-500/10 text-red-400 border-red-500/20",
                            maintain: "bg-amber-500/10 text-amber-400 border-amber-500/20",
                            write: "bg-indigo-500/10 text-indigo-400 border-indigo-500/20",
                            triage: "bg-sky-500/10 text-sky-400 border-sky-500/20",
                            read: "bg-zinc-500/10 text-zinc-400 border-zinc-500/20",
                        };
                        return (
                            <div className="p-6">
                                {/* Refresh button */}
                                <div className="flex justify-between items-center mb-6">
                                    <p className="text-sm text-zinc-500">
                                        {collaborators.length > 0
                                            ? `${collaborators.length} collaborator${collaborators.length > 1 ? 's' : ''} with repository access`
                                            : "Fetching collaborators from GitHub..."}
                                    </p>
                                    <button
                                        onClick={async () => {
                                            const t = localStorage.getItem("ugie_token");
                                            if (!t) return;
                                            await fetch(`http://localhost:8000/repos/${repoId}/collaboration/collaborators/refresh`, {
                                                method: "POST",
                                                headers: { Authorization: `Bearer ${t}` }
                                            });
                                            setTimeout(() => loadData(false), 1500);
                                        }}
                                        className="flex items-center gap-2 px-3 py-1.5 text-xs font-medium bg-white/[0.04] border border-white/[0.08] text-zinc-300 rounded-lg hover:bg-white/[0.08] transition-colors"
                                    >
                                        <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" /></svg>
                                        Refresh from GitHub
                                    </button>
                                </div>

                                {collaborators.length === 0 ? (
                                    <div className="flex flex-col items-center justify-center py-16 text-zinc-600">
                                        <svg className="w-10 h-10 mb-3 opacity-40" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M17 20h5v-2a3 3 0 00-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857M7 20H2v-2a3 3 0 015.356-1.857M7 20v-2c0-.656.126-1.283.356-1.857m0 0a5.002 5.002 0 019.288 0M15 7a3 3 0 11-6 0 3 3 0 016 0z" /></svg>
                                        <p className="text-sm font-medium">No collaborators found yet</p>
                                        <p className="text-xs mt-1">Requires admin access to the repository</p>
                                    </div>
                                ) : (
                                    <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
                                        {collaborators.map((member) => (
                                            <div key={member.login} className="bg-white/[0.02] border border-white/[0.07] rounded-2xl p-5 hover:border-white/[0.14] transition-all duration-200 group">
                                                {/* Header row: avatar + name + badges */}
                                                <div className="flex items-start justify-between mb-4">
                                                    <div className="flex items-center gap-3">
                                                        {member.avatar_url ? (
                                                            <img
                                                                src={member.avatar_url}
                                                                alt={member.login}
                                                                className="w-10 h-10 rounded-full ring-2 ring-white/10 group-hover:ring-indigo-500/30 transition-all"
                                                            />
                                                        ) : (
                                                            <div className="w-10 h-10 rounded-full bg-gradient-to-br from-indigo-500 to-purple-600 flex items-center justify-center text-white font-bold text-sm uppercase">
                                                                {member.login.substring(0, 2)}
                                                            </div>
                                                        )}
                                                        <div>
                                                            <p className="font-semibold text-white text-sm leading-tight">{member.name || member.login}</p>
                                                            {member.name && (
                                                                <p className="text-xs text-zinc-500 mt-0.5">@{member.login}</p>
                                                            )}
                                                        </div>
                                                    </div>
                                                    <div className="flex flex-col items-end gap-1.5 shrink-0 ml-2">
                                                        {/* Permission badge */}
                                                        <span className={`px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider border rounded-md ${permColors[member.permission] || permColors.read}`}>
                                                            {member.permission}
                                                        </span>
                                                        {/* On-UGIE badge */}
                                                        {member.is_site_user && (
                                                            <span className="flex items-center gap-1 px-2 py-0.5 text-[10px] font-semibold bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 rounded-md">
                                                                <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
                                                                On UGIE
                                                            </span>
                                                        )}
                                                    </div>
                                                </div>

                                                {/* Stats row */}
                                                <div className="grid grid-cols-3 gap-2 pt-4 border-t border-white/[0.06]">
                                                    <div className="text-center">
                                                        <p className="text-lg font-bold text-white">{member.commits}</p>
                                                        <p className="text-[10px] text-zinc-500 font-medium mt-0.5">Commits</p>
                                                    </div>
                                                    <div className="text-center border-x border-white/[0.06]">
                                                        <p className="text-lg font-bold text-purple-400">{member.merged_prs}</p>
                                                        <p className="text-[10px] text-zinc-500 font-medium mt-0.5">PRs Merged</p>
                                                    </div>
                                                    <div className="text-center">
                                                        <p className="text-lg font-bold text-emerald-400">{member.closed_issues}</p>
                                                        <p className="text-[10px] text-zinc-500 font-medium mt-0.5">Issues Closed</p>
                                                    </div>
                                                </div>

                                                {/* GitHub link */}
                                                <a
                                                    href={`https://github.com/${member.login}`}
                                                    target="_blank"
                                                    rel="noreferrer"
                                                    className="mt-3 flex items-center gap-2 text-xs text-zinc-600 hover:text-zinc-300 transition-colors"
                                                >
                                                    <svg className="w-3.5 h-3.5 shrink-0" fill="currentColor" viewBox="0 0 24 24"><path d="M12 0c-6.626 0-12 5.373-12 12 0 5.302 3.438 9.8 8.207 11.387.599.111.793-.261.793-.577v-2.234c-3.338.726-4.033-1.416-4.033-1.416-.546-1.387-1.333-1.756-1.333-1.756-1.089-.745.083-.729.083-.729 1.205.084 1.839 1.237 1.839 1.237 1.07 1.834 2.807 1.304 3.492.997.107-.775.418-1.305.762-1.604-2.665-.305-5.467-1.334-5.467-5.931 0-1.311.469-2.381 1.236-3.221-.124-.303-.535-1.524.117-3.176 0 0 1.008-.322 3.301 1.23.957-.266 1.983-.399 3.003-.404 1.02.005 2.047.138 3.006.404 2.291-1.552 3.297-1.23 3.297-1.23.653 1.653.242 2.874.118 3.176.77.84 1.235 1.911 1.235 3.221 0 4.609-2.807 5.624-5.479 5.921.43.372.823 1.102.823 2.222v3.293c0 .319.192.694.801.576 4.765-1.589 8.199-6.086 8.199-11.386 0-6.627-5.373-12-12-12z" /></svg>
                                                    github.com/{member.login}
                                                </a>
                                            </div>
                                        ))}
                                    </div>
                                )}
                            </div>
                        );
                    })()}

                    {/* ACTIVE WORK KANBAN BOARD */}
                    {activeTab === "board" && (
                        <div className="p-6 bg-[#0E0E11]">
                            {!boardData ? (
                                <div className="p-8 text-center text-gray-500">No active work items fetched.</div>
                            ) : (
                                <div className="flex gap-6 overflow-x-auto pb-4 snap-x">
                                    {/* Kanban Columns */}
                                    {[
                                        { key: "todo", title: "To Do", icon: "📋", color: "text-zinc-400" },
                                        { key: "in_progress", title: "In Progress", icon: "🚧", color: "text-amber-500" },
                                        { key: "review", title: "In Review (PRs)", icon: "👀", color: "text-blue-400" },
                                        { key: "done", title: "Done", icon: "✅", color: "text-emerald-500" }
                                    ].map((column) => (
                                        <div key={column.key} className="flex-none w-80 flex flex-col snap-start">
                                            <div className="flex items-center justify-between mb-4 px-1">
                                                <div className="flex items-center gap-2">
                                                    <span>{column.icon}</span>
                                                    <h3 className={`font-semibold text-sm tracking-wide ${column.color}`}>{column.title}</h3>
                                                </div>
                                                <span className="text-xs font-medium px-2 py-1 bg-white/[0.05] rounded-full text-zinc-500">
                                                    {(boardData as any)[column.key]?.length || 0}
                                                </span>
                                            </div>
                                            <div className="flex-1 flex flex-col gap-3 min-h-[400px] bg-white/[0.02] rounded-xl p-3 border border-white/[0.05]">
                                                {((boardData as any)[column.key] || []).map((item: BoardItem) => (
                                                    <div key={item.id} className="bg-[#18181B] p-4 rounded-lg border border-white/[0.08] hover:border-white/[0.15] transition-colors shadow-sm group">
                                                        <div className="flex justify-between items-start mb-3 gap-2">
                                                            <div className="flex items-center gap-2">
                                                                {item.type === 'issue' ? (
                                                                    <svg className="w-4 h-4 text-emerald-500 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" /></svg>
                                                                ) : (
                                                                    <svg className="w-4 h-4 text-purple-500 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 7v8a2 2 0 002 2h6M8 7V5a2 2 0 012-2h4.586a1 1 0 01.707.293l4.414 4.414a1 1 0 01.293.707V15a2 2 0 01-2 2h-2M8 7H6a2 2 0 00-2 2v10a2 2 0 002 2h8a2 2 0 002-2v-2" /></svg>
                                                                )}
                                                                <span className="text-xs font-medium text-zinc-500">#{item.number}</span>
                                                            </div>
                                                            {item.assignee && (
                                                                <div className="w-6 h-6 rounded-full bg-gradient-to-br from-indigo-500 to-purple-600 flex items-center justify-center text-[10px] font-bold text-white shadow" title={`Assigned to ${item.assignee}`}>
                                                                    {item.assignee.substring(0, 2).toUpperCase()}
                                                                </div>
                                                            )}
                                                        </div>
                                                        <h4 className="text-sm font-medium text-zinc-200 leading-snug line-clamp-2 mb-3">{item.title}</h4>
                                                        <div className="flex justify-between items-center text-xs text-zinc-500">
                                                            <span className="truncate max-w-[120px]">{item.author || "Unknown"}</span>
                                                            <span className="shrink-0">{new Date(item.updated_at).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })}</span>
                                                        </div>
                                                    </div>
                                                ))}
                                                {((boardData as any)[column.key]?.length === 0) && (
                                                    <div className="flex-1 flex items-center justify-center text-zinc-600 text-sm font-medium border-2 border-dashed border-white/[0.05] rounded-lg">
                                                        Empty
                                                    </div>
                                                )}
                                            </div>
                                        </div>
                                    ))}
                                </div>
                            )}
                        </div>
                    )}

                </div>
            </div>
        </div>
    );
}

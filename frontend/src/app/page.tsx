"use client";

import { useState, useEffect } from "react";
import { useSession, signIn, signOut } from "next-auth/react";

interface StatusResponse {
  database: string;
  redis: string;
  celery: {
    status: string;
    task_id: string;
  } | string;
}

interface HelloResponse {
  message: string;
  status: string;
}

export default function Home() {
  const [helloData, setHelloData] = useState<HelloResponse | null>(null);
  const [helloLoading, setHelloLoading] = useState(false);
  const [helloError, setHelloError] = useState<string | null>(null);

  const [statusData, setStatusData] = useState<StatusResponse | null>(null);
  const [statusLoading, setStatusLoading] = useState(false);
  const [statusError, setStatusError] = useState<string | null>(null);

  const [triggeringTask, setTriggeringTask] = useState(false);
  const [taskResult, setTaskResult] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<"dev" | "prod">("dev");

  // NextAuth state
  const { data: session, status: sessionStatus } = useSession();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [loginLoading, setLoginLoading] = useState(false);
  const [loginError, setLoginError] = useState<string | null>(null);

  // Fetch hello world API
  const fetchHello = async () => {
    setHelloLoading(true);
    setHelloError(null);
    try {
      const apiUrl = process.env.NEXT_PUBLIC_API_URL || "/api";
      const res = await fetch(`${apiUrl}/hello/`);
      if (!res.ok) throw new Error(`HTTP error! status: ${res.status}`);
      const data = await res.json();
      setHelloData(data);
    } catch (err: any) {
      console.error(err);
      setHelloError(err.message || "Failed to connect to backend API");
    } finally {
      setHelloLoading(false);
    }
  };

  // Fetch health status
  const fetchStatus = async () => {
    setStatusLoading(true);
    setStatusError(null);
    try {
      const apiUrl = process.env.NEXT_PUBLIC_API_URL || "/api";
      const res = await fetch(`${apiUrl}/status/`);
      if (!res.ok) throw new Error(`HTTP error! status: ${res.status}`);
      const data = await res.json();
      setStatusData(data);
    } catch (err: any) {
      console.error(err);
      setStatusError(err.message || "Failed to fetch system status");
    } finally {
      setStatusLoading(false);
    }
  };

  // Trigger Celery task
  const triggerCelery = async () => {
    setTriggeringTask(true);
    setTaskResult(null);
    try {
      const apiUrl = process.env.NEXT_PUBLIC_API_URL || "/api";
      const res = await fetch(`${apiUrl}/status/`);
      if (!res.ok) throw new Error(`HTTP error! status: ${res.status}`);
      const data: StatusResponse = await res.json();
      setStatusData(data);
      
      if (typeof data.celery === "object" && data.celery.task_id) {
        setTaskResult(`Task triggered! Task ID: ${data.celery.task_id}. Check worker logs to see it complete in 2 seconds.`);
      } else {
        setTaskResult("Failed to trigger Celery task.");
      }
    } catch (err: any) {
      setTaskResult(`Error: ${err.message}`);
    } finally {
      setTriggeringTask(false);
    }
  };

  // Handle Login form submission
  const handleLogin = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoginLoading(true);
    setLoginError(null);
    try {
      const res = await signIn("credentials", {
        username,
        password,
        redirect: false,
      });
      if (res?.error) {
        setLoginError("Invalid username or password, or server connection issue.");
      } else {
        setUsername("");
        setPassword("");
      }
    } catch (err: any) {
      setLoginError(err.message || "An unexpected error occurred.");
    } finally {
      setLoginLoading(false);
    }
  };

  useEffect(() => {
    fetchHello();
    fetchStatus();
  }, []);

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 font-sans relative overflow-hidden pb-16">
      {/* Decorative Background Blobs */}
      <div className="absolute top-[-10%] left-[-10%] w-[50%] h-[50%] rounded-full bg-indigo-500/10 blur-[120px] pointer-events-none" />
      <div className="absolute bottom-[20%] right-[-10%] w-[60%] h-[60%] rounded-full bg-violet-600/10 blur-[150px] pointer-events-none" />

      {/* Main Container */}
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 pt-12 relative z-10">
        
        {/* Header */}
        <header className="text-center mb-12">
          <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-indigo-500/10 border border-indigo-500/20 text-indigo-400 text-sm font-medium mb-4 backdrop-blur-sm">
            <span className="w-2 h-2 rounded-full bg-indigo-400 animate-pulse" />
            Next.js + Django Template
          </div>
          <h1 className="text-4xl sm:text-5xl font-extrabold tracking-tight bg-gradient-to-r from-white via-slate-200 to-indigo-400 bg-clip-text text-transparent mb-4">
            Full-Stack Dockerized Template
          </h1>
          <p className="max-w-2xl mx-auto text-lg text-slate-400">
            A production-ready blueprint featuring Django, Next.js, PostgreSQL, Redis, Celery, and Caddy.
          </p>

          {/* Tech Badges with OpenAPI Swagger Link */}
          <div className="flex flex-wrap justify-center gap-2 mt-6">
            {["Next.js", "Django", "PostgreSQL", "Redis", "Celery", "Caddy", "Tailwind CSS", "TypeScript"].map((tech) => (
              <span
                key={tech}
                className="px-3 py-1 rounded-md text-xs font-semibold bg-slate-900 border border-slate-800 text-slate-300 hover:border-slate-700 transition"
              >
                {tech}
              </span>
            ))}
            <a
              href="/api/docs/"
              target="_blank"
              rel="noopener noreferrer"
              className="px-3 py-1 rounded-md text-xs font-semibold bg-indigo-900/50 border border-indigo-500/30 text-indigo-300 hover:border-indigo-400 hover:bg-indigo-900 transition flex items-center gap-1 cursor-pointer"
            >
              <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 6.253v13m0-13C10.832 5.477 9.246 5 7.5 5S4.168 5.477 3 6.253v13C4.168 18.477 5.754 18 7.5 18s3.332.477 4.5 1.253m0-13C13.168 5.477 14.754 5 16.5 5c1.747 0 3.332.477 4.5 1.253v13C19.832 18.477 18.247 18 16.5 18c-1.746 0-3.332.477-4.5 1.253" />
              </svg>
              Interactive API Docs (Swagger)
            </a>
          </div>
        </header>

        {/* Dashboard Grid */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-8 mb-12">
          
          {/* Column 1: API Connections & Auth */}
          <div className="space-y-8 lg:col-span-2">
            
            {/* Hello World Card */}
            <div className="rounded-2xl border border-slate-800 bg-slate-900/50 backdrop-blur-md p-6 relative overflow-hidden">
              <div className="absolute top-0 right-0 p-3 opacity-10">
                <svg className="w-24 h-24 text-indigo-500" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1} d="M8 9l3 3-3 3m5 0h3M5 20h14a2 2 0 002-2V6a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z" />
                </svg>
              </div>

              <div className="flex items-center justify-between mb-4">
                <h2 className="text-xl font-bold text-slate-100 flex items-center gap-2">
                  <span className="text-indigo-400">01.</span> Hello World API
                </h2>
                <button
                  onClick={fetchHello}
                  disabled={helloLoading}
                  className="px-3 py-1 rounded bg-indigo-600 hover:bg-indigo-500 disabled:bg-indigo-800 text-xs font-medium transition cursor-pointer"
                >
                  {helloLoading ? "Fetching..." : "Test Connection"}
                </button>
              </div>
              <p className="text-sm text-slate-400 mb-4">
                Fetches message from Django API endpoint <code className="text-indigo-300 bg-slate-950 px-1.5 py-0.5 rounded text-xs">/api/hello/</code>
              </p>

              {/* Response Block */}
              <div className="rounded-lg bg-slate-950/80 border border-slate-900 p-4 font-mono text-sm min-h-[80px] flex items-center justify-center relative">
                {helloLoading ? (
                  <div className="flex items-center gap-2 text-slate-500">
                    <svg className="animate-spin h-5 w-5 text-indigo-500" viewBox="0 0 24 24" fill="none">
                      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
                    </svg>
                    <span>Fetching response...</span>
                  </div>
                ) : helloError ? (
                  <div className="text-rose-400 w-full">
                    <p className="font-bold">Connection Error:</p>
                    <p className="text-xs mt-1 text-rose-500">{helloError}</p>
                    <p className="text-xs mt-2 text-slate-500 font-sans">
                      Tip: Ensure Docker containers are running (<code className="bg-slate-900 px-1 py-0.5 rounded">docker compose up</code>).
                    </p>
                  </div>
                ) : helloData ? (
                  <div className="w-full">
                    <div className="text-emerald-400 font-semibold mb-1">Status: {helloData.status}</div>
                    <div className="text-indigo-200">{JSON.stringify(helloData, null, 2)}</div>
                  </div>
                ) : (
                  <span className="text-slate-600">No response fetched yet. Click Test Connection.</span>
                )}
              </div>
            </div>

            {/* System Health Dashboard */}
            <div className="rounded-2xl border border-slate-800 bg-slate-900/50 backdrop-blur-md p-6">
              <div className="flex items-center justify-between mb-4">
                <h2 className="text-xl font-bold text-slate-100 flex items-center gap-2">
                  <span className="text-indigo-400">02.</span> System Services Health
                </h2>
                <button
                  onClick={fetchStatus}
                  disabled={statusLoading}
                  className="px-3 py-1 rounded bg-slate-800 hover:bg-slate-700 disabled:bg-slate-900 text-xs font-medium transition cursor-pointer"
                >
                  {statusLoading ? "Checking..." : "Refresh Status"}
                </button>
              </div>
              <p className="text-sm text-slate-400 mb-6">
                Django dynamically checks the active status of core state containers at <code className="text-indigo-300 bg-slate-950 px-1.5 py-0.5 rounded text-xs">/api/status/</code>
              </p>

              {/* Services Health Indicators */}
              <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-6">
                
                {/* Database */}
                <div className="rounded-xl border border-slate-800 bg-slate-950/60 p-4 flex flex-col justify-between">
                  <div className="text-xs text-slate-500 uppercase tracking-wider font-semibold">PostgreSQL Database</div>
                  <div className="flex items-center gap-2 mt-2">
                    {statusLoading ? (
                      <span className="text-sm text-slate-400 animate-pulse">Checking...</span>
                    ) : statusData?.database === "up" ? (
                      <>
                        <span className="w-2.5 h-2.5 rounded-full bg-emerald-500 shadow-[0_0_8px_rgba(16,185,129,0.6)] animate-pulse" />
                        <span className="text-sm font-bold text-emerald-400">Connected</span>
                      </>
                    ) : (
                      <>
                        <span className="w-2.5 h-2.5 rounded-full bg-rose-500 shadow-[0_0_8px_rgba(244,63,94,0.6)]" />
                        <span className="text-sm font-bold text-rose-400">Disconnected</span>
                      </>
                    )}
                  </div>
                </div>

                {/* Redis */}
                <div className="rounded-xl border border-slate-800 bg-slate-950/60 p-4 flex flex-col justify-between">
                  <div className="text-xs text-slate-500 uppercase tracking-wider font-semibold">Redis Cache & Broker</div>
                  <div className="flex items-center gap-2 mt-2">
                    {statusLoading ? (
                      <span className="text-sm text-slate-400 animate-pulse">Checking...</span>
                    ) : statusData?.redis === "up" ? (
                      <>
                        <span className="w-2.5 h-2.5 rounded-full bg-emerald-500 shadow-[0_0_8px_rgba(16,185,129,0.6)] animate-pulse" />
                        <span className="text-sm font-bold text-emerald-400">Connected</span>
                      </>
                    ) : (
                      <>
                        <span className="w-2.5 h-2.5 rounded-full bg-rose-500 shadow-[0_0_8px_rgba(244,63,94,0.6)]" />
                        <span className="text-sm font-bold text-rose-400">Disconnected</span>
                      </>
                    )}
                  </div>
                </div>

                {/* Celery */}
                <div className="rounded-xl border border-slate-800 bg-slate-950/60 p-4 flex flex-col justify-between">
                  <div className="text-xs text-slate-500 uppercase tracking-wider font-semibold">Celery Worker</div>
                  <div className="flex items-center gap-2 mt-2">
                    {statusLoading ? (
                      <span className="text-sm text-slate-400 animate-pulse">Checking...</span>
                    ) : statusData?.celery && typeof statusData.celery === "object" ? (
                      <>
                        <span className="w-2.5 h-2.5 rounded-full bg-violet-500 shadow-[0_0_8px_rgba(139,92,246,0.6)] animate-pulse" />
                        <span className="text-sm font-bold text-violet-400">Worker Active</span>
                      </>
                    ) : (
                      <>
                        <span className="w-2.5 h-2.5 rounded-full bg-slate-600" />
                        <span className="text-sm font-bold text-slate-400">Idle / Off</span>
                      </>
                    )}
                  </div>
                </div>

              </div>

              {/* Celery Task Trigger Section */}
              <div className="p-4 rounded-xl bg-slate-950/80 border border-slate-900">
                <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
                  <div>
                    <h3 className="text-sm font-bold text-slate-200">Asynchronous Celery Tasks</h3>
                    <p className="text-xs text-slate-400 mt-1">
                      Trigger a task to compute on the background worker using Redis as broker.
                    </p>
                  </div>
                  <button
                    onClick={triggerCelery}
                    disabled={triggeringTask}
                    className="self-start sm:self-center px-4 py-2 rounded bg-indigo-600 hover:bg-indigo-500 disabled:bg-indigo-800 text-xs font-bold transition whitespace-nowrap cursor-pointer"
                  >
                    {triggeringTask ? "Triggering..." : "Trigger Background Task"}
                  </button>
                </div>

                {taskResult && (
                  <div className="mt-4 p-3 rounded bg-slate-900 border border-slate-800 text-xs font-mono text-indigo-300">
                    {taskResult}
                  </div>
                )}
              </div>

            </div>

            {/* JWT Authentication Card */}
            <div className="rounded-2xl border border-slate-800 bg-slate-900/50 backdrop-blur-md p-6 relative overflow-hidden">
              <div className="absolute top-0 right-0 p-3 opacity-10">
                <svg className="w-24 h-24 text-indigo-500" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1} d="M15 7a2 2 0 012 2m4 0a6 6 0 01-7.743 5.743L11 17H9v2H7v2H4a1 1 0 01-1-1v-2.586a1 1 0 01.293-.707l5.964-5.964A6 6 0 1121 9z" />
                </svg>
              </div>

              <h2 className="text-xl font-bold text-slate-100 flex items-center gap-2 mb-2">
                <span className="text-indigo-400">03.</span> JWT Authentication (NextAuth.js)
              </h2>
              <p className="text-sm text-slate-400 mb-6">
                Django generates JWT tokens using <code className="text-indigo-300 bg-slate-950 px-1.5 py-0.5 rounded text-xs">django-rest-framework-simplejwt</code>, which NextAuth.js securely manages inside HTTP-only cookies.
              </p>

              {sessionStatus === "loading" ? (
                <div className="flex items-center gap-2 text-slate-500 font-mono text-sm py-4">
                  <svg className="animate-spin h-5 w-5 text-indigo-500" viewBox="0 0 24 24" fill="none">
                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
                  </svg>
                  <span>Loading session state...</span>
                </div>
              ) : session ? (
                /* Authenticated UI */
                <div className="space-y-6">
                  <div className="flex items-center justify-between p-4 rounded-xl bg-slate-950/60 border border-slate-800">
                    <div>
                      <div className="text-xs text-slate-500 uppercase tracking-wider font-semibold">Logged in as</div>
                      <div className="text-sm font-bold text-slate-200 mt-0.5">{session.username || session.user?.name}</div>
                    </div>
                    <button
                      onClick={() => signOut({ redirect: false })}
                      className="px-3 py-1.5 rounded bg-slate-800 hover:bg-slate-700 text-xs font-semibold transition cursor-pointer"
                    >
                      Sign Out
                    </button>
                  </div>

                  <div className="space-y-3">
                    <div>
                      <span className="text-xs font-bold text-indigo-400 uppercase tracking-wide">Access Token (Truncated)</span>
                      <div className="mt-1 p-3 bg-slate-950 rounded border border-slate-900 font-mono text-[11px] text-indigo-200 break-all select-all">
                        {session.accessToken ? `${session.accessToken.substring(0, 80)}... [${session.accessToken.length} chars]` : "Not found"}
                      </div>
                    </div>
                    <div>
                      <span className="text-xs font-bold text-indigo-400 uppercase tracking-wide">Refresh Token (Truncated)</span>
                      <div className="mt-1 p-3 bg-slate-950 rounded border border-slate-900 font-mono text-[11px] text-slate-400 break-all select-all">
                        {session.refreshToken ? `${session.refreshToken.substring(0, 80)}... [${session.refreshToken.length} chars]` : "Not found"}
                      </div>
                    </div>
                  </div>
                </div>
              ) : (
                /* Guest UI / Login Form */
                <div className="space-y-6">
                  <form onSubmit={handleLogin} className="space-y-4">
                    <div>
                      <label className="block text-xs font-bold text-slate-400 uppercase tracking-wide mb-1">Username</label>
                      <input
                        type="text"
                        value={username}
                        onChange={(e) => setUsername(e.target.value)}
                        placeholder="e.g. admin"
                        required
                        className="w-full bg-slate-950 border border-slate-800 rounded px-3 py-2 text-sm text-slate-200 placeholder-slate-600 focus:outline-none focus:border-indigo-500 transition"
                      />
                    </div>
                    <div>
                      <label className="block text-xs font-bold text-slate-400 uppercase tracking-wide mb-1">Password</label>
                      <input
                        type="password"
                        value={password}
                        onChange={(e) => setPassword(e.target.value)}
                        placeholder="••••••••"
                        required
                        className="w-full bg-slate-950 border border-slate-800 rounded px-3 py-2 text-sm text-slate-200 placeholder-slate-600 focus:outline-none focus:border-indigo-500 transition"
                      />
                    </div>

                    {loginError && (
                      <div className="p-3 rounded bg-rose-950/30 border border-rose-800/50 text-rose-400 text-xs font-semibold">
                        {loginError}
                      </div>
                    )}

                    <button
                      type="submit"
                      disabled={loginLoading}
                      className="w-full py-2.5 rounded bg-indigo-600 hover:bg-indigo-500 disabled:bg-indigo-800 text-sm font-bold transition flex items-center justify-center gap-2 cursor-pointer"
                    >
                      {loginLoading && (
                        <svg className="animate-spin h-4 w-4 text-white" viewBox="0 0 24 24" fill="none">
                          <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                          <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
                        </svg>
                      )}
                      {loginLoading ? "Authenticating..." : "Sign In with credentials"}
                    </button>
                  </form>

                  <div className="p-4 rounded-xl bg-indigo-950/20 border border-indigo-900/30 text-xs text-indigo-300">
                    <p className="font-bold flex items-center gap-1.5 mb-1 text-indigo-200 font-sans">
                      <svg className="w-4 h-4 text-indigo-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                      </svg>
                      How to Authenticate:
                    </p>
                    <p className="leading-relaxed font-sans">
                      First create a Django superuser inside the running backend container:
                      <code className="block mt-1.5 p-2 bg-slate-950 rounded border border-slate-900 font-mono text-[10px] text-slate-300 select-all">
                        docker compose exec backend python manage.py createsuperuser
                      </code>
                    </p>
                  </div>
                </div>
              )}
            </div>

          </div>

          {/* Column 2: Architecture & Specs */}
          <div className="space-y-8">
            
            {/* Architecture Card */}
            <div className="rounded-2xl border border-slate-800 bg-slate-900/50 backdrop-blur-md p-6">
              <h2 className="text-xl font-bold text-slate-100 mb-4">
                Architecture Flow
              </h2>
              
              <div className="relative border-l-2 border-slate-800 pl-4 ml-2 py-2 space-y-6">
                
                {/* Step 1 */}
                <div className="relative">
                  <div className="absolute left-[-25px] top-1.5 w-4.5 h-4.5 rounded-full bg-slate-900 border-2 border-indigo-500 flex items-center justify-center text-[10px] font-bold text-indigo-400">
                    1
                  </div>
                  <h4 className="text-sm font-bold text-slate-200">Client Entry Point (Caddy)</h4>
                  <p className="text-xs text-slate-400 mt-1">
                    Caddy listens on Port 80, routing <code className="text-indigo-400">/api/*</code> requests to Django and everything else to Next.js.
                  </p>
                </div>

                {/* Step 2 */}
                <div className="relative">
                  <div className="absolute left-[-25px] top-1.5 w-4.5 h-4.5 rounded-full bg-slate-900 border-2 border-indigo-500 flex items-center justify-center text-[10px] font-bold text-indigo-400">
                    2
                  </div>
                  <h4 className="text-sm font-bold text-slate-200">Next.js Frontend (Port 3000)</h4>
                  <p className="text-xs text-slate-400 mt-1">
                    Compiled with TypeScript and Tailwind CSS v4. Leverages multi-stage Docker builds and standalone output.
                  </p>
                </div>

                {/* Step 3 */}
                <div className="relative">
                  <div className="absolute left-[-25px] top-1.5 w-4.5 h-4.5 rounded-full bg-slate-900 border-2 border-indigo-500 flex items-center justify-center text-[10px] font-bold text-indigo-400">
                    3
                  </div>
                  <h4 className="text-sm font-bold text-slate-200">Django Backend (Port 8000)</h4>
                  <p className="text-xs text-slate-400 mt-1">
                    Served by Gunicorn (prod) or runserver (dev). Handles DB operations, caching, and celery worker tasks.
                  </p>
                </div>

                {/* Step 4 */}
                <div className="relative">
                  <div className="absolute left-[-25px] top-1.5 w-4.5 h-4.5 rounded-full bg-slate-900 border-2 border-indigo-500 flex items-center justify-center text-[10px] font-bold text-indigo-400">
                    4
                  </div>
                  <h4 className="text-sm font-bold text-slate-200">PostgreSql & Redis Services</h4>
                  <p className="text-xs text-slate-400 mt-1">
                    Persistent Postgres database and high-throughput Redis message broker / caching layers.
                  </p>
                </div>

              </div>
            </div>

            {/* Docker Environment Config */}
            <div className="rounded-2xl border border-slate-800 bg-slate-900/50 backdrop-blur-md p-6">
              <h2 className="text-xl font-bold text-slate-100 mb-4">
                Configuration Files
              </h2>
              
              {/* Tab Header */}
              <div className="flex border-b border-slate-800 mb-4">
                <button
                  onClick={() => setActiveTab("dev")}
                  className={`flex-1 pb-2.5 text-center text-sm font-bold border-b-2 transition cursor-pointer ${
                    activeTab === "dev" ? "border-indigo-500 text-indigo-400" : "border-transparent text-slate-400 hover:text-slate-300"
                  }`}
                >
                  Development
                </button>
                <button
                  onClick={() => setActiveTab("prod")}
                  className={`flex-1 pb-2.5 text-center text-sm font-bold border-b-2 transition cursor-pointer ${
                    activeTab === "prod" ? "border-indigo-500 text-indigo-400" : "border-transparent text-slate-400 hover:text-slate-300"
                  }`}
                >
                  Production
                </button>
              </div>

              {/* Tab Contents */}
              <div className="text-xs space-y-4">
                {activeTab === "dev" ? (
                  <>
                    <p className="text-slate-400">
                      Optimized for rapid feedback, using file watchers, hot-reloading (HMR), and debug mode.
                    </p>
                    <div className="space-y-2">
                      <div className="flex justify-between border-b border-slate-800 pb-1">
                        <span className="text-slate-500">Docker File</span>
                        <span className="font-mono text-slate-300">backend/Dockerfile</span>
                      </div>
                      <div className="flex justify-between border-b border-slate-800 pb-1">
                        <span className="text-slate-500">Compose Config</span>
                        <span className="font-mono text-slate-300">docker-compose.yml</span>
                      </div>
                      <div className="flex justify-between border-b border-slate-800 pb-1">
                        <span className="text-slate-500">Caddy Config</span>
                        <span className="font-mono text-slate-300">caddy/Caddyfile.dev</span>
                      </div>
                      <div className="flex justify-between border-b border-slate-800 pb-1">
                        <span className="text-slate-500">Settings Module</span>
                        <span className="font-mono text-slate-300">core.settings.dev</span>
                      </div>
                    </div>
                  </>
                ) : (
                  <>
                    <p className="text-slate-400">
                      Optimized for speed, low resources, and safety: static compression, multi-stage Node, non-root user.
                    </p>
                    <div className="space-y-2">
                      <div className="flex justify-between border-b border-slate-800 pb-1">
                        <span className="text-slate-500">Docker File</span>
                        <span className="font-mono text-slate-300">backend/Dockerfile.prod</span>
                      </div>
                      <div className="flex justify-between border-b border-slate-800 pb-1">
                        <span className="text-slate-500">Compose Config</span>
                        <span className="font-mono text-slate-300">docker-compose.prod.yml</span>
                      </div>
                      <div className="flex justify-between border-b border-slate-800 pb-1">
                        <span className="text-slate-500">Caddy Config</span>
                        <span className="font-mono text-slate-300">caddy/Caddyfile</span>
                      </div>
                      <div className="flex justify-between border-b border-slate-800 pb-1">
                        <span className="text-slate-500">Settings Module</span>
                        <span className="font-mono text-slate-300">core.settings.prod</span>
                      </div>
                    </div>
                  </>
                )}
              </div>
            </div>

          </div>

        </div>

        {/* Command Reference */}
        <section className="rounded-2xl border border-slate-800 bg-slate-900/30 p-6">
          <h2 className="text-xl font-bold text-slate-100 mb-4">
            Deployment & Commands Reference
          </h2>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6 font-mono text-xs">
            
            {/* Dev Commands */}
            <div className="space-y-3">
              <h4 className="text-indigo-400 font-sans font-bold text-sm uppercase tracking-wide">Development Commands</h4>
              <div className="space-y-2">
                <div>
                  <div className="text-slate-500 mb-1"># Start development environment</div>
                  <div className="bg-slate-950 p-2.5 rounded border border-slate-900 text-slate-300 select-all">
                    docker compose up --build
                  </div>
                </div>
                <div>
                  <div className="text-slate-500 mb-1"># Run migrations manually</div>
                  <div className="bg-slate-950 p-2.5 rounded border border-slate-900 text-slate-300 select-all">
                    docker compose exec backend python manage.py migrate
                  </div>
                </div>
              </div>
            </div>

            {/* Prod Commands */}
            <div className="space-y-3">
              <h4 className="text-indigo-400 font-sans font-bold text-sm uppercase tracking-wide">Production Commands</h4>
              <div className="space-y-2">
                <div>
                  <div className="text-slate-500 mb-1"># Start production containers</div>
                  <div className="bg-slate-950 p-2.5 rounded border border-slate-900 text-slate-300 select-all">
                    docker compose -f docker-compose.prod.yml up -d --build
                  </div>
                </div>
                <div>
                  <div className="text-slate-500 mb-1"># View production container logs</div>
                  <div className="bg-slate-950 p-2.5 rounded border border-slate-900 text-slate-300 select-all">
                    docker compose -f docker-compose.prod.yml logs -f
                  </div>
                </div>
              </div>
            </div>

          </div>
        </section>

      </div>
    </div>
  );
}

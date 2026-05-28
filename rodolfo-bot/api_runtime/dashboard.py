"""Dashboard UI and management routes for the Rodo bot."""

import os
import time
import logging
from pathlib import Path
from aiohttp import web
import tokens as token_mgr

from modules.music.cache.database import get_connection, DB_PATH
from modules.music.cache import get_stats_summary, cleanup_expired
from modules.music.player import _players
from modules.music.cog import get_target_guild

logger = logging.getLogger("rodolfo.api.dashboard")

DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>RODO — Panel de Control</title>
    <link rel="icon" type="image/x-icon" href="/favicon.ico">
    <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;500;600;700;800&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
    <script src="https://cdn.tailwindcss.com"></script>
    <script>
        tailwind.config = {
            theme: {
                extend: {
                    fontFamily: {
                        sans: ['Outfit', 'sans-serif'],
                        mono: ['JetBrains Mono', 'monospace'],
                    },
                }
            }
        }
    </script>
    <style>
        body {
            background: radial-gradient(circle at top right, #1e1b4b, #090514 60%);
            min-height: 100vh;
            color: #e2e8f0;
        }
        .glass {
            background: rgba(17, 12, 34, 0.45);
            backdrop-filter: blur(20px);
            -webkit-backdrop-filter: blur(20px);
            border: 1px solid rgba(255, 255, 255, 0.05);
            box-shadow: 0 8px 32px 0 rgba(0, 0, 0, 0.37);
        }
        .glass-hover:hover {
            border-color: rgba(139, 92, 246, 0.3);
            box-shadow: 0 8px 32px 0 rgba(139, 92, 246, 0.1);
        }
        .text-glow {
            text-shadow: 0 0 10px rgba(167, 139, 250, 0.5);
        }
        .indicator-pulse::after {
            content: '';
            position: absolute;
            width: 100%;
            height: 100%;
            top: 0;
            left: 0;
            border-radius: 50%;
            background: inherit;
            animation: pulse-ring 1.5s cubic-bezier(0.215, 0.610, 0.355, 1) infinite;
        }
        @keyframes pulse-ring {
            0% { transform: scale(0.7); opacity: 1; }
            80%, 100% { transform: scale(2.0); opacity: 0; }
        }
        ::-webkit-scrollbar {
            width: 8px;
            height: 8px;
        }
        ::-webkit-scrollbar-track {
            background: rgba(255, 255, 255, 0.02);
            border-radius: 4px;
        }
        ::-webkit-scrollbar-thumb {
            background: rgba(255, 255, 255, 0.1);
            border-radius: 4px;
        }
        ::-webkit-scrollbar-thumb:hover {
            background: rgba(139, 92, 246, 0.4);
        }
    </style>
</head>
<body class="p-4 md:p-8">

    <!-- LOGIN SCREEN -->
    <div id="login-screen" class="fixed inset-0 z-50 flex items-center justify-center bg-[#090514] bg-opacity-95 p-4 transition-all duration-300">
        <div class="glass w-full max-w-md p-8 rounded-3xl text-center space-y-6">
            <div class="mx-auto w-16 h-16 rounded-2xl bg-violet-600/20 flex items-center justify-center border border-violet-500/30">
                <span class="text-3xl">🎤</span>
            </div>
            <div>
                <h1 class="text-2xl font-bold tracking-tight text-white">Rodolfo Bot</h1>
                <p class="text-violet-300/60 text-sm mt-1">Introduce el Token Maestro para entrar al panel</p>
            </div>
            <div class="space-y-4">
                <input type="password" id="token-input" placeholder="Bearer hrCriwyB..." class="w-full bg-[#110c22] border border-white/10 rounded-xl px-4 py-3 text-center focus:outline-none focus:border-violet-500 text-white font-mono placeholder-white/20">
                <button onclick="attemptLogin()" class="w-full bg-violet-600 hover:bg-violet-500 active:scale-[0.98] transition-all duration-200 text-white font-medium rounded-xl py-3 shadow-lg shadow-violet-500/25">Acceder al Panel</button>
            </div>
            <div id="login-error" class="text-rose-400 text-sm hidden">Token incorrecto o denegado</div>
        </div>
    </div>

    <!-- MAIN CONTAINER -->
    <div id="dashboard-content" class="max-w-7xl mx-auto space-y-6 hidden">
        
        <!-- HEADER -->
        <header class="flex flex-col md:flex-row items-start md:items-center justify-between gap-4 pb-4 border-b border-white/5">
            <div class="flex items-center gap-3">
                <div class="w-12 h-12 rounded-xl bg-violet-600/20 flex items-center justify-center border border-violet-500/30">
                    <span class="text-2xl">🤖</span>
                </div>
                <div>
                    <h1 class="text-2xl font-extrabold text-white tracking-tight flex items-center gap-2">
                        RODO <span class="text-xs bg-violet-600/40 text-violet-200 border border-violet-500/30 px-2 py-0.5 rounded-full font-normal tracking-wide">Control Center</span>
                    </h1>
                    <p class="text-violet-300/40 text-xs">Monitoreo de latencia, caché musical L1/L2/L3 y túneles</p>
                </div>
            </div>
            
            <div class="flex flex-wrap items-center gap-3">
                <div class="glass flex items-center gap-2 px-3 py-1.5 rounded-full text-xs">
                    <div class="w-2.5 h-2.5 rounded-full bg-green-500 relative indicator-pulse"></div>
                    <span class="text-green-300 font-semibold" id="api-status">API OK</span>
                </div>
                <div class="glass flex items-center gap-2 px-3 py-1.5 rounded-full text-xs">
                    <span class="text-violet-300/50">Ping Bot:</span>
                    <span class="text-white font-bold" id="header-ping">-- ms</span>
                </div>
                <button onclick="logout()" class="glass hover:bg-rose-500/10 hover:border-rose-500/30 text-rose-300 px-4 py-1.5 rounded-xl text-xs font-medium transition-all duration-200">Salir</button>
            </div>
        </header>

        <!-- TAB NAVIGATION -->
        <div class="flex border-b border-white/5 gap-6 text-sm font-semibold">
            <button onclick="switchTab('telemetry')" id="tab-btn-telemetry" class="pb-3 text-violet-400 border-b-2 border-violet-500 tracking-tight transition-all duration-200">
                📊 Telemetría y Consola
            </button>
            <button onclick="switchTab('database')" id="tab-btn-database" class="pb-3 text-violet-300/40 hover:text-violet-300 border-b-2 border-transparent tracking-tight transition-all duration-200">
                💾 Base de Datos de Caché
            </button>
        </div>

        <!-- TELEMETRY & CONSOLE TAB -->
        <div id="panel-telemetry" class="space-y-6">
            <!-- STATS GRID -->
            <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
                <!-- Discord Bot Card -->
                <div class="glass rounded-2xl p-5 space-y-4 glass-hover transition-all duration-300">
                    <div class="flex justify-between items-center">
                        <span class="text-xs font-semibold text-violet-300/40 uppercase tracking-wider">Discord Status</span>
                        <span class="text-lg">💬</span>
                    </div>
                    <div class="space-y-1">
                        <div class="text-xl font-bold text-white truncate" id="bot-name">Cargando...</div>
                        <div class="text-xs text-violet-300/60" id="bot-servers">0 servidores activos</div>
                    </div>
                    <div class="pt-2 border-t border-white/5 flex justify-between text-xs text-violet-300/40">
                        <span>Ws Ping</span>
                        <span class="font-bold text-violet-300" id="bot-ping">--</span>
                    </div>
                </div>

                <!-- Ngrok Tunnel Card -->
                <div class="glass rounded-2xl p-5 space-y-4 glass-hover transition-all duration-300">
                    <div class="flex justify-between items-center">
                        <span class="text-xs font-semibold text-violet-300/40 uppercase tracking-wider">Ngrok Tunnel</span>
                        <span class="text-lg">🔗</span>
                    </div>
                    <div class="space-y-1">
                        <div class="text-xl font-bold text-white truncate flex items-center gap-1.5" id="tunnel-status">
                            <span class="text-rose-400">Inactivo</span>
                        </div>
                        <div class="text-xs text-violet-300/60 truncate" id="tunnel-url">Espera de conexión...</div>
                    </div>
                    <div class="pt-2 border-t border-white/5 flex justify-between text-xs text-violet-300/40">
                        <span>Destino</span>
                        <span class="font-bold text-violet-300" id="tunnel-dest">localhost:5000</span>
                    </div>
                </div>

                <!-- Cache Database Card -->
                <div class="glass rounded-2xl p-5 space-y-4 glass-hover transition-all duration-300" onclick="switchTab('database')" class="cursor-pointer">
                    <div class="flex justify-between items-center">
                        <span class="text-xs font-semibold text-violet-300/40 uppercase tracking-wider">Base de Datos</span>
                        <span class="text-lg">💾</span>
                    </div>
                    <div class="space-y-1">
                        <div class="text-xl font-bold text-white" id="cache-size">-- KB</div>
                        <div class="text-xs text-violet-300/60" id="cache-metrics">-- tracks en caché</div>
                    </div>
                    <div class="pt-2 border-t border-white/5 flex justify-between text-xs text-violet-300/40">
                        <span>Queries Guardadas</span>
                        <span class="font-bold text-violet-300" id="cache-queries">--</span>
                    </div>
                </div>

                <!-- Performance Card -->
                <div class="glass rounded-2xl p-5 space-y-4 glass-hover transition-all duration-300">
                    <div class="flex justify-between items-center">
                        <span class="text-xs font-semibold text-violet-300/40 uppercase tracking-wider">Rendimiento (24h)</span>
                        <span class="text-lg">⚡</span>
                    </div>
                    <div class="space-y-1">
                        <div class="text-xl font-bold text-white" id="cache-hit-ratio">--% Hits</div>
                        <div class="text-xs text-violet-300/60" id="cache-events-count">-- transacciones</div>
                    </div>
                    <div class="pt-2 border-t border-white/5 flex justify-between text-xs text-violet-300/40">
                        <span>L1 Hot Streams</span>
                        <span class="font-bold text-violet-300" id="cache-l1-count">--</span>
                    </div>
                </div>
            </div>

            <!-- MAIN GRID: Left (Details & Controls) / Right (Console Logs) -->
            <div class="grid grid-cols-1 lg:grid-cols-12 gap-6">
                <!-- LEFT PANEL (5 cols) -->
                <div class="lg:col-span-5 space-y-6 flex flex-col">
                    <!-- PLAYBACK STATE -->
                    <div class="glass rounded-2xl p-6 space-y-4">
                        <h2 class="text-sm font-bold text-white flex items-center gap-2">
                            <span class="w-1.5 h-1.5 rounded-full bg-violet-500"></span>
                            Reproductores Activos
                        </h2>
                        <div id="active-players-list" class="space-y-3 max-h-[180px] overflow-y-auto pr-1">
                            <div class="text-sm text-violet-300/50 text-center py-4">No hay servidores reproduciendo música.</div>
                        </div>
                    </div>

                    <!-- USERS AND SPOTIFY -->
                    <div class="glass rounded-2xl p-6 space-y-4 flex-1">
                        <h2 class="text-sm font-bold text-white flex items-center gap-2">
                            <span class="w-1.5 h-1.5 rounded-full bg-violet-500"></span>
                            Amigos Registrados (OAuth)
                        </h2>
                        <div id="users-list" class="space-y-3 overflow-y-auto pr-1">
                            <div class="text-sm text-violet-300/50 text-center py-4">Cargando usuarios...</div>
                        </div>
                    </div>

                    <!-- ACTIONS & CONTROLS -->
                    <div class="glass rounded-2xl p-6 space-y-4">
                        <h2 class="text-sm font-bold text-white flex items-center gap-2">
                            <span class="w-1.5 h-1.5 rounded-full bg-violet-500"></span>
                            Mantenimiento & Acciones
                        </h2>
                        <div class="grid grid-cols-2 gap-3">
                            <button onclick="triggerCleanup()" class="bg-violet-600/10 hover:bg-violet-600/20 active:scale-[0.98] border border-violet-500/20 text-violet-200 font-semibold text-xs py-3 rounded-xl transition-all duration-200">
                                🧹 Depurar Caché (WAL)
                            </button>
                            <button onclick="forceRefreshStats()" class="bg-white/5 hover:bg-white/10 active:scale-[0.98] border border-white/5 text-white font-semibold text-xs py-3 rounded-xl transition-all duration-200">
                                🔄 Refrescar Métricas
                            </button>
                        </div>
                        <div class="bg-amber-500/10 border border-amber-500/20 rounded-xl p-3 flex gap-2.5 items-start text-xs text-amber-200">
                            <span class="text-base leading-none">💡</span>
                            <div>
                                <span class="font-bold">Optimización Local:</span> Recuerda configurar el companion con la IP <b>127.0.0.1</b> en lugar de localhost para saltarte el delay de IPv6 de Windows y bajar la latencia de 2000ms a 14ms.
                            </div>
                        </div>
                    </div>
                </div>

                <!-- RIGHT PANEL: CONSOLE LOGS (7 cols) -->
                <div class="lg:col-span-7 flex flex-col h-[600px] lg:h-auto">
                    <div class="glass rounded-2xl p-6 flex flex-col h-full space-y-4">
                        <div class="flex items-center justify-between">
                            <div class="flex items-center gap-2">
                                <h2 class="text-sm font-bold text-white">Consola de Eventos (rodo_log.txt)</h2>
                                <div class="w-1.5 h-1.5 rounded-full bg-violet-500 relative indicator-pulse"></div>
                            </div>
                            <div class="flex items-center gap-3">
                                <label class="flex items-center gap-1.5 text-xs text-violet-300/60 cursor-pointer">
                                    <input type="checkbox" id="autoscroll-checkbox" checked class="rounded border-white/10 bg-[#110c22] text-violet-600 focus:ring-0">
                                    Auto-scroll
                                </label>
                                <button onclick="loadLogs()" class="p-1.5 rounded-lg hover:bg-white/5 border border-white/5 text-violet-300 transition-all duration-200">
                                    🔄
                                </button>
                            </div>
                        </div>

                        <!-- CONSOLE BOX -->
                        <div class="flex-1 bg-[#090514]/90 border border-white/5 rounded-xl p-4 font-mono text-xs overflow-y-auto space-y-1.5 select-text h-[400px] lg:h-[450px]" id="log-box">
                            <div class="text-violet-300/30">Cargando registros...</div>
                        </div>

                        <!-- CONSOLE FILTER -->
                        <div class="flex gap-2">
                            <input type="text" id="log-search" placeholder="Filtrar registros (ej: PLAY, CACHE, ERROR)..." oninput="filterLogs()" class="flex-1 bg-[#110c22] border border-white/5 rounded-xl px-4 py-2 text-xs focus:outline-none focus:border-violet-500 font-mono placeholder-white/20">
                        </div>
                    </div>
                </div>
            </div>
        </div>

        <!-- DATABASE EXPLORER TAB -->
        <div id="panel-database" class="space-y-6 hidden">
            <!-- SEARCH AND FILTER -->
            <div class="glass rounded-2xl p-4 flex flex-col md:flex-row gap-4 items-center justify-between">
                <div class="relative w-full md:max-w-md">
                    <input type="text" id="db-search" placeholder="Buscar canciones o consultas en caché..." oninput="filterCacheTables()" class="w-full bg-[#110c22] border border-white/5 rounded-xl pl-10 pr-4 py-2.5 text-sm focus:outline-none focus:border-violet-500 font-sans placeholder-white/20">
                    <span class="absolute left-3.5 top-3 text-violet-300/30">🔍</span>
                </div>
                <button onclick="loadCacheData(true)" class="w-full md:w-auto bg-violet-600 hover:bg-violet-500 active:scale-[0.98] transition-all duration-200 text-white text-sm font-semibold rounded-xl px-6 py-2.5 flex items-center justify-center gap-2">
                    🔄 Cargar/Actualizar Tablas
                </button>
            </div>

            <!-- DUAL TABLES GRID -->
            <div class="grid grid-cols-1 xl:grid-cols-12 gap-6">
                <!-- LEFT: Tracks Table (7 cols) -->
                <div class="xl:col-span-7 glass rounded-2xl p-6 space-y-4">
                    <div class="flex items-center justify-between">
                        <h2 class="text-sm font-bold text-white flex items-center gap-2">
                            <span class="w-1.5 h-1.5 rounded-full bg-emerald-500"></span>
                            Metadatos Globales (tracks)
                        </h2>
                        <span class="text-xs text-violet-300/40" id="db-tracks-count">Top 150 elementos</span>
                    </div>
                    
                    <div class="overflow-x-auto w-full max-h-[500px] overflow-y-auto pr-1">
                        <table class="w-full text-left text-xs border-collapse">
                            <thead>
                                <tr class="text-violet-300/40 border-b border-white/5 uppercase tracking-wider font-semibold">
                                    <th class="py-3 px-2">Canción / Artista</th>
                                    <th class="py-3 px-2 text-center">Duración</th>
                                    <th class="py-3 px-2 text-center">Reproducciones</th>
                                    <th class="py-3 px-2 text-center">Stream L1</th>
                                    <th class="py-3 px-2 text-right">Acciones</th>
                                </tr>
                            </thead>
                            <tbody id="db-tracks-body" class="divide-y divide-white/5 text-violet-200 font-sans">
                                <tr>
                                    <td colspan="5" class="py-8 text-center text-violet-300/30">Cargando base de datos...</td>
                                </tr>
                            </tbody>
                        </table>
                    </div>
                </div>

                <!-- RIGHT: Queries Table (5 cols) -->
                <div class="xl:col-span-5 glass rounded-2xl p-6 space-y-4">
                    <div class="flex items-center justify-between">
                        <h2 class="text-sm font-bold text-white flex items-center gap-2">
                            <span class="w-1.5 h-1.5 rounded-full bg-violet-500"></span>
                            Consultas de Usuario (user_queries)
                        </h2>
                        <span class="text-xs text-violet-300/40" id="db-queries-count">Top 200 elementos</span>
                    </div>

                    <div class="overflow-x-auto w-full max-h-[500px] overflow-y-auto pr-1">
                        <table class="w-full text-left text-xs border-collapse">
                            <thead>
                                <tr class="text-violet-300/40 border-b border-white/5 uppercase tracking-wider font-semibold">
                                    <th class="py-3 px-2">Usuario</th>
                                    <th class="py-3 px-2">Consulta original / Elegido</th>
                                    <th class="py-3 px-2 text-center">Conf.</th>
                                    <th class="py-3 px-2 text-center">Usos</th>
                                    <th class="py-3 px-2 text-right"></th>
                                </tr>
                            </thead>
                            <tbody id="db-queries-body" class="divide-y divide-white/5 text-violet-200 font-sans">
                                <tr>
                                    <td colspan="5" class="py-8 text-center text-violet-300/30">Cargando consultas...</td>
                                </tr>
                            </tbody>
                        </table>
                    </div>
                </div>
            </div>
        </div>

    </div>

    <!-- NOTIFICATION POPUP -->
    <div id="toast" class="fixed bottom-6 right-6 glass border-violet-500/30 text-white text-xs px-4 py-3 rounded-xl transition-all duration-300 transform translate-y-20 opacity-0 flex items-center gap-2 z-50">
        <span id="toast-icon">✨</span>
        <span id="toast-text">Acción completada</span>
    </div>

    <script>
        let logsRaw = [];
        let cacheTracks = [];
        let cacheQueries = [];

        // Check if token exists in localStorage
        window.addEventListener('DOMContentLoaded', () => {
            const savedToken = localStorage.getItem('rodo_token');
            if (savedToken) {
                document.getElementById('token-input').value = savedToken;
                attemptLogin();
            }
        });

        async function attemptLogin() {
            const token = document.getElementById('token-input').value.trim();
            if (!token) return;

            const errorEl = document.getElementById('login-error');
            errorEl.classList.add('hidden');

            try {
                const headers = { 'Authorization': `Bearer ${token}` };
                const res = await fetch('/health', { headers });
                
                if (res.status === 200 || res.status === 404) {
                    const data = await res.json();
                    if (data.status === 'ok') {
                        localStorage.setItem('rodo_token', token);
                        document.getElementById('login-screen').classList.add('opacity-0', 'pointer-events-none');
                        document.getElementById('dashboard-content').classList.remove('hidden');
                        showToast('🔑 Conectado con Token Maestro', '🟢');
                        startDashboardPoll();
                    } else {
                        errorEl.classList.remove('hidden');
                    }
                } else {
                    errorEl.classList.remove('hidden');
                }
            } catch (err) {
                errorEl.textContent = 'Error de red al conectar con el servidor';
                errorEl.classList.remove('hidden');
            }
        }

        function logout() {
            localStorage.removeItem('rodo_token');
            document.getElementById('dashboard-content').classList.add('hidden');
            document.getElementById('login-screen').classList.remove('opacity-0', 'pointer-events-none');
            document.getElementById('token-input').value = '';
        }

        function getHeaders() {
            const token = localStorage.getItem('rodo_token');
            return {
                'Authorization': `Bearer ${token}`,
                'Content-Type': 'application/json'
            };
        }

        function showToast(text, icon = '✨') {
            const toast = document.getElementById('toast');
            document.getElementById('toast-text').textContent = text;
            document.getElementById('toast-icon').textContent = icon;
            toast.classList.remove('translate-y-20', 'opacity-0');
            setTimeout(() => {
                toast.classList.add('translate-y-20', 'opacity-0');
            }, 3000);
        }

        // Tab switcher
        let currentTab = 'telemetry';
        function switchTab(tabId) {
            currentTab = tabId;
            const telePanel = document.getElementById('panel-telemetry');
            const dbPanel = document.getElementById('panel-database');
            const teleBtn = document.getElementById('tab-btn-telemetry');
            const dbBtn = document.getElementById('tab-btn-database');
            
            if (tabId === 'telemetry') {
                telePanel.classList.remove('hidden');
                dbPanel.classList.add('hidden');
                teleBtn.className = "pb-3 text-violet-400 border-b-2 border-violet-500 tracking-tight transition-all duration-200";
                dbBtn.className = "pb-3 text-violet-300/40 hover:text-violet-300 border-b-2 border-transparent tracking-tight transition-all duration-200";
            } else if (tabId === 'database') {
                telePanel.classList.add('hidden');
                dbPanel.classList.remove('hidden');
                dbBtn.className = "pb-3 text-violet-400 border-b-2 border-violet-500 tracking-tight transition-all duration-200";
                teleBtn.className = "pb-3 text-violet-300/40 hover:text-violet-300 border-b-2 border-transparent tracking-tight transition-all duration-200";
                loadCacheData();
            }
        }

        let pollInterval;
        function startDashboardPoll() {
            loadStats();
            loadLogs();
            if (pollInterval) clearInterval(pollInterval);
            pollInterval = setInterval(() => {
                loadStats();
                loadLogs();
                if (currentTab === 'database') {
                    loadCacheData(false); // poll cache tables quietly
                }
            }, 5000);
        }

        function forceRefreshStats() {
            loadStats();
            loadLogs();
            showToast('Métricas actualizadas', '🔄');
        }

        async function loadStats() {
            try {
                const res = await fetch('/api/dashboard/stats', { headers: getHeaders() });
                if (!res.ok) {
                    if (res.status === 401) logout();
                    return;
                }
                const data = await res.json();
                
                // Discord Bot
                document.getElementById('bot-name').textContent = data.bot.username || 'Desconectado';
                document.getElementById('bot-servers').textContent = `${data.bot.guilds.length} servidores activos`;
                document.getElementById('bot-ping').textContent = `${data.bot.latency} ms`;
                document.getElementById('header-ping').textContent = `${data.bot.latency} ms`;

                // Ngrok
                const tunStat = document.getElementById('tunnel-status');
                const tunUrl = document.getElementById('tunnel-url');
                const tunDest = document.getElementById('tunnel-dest');
                
                if (data.ngrok.active) {
                    tunStat.innerHTML = '<span class="text-green-400">Activo</span>';
                    tunUrl.textContent = data.ngrok.public_url;
                    tunUrl.className = "text-xs text-green-300 font-mono underline cursor-pointer";
                    tunUrl.onclick = () => window.open(data.ngrok.public_url, '_blank');
                    tunDest.textContent = data.ngrok.addr;
                } else {
                    tunStat.innerHTML = '<span class="text-rose-400">Inactivo</span>';
                    tunUrl.textContent = data.ngrok.public_url || 'Espera de conexión...';
                    tunUrl.className = "text-xs text-violet-300/40 truncate";
                    tunUrl.onclick = null;
                    tunDest.textContent = 'localhost:5000';
                }

                // DB Size
                document.getElementById('cache-size').textContent = `${(data.cache.db_size_bytes / 1024).toFixed(1)} KB`;
                document.getElementById('cache-metrics').textContent = `${data.cache.tracks_count} canciones en L2/L3`;
                document.getElementById('cache-queries').textContent = data.cache.queries_count;

                // Cache Stats Period (hit ratios)
                const breakdown = data.cache.stats_summary.breakdown || {};
                const ratio = data.cache.stats_summary.live_ratio || {};
                
                let hits = (ratio.CACHE_L1_HIT?.count || 0) + (ratio.CACHE_L2_HIT?.count || 0);
                let total = ratio.total || 0;
                let hitRatioVal = total > 0 ? ((hits / total) * 100).toFixed(1) : '0';
                
                document.getElementById('cache-hit-ratio').textContent = `${hitRatioVal}% Hits`;
                document.getElementById('cache-events-count').textContent = `${total} peticiones totales`;
                document.getElementById('cache-l1-count').textContent = ratio.CACHE_L1_HIT?.count || 0;

                // Render Active Players
                const playersList = document.getElementById('active-players-list');
                playersList.innerHTML = '';
                if (data.bot.active_players.length === 0) {
                    playersList.innerHTML = '<div class="text-sm text-violet-300/30 text-center py-4">No hay reproductores activos</div>';
                } else {
                    data.bot.active_players.forEach(p => {
                        playersList.innerHTML += `
                            <div class="glass bg-violet-950/10 border border-violet-500/10 p-3 rounded-xl flex items-center justify-between text-xs">
                                <div class="space-y-0.5 truncate pr-2">
                                    <div class="font-bold text-white truncate">${p.guild_name}</div>
                                    <div class="text-violet-300/60 truncate">${p.now_playing ? `🔊 Rep: ${p.now_playing}` : '💤 En pausa/espera'}</div>
                                </div>
                                <span class="bg-violet-600/30 px-2 py-0.5 rounded text-[10px] font-bold text-violet-300 flex-shrink-0">
                                    Cola: ${p.queue_size}
                                </span>
                            </div>
                        `;
                    });
                }

                // Render Users List
                const usersList = document.getElementById('users-list');
                usersList.innerHTML = '';
                if (data.users.length === 0) {
                    usersList.innerHTML = '<div class="text-sm text-violet-300/30 text-center py-4">No hay usuarios en tokens.json</div>';
                } else {
                    data.users.forEach(u => {
                        const spotBadge = u.spotify_linked 
                            ? '<span class="bg-emerald-500/10 border border-emerald-500/20 text-emerald-300 px-2 py-0.5 rounded text-[9px] font-semibold flex items-center gap-1">🟢 Spotify linked</span>'
                            : '<span class="bg-white/5 border border-white/5 text-violet-300/30 px-2 py-0.5 rounded text-[9px] flex items-center gap-1">🔴 Spotify off</span>';
                        usersList.innerHTML += `
                            <div class="glass bg-white/5 border border-white/5 px-4 py-2.5 rounded-xl flex items-center justify-between text-xs">
                                <div class="space-y-0.5">
                                    <span class="font-semibold text-white">${u.name}</span>
                                    <span class="text-violet-300/40 text-[10px] font-mono ml-2">(${u.key})</span>
                                </div>
                                ${spotBadge}
                            </div>
                        `;
                    });
                }

            } catch (err) {
                console.error("Error loading stats:", err);
            }
        }

        async function loadLogs() {
            try {
                const res = await fetch('/api/dashboard/logs', { headers: getHeaders() });
                if (!res.ok) return;
                const data = await res.json();
                
                logsRaw = data.logs || [];
                filterLogs();
            } catch (err) {
                console.error("Error loading logs:", err);
            }
        }

        function filterLogs() {
            const query = document.getElementById('log-search').value.toLowerCase().trim();
            const logBox = document.getElementById('log-box');
            
            let filtered = logsRaw;
            if (query) {
                filtered = logsRaw.filter(line => line.toLowerCase().includes(query));
            }

            if (filtered.length === 0) {
                logBox.innerHTML = '<div class="text-violet-300/30">Sin coincidencias.</div>';
                return;
            }

            logBox.innerHTML = filtered.map(line => {
                let colorClass = "text-violet-200";
                if (line.includes("ERROR") || line.includes("falló") || line.includes("fail") || line.includes("ERR_")) {
                    colorClass = "text-rose-400 font-semibold";
                } else if (line.includes("[MÚSICA]") || line.includes("play_music") || line.includes("[PLAYER]")) {
                    colorClass = "text-emerald-300";
                } else if (line.includes("[CACHE]") || line.includes("[CACHE DB]")) {
                    colorClass = "text-amber-300";
                } else if (line.includes("[TIMING]")) {
                    colorClass = "text-sky-300";
                } else if (line.includes("[BOT]") || line.includes("[HTTP]")) {
                    colorClass = "text-indigo-300";
                }
                
                const escaped = line.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
                return `<div class="${colorClass}">${escaped}</div>`;
            }).join('');

            const checkbox = document.getElementById('autoscroll-checkbox');
            if (checkbox.checked) {
                logBox.scrollTop = logBox.scrollHeight;
            }
        }

        async function triggerCleanup() {
            if (!confirm("¿Deseas depurar la base de datos de caché?\\n\\nEsto invalidará los stream URLs de YouTube expirados y purgará los candidatos inactivos de baja confianza.")) {
                return;
            }
            
            try {
                const res = await fetch('/api/dashboard/cleanup', {
                    method: 'POST',
                    headers: getHeaders()
                });
                const data = await res.json();
                if (data.ok) {
                    showToast(`🧹 Depuración terminada: ${data.message}`, '🟢');
                    loadStats();
                } else {
                    showToast(`Error: ${data.error}`, '🔴');
                }
            } catch (err) {
                showToast("Fallo al contactar el servidor", '🔴');
            }
        }

        // Cache DB Explorer logic
        async function loadCacheData(showToastFeedback = false) {
            try {
                const res = await fetch('/api/dashboard/cache', { headers: getHeaders() });
                if (!res.ok) return;
                const data = await res.json();
                
                cacheTracks = data.tracks || [];
                cacheQueries = data.queries || [];
                
                filterCacheTables();
                
                if (showToastFeedback) {
                    showToast('Base de datos cargada', '💾');
                }
            } catch (err) {
                console.error("Error loading cache data:", err);
            }
        }

        function formatDuration(secs) {
            if (!secs) return "--:--";
            const m = Math.floor(secs / 60);
            const s = Math.floor(secs % 60);
            return `${m}:${s < 10 ? '0' : ''}${s}`;
        }

        function filterCacheTables() {
            const query = document.getElementById('db-search').value.toLowerCase().trim();
            const tracksBody = document.getElementById('db-tracks-body');
            const queriesBody = document.getElementById('db-queries-body');
            
            // 1. Filter tracks
            let filteredTracks = cacheTracks;
            if (query) {
                filteredTracks = cacheTracks.filter(t => 
                    (t.title || '').toLowerCase().includes(query) || 
                    (t.artist || '').toLowerCase().includes(query) ||
                    (t.track_key || '').toLowerCase().includes(query)
                );
            }
            
            document.getElementById('db-tracks-count').textContent = `Top ${filteredTracks.length} elementos`;
            
            if (filteredTracks.length === 0) {
                tracksBody.innerHTML = '<tr><td colspan="5" class="py-8 text-center text-violet-300/30 font-sans">No hay canciones en caché que coincidan.</td></tr>';
            } else {
                tracksBody.innerHTML = filteredTracks.map(t => {
                    let streamBadge = '';
                    if (t.stream_invalid) {
                        streamBadge = '<span class="bg-rose-500/10 border border-rose-500/20 text-rose-400 px-1.5 py-0.5 rounded text-[10px]">⚠️ Playback Error</span>';
                    } else if (t.is_expired) {
                        streamBadge = '<span class="bg-amber-500/10 border border-amber-500/20 text-amber-400 px-1.5 py-0.5 rounded text-[10px]">⏳ Expirado (L2)</span>';
                    } else {
                        streamBadge = `<span class="bg-emerald-500/10 border border-emerald-500/20 text-emerald-300 px-1.5 py-0.5 rounded text-[10px]">⚡ L1 (${t.expires_in_mins}m)</span>`;
                    }
                    
                    return `
                        <tr class="hover:bg-white/5 transition-all duration-150">
                            <td class="py-3 px-2 max-w-[220px]">
                                <div class="font-semibold text-white truncate" title="${t.title}">${t.title || 'Sin título'}</div>
                                <div class="text-[10px] text-violet-300/50 truncate flex items-center gap-1.5 mt-0.5">
                                    <span>${t.artist || 'Desconocido'}</span>
                                    <span class="font-mono bg-white/5 px-1 py-0.2 rounded">${t.track_key}</span>
                                </div>
                            </td>
                            <td class="py-3 px-2 text-center font-mono text-[11px] text-violet-300/50">${formatDuration(t.duration)}</td>
                            <td class="py-3 px-2 text-center font-semibold font-mono text-violet-300">${t.play_count}</td>
                            <td class="py-3 px-2 text-center">${streamBadge}</td>
                            <td class="py-3 px-2 text-right space-x-1.5 whitespace-nowrap">
                                <button onclick="window.open('${t.webpage_url}', '_blank')" class="p-1 rounded bg-white/5 hover:bg-white/10 text-violet-300" title="Ver en YouTube">📺</button>
                                <button onclick="refreshTrackStream('${t.track_key}')" class="p-1 rounded bg-violet-600/20 hover:bg-violet-600/40 text-violet-200" title="Refrescar Stream L3">🔄</button>
                                <button onclick="deleteCacheItem('track', '${t.track_key}')" class="p-1 rounded bg-rose-500/10 hover:bg-rose-500/30 text-rose-300" title="Eliminar de caché">🗑️</button>
                            </td>
                        </tr>
                    `;
                }).join('');
            }

            // 2. Filter queries
            let filteredQueries = cacheQueries;
            if (query) {
                filteredQueries = cacheQueries.filter(q => 
                    (q.normalized_query || '').toLowerCase().includes(query) || 
                    (q.title || '').toLowerCase().includes(query) ||
                    (q.artist || '').toLowerCase().includes(query) ||
                    (q.user_key || '').toLowerCase().includes(query)
                );
            }
            
            document.getElementById('db-queries-count').textContent = `Top ${filteredQueries.length} elementos`;

            if (filteredQueries.length === 0) {
                queriesBody.innerHTML = '<tr><td colspan="5" class="py-8 text-center text-violet-300/30 font-sans">No hay consultas que coincidan.</td></tr>';
            } else {
                queriesBody.innerHTML = filteredQueries.map(q => {
                    let confBadge = '';
                    if (q.confidence >= 0.8) {
                        confBadge = `<span class="bg-emerald-500/10 border border-emerald-500/20 text-emerald-300 px-1 py-0.5 rounded text-[10px] font-bold font-mono">${q.confidence}</span>`;
                    } else if (q.confidence >= 0.5) {
                        confBadge = `<span class="bg-amber-500/10 border border-amber-500/20 text-amber-400 px-1 py-0.5 rounded text-[10px] font-bold font-mono">${q.confidence}</span>`;
                    } else {
                        confBadge = `<span class="bg-rose-500/10 border border-rose-500/20 text-rose-400 px-1 py-0.5 rounded text-[10px] font-bold font-mono">${q.confidence}</span>`;
                    }
                    
                    return `
                        <tr class="hover:bg-white/5 transition-all duration-150">
                            <td class="py-3 px-2 font-semibold text-white capitalize">${q.user_key}</td>
                            <td class="py-3 px-2 max-w-[150px]">
                                <div class="font-mono text-violet-300 font-medium truncate" title="${q.normalized_query}">"${q.normalized_query}"</div>
                                <div class="text-[10px] text-violet-300/40 truncate mt-0.5 flex items-center gap-1">
                                    <span>👉</span>
                                    <span class="truncate" title="${q.title}">${q.title}</span>
                                </div>
                            </td>
                            <td class="py-3 px-2 text-center">${confBadge}</td>
                            <td class="py-3 px-2 text-center font-bold font-mono text-violet-300">${q.usage_count}</td>
                            <td class="py-3 px-2 text-right">
                                <button onclick="deleteCacheItem('query', ${q.id})" class="p-1 rounded bg-rose-500/10 hover:bg-rose-500/30 text-rose-300" title="Eliminar asociación">🗑️</button>
                            </td>
                        </tr>
                    `;
                }).join('');
            }
        }

        async function deleteCacheItem(type, id) {
            const confirmMsg = type === 'query' 
                ? '¿Deseas eliminar esta asociación específica de consulta de usuario?' 
                : '¿Deseas eliminar esta canción de la caché? Se borrarán también todas las consultas de usuario asociadas a ella.';
                
            if (!confirm(confirmMsg)) return;
            
            try {
                const res = await fetch('/api/dashboard/cache/delete', {
                    method: 'POST',
                    headers: getHeaders(),
                    body: JSON.stringify({ type, id })
                });
                const data = await res.json();
                if (data.ok) {
                    showToast(data.message, '🗑️');
                    loadCacheData();
                    loadStats();
                } else {
                    showToast(`Error: ${data.error}`, '🔴');
                }
            } catch (err) {
                showToast("Fallo al contactar el servidor", '🔴');
            }
        }

        async function refreshTrackStream(trackKey) {
            showToast(`Extrayendo nuevo stream URL para '${trackKey}'...`, '⏳');
            try {
                const res = await fetch('/api/dashboard/cache/refresh', {
                    method: 'POST',
                    headers: getHeaders(),
                    body: JSON.stringify({ track_key: trackKey })
                });
                const data = await res.json();
                if (data.ok) {
                    showToast(data.message, '⚡');
                    loadCacheData();
                } else {
                    showToast(`Error: ${data.error}`, '🔴');
                }
            } catch (err) {
                showToast("Fallo al contactar el servidor", '🔴');
            }
        }
    </script>
</body>
</html>
"""


async def http_dashboard(request: web.Request, bot) -> web.Response:
    """Serve the dashboard static HTML."""
    return web.Response(text=DASHBOARD_HTML, content_type="text/html")


async def http_dashboard_stats(request: web.Request, bot) -> web.Response:
    """GET /api/dashboard/stats - detailed system statistics."""
    now = int(time.time())

    # 1. Gather active player structures
    active_players = []
    for guild_id, player in _players.items():
        guild = bot.get_guild(guild_id)
        if guild and player.voice_client and player.voice_client.is_connected():
            active_players.append({
                "guild_id": guild_id,
                "guild_name": guild.name,
                "now_playing": player.current["title"] if player.current else None,
                "queue_size": len(player.queue),
            })

    # 2. Database statistics
    db_size = 0
    tracks_count = 0
    queries_count = 0
    high_confidence = 0
    low_confidence = 0

    if DB_PATH.exists():
        try:
            db_size = DB_PATH.stat().st_size
            conn = get_connection()
            c = conn.cursor()
            
            c.execute("SELECT COUNT(*) FROM tracks")
            tracks_count = c.fetchone()[0]
            
            c.execute("SELECT COUNT(*) FROM user_queries")
            queries_count = c.fetchone()[0]
            
            c.execute("SELECT COUNT(*) FROM user_queries WHERE confidence >= 0.8")
            high_confidence = c.fetchone()[0]
            
            c.execute("SELECT COUNT(*) FROM user_queries WHERE confidence < 0.5")
            low_confidence = c.fetchone()[0]
            
            conn.close()
        except Exception as e:
            logger.error("Error reading database stats: %s", e)

    # 3. Cache performance statistics
    stats_summary = get_stats_summary(hours=24)

    # 4. Ngrok status
    ngrok_url = ""
    ngrok_addr = "http://localhost:5000"
    ngrok_active = False
    
    # Try querying the local ngrok client API
    import aiohttp
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get("http://127.0.0.1:4040/api/tunnels", timeout=0.8) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    tunnels = data.get("tunnels", [])
                    if tunnels:
                        ngrok_url = tunnels[0].get("public_url", "")
                        ngrok_addr = tunnels[0].get("config", {}).get("addr", "http://localhost:5000")
                        ngrok_active = True
    except Exception:
        # Fallback to reading the .env domain if ngrok API is down
        env_domain = os.getenv("NGROK_DOMAIN", "")
        if env_domain:
            ngrok_url = f"https://{env_domain}"

    # 5. List users
    users = []
    for u in token_mgr.list_users():
        user_key = u.get("username")
        # Check Spotify linked status
        spotify_linked = False
        spotify_info = token_mgr.get_spotify_token_info(user_key)
        if spotify_info and spotify_info.get("access_token"):
            spotify_linked = True
        
        users.append({
            "key": user_key,
            "name": u.get("name", user_key),
            "active": u.get("active", True),
            "spotify_linked": spotify_linked,
        })

    # Composition
    res = {
        "bot": {
            "username": str(bot.user) if bot.user else "Desconectado",
            "latency": round(bot.latency * 1000, 1) if bot.latency is not None and not bot.latency != bot.latency else 0.0,
            "guilds": [{"id": g.id, "name": g.name} for g in bot.guilds],
            "active_players": active_players,
        },
        "cache": {
            "db_size_bytes": db_size,
            "tracks_count": tracks_count,
            "queries_count": queries_count,
            "high_confidence_count": high_confidence,
            "low_confidence_count": low_confidence,
            "stats_summary": stats_summary,
        },
        "ngrok": {
            "active": ngrok_active,
            "public_url": ngrok_url,
            "addr": ngrok_addr,
        },
        "users": users,
    }

    return web.json_response(res)


async def http_dashboard_logs(request: web.Request, bot) -> web.Response:
    """GET /api/dashboard/logs - read the last 100 lines of rodo_log.txt."""
    parent_dir = Path(__file__).parent.parent
    log_file = parent_dir / "rodo_log.txt"

    lines = []
    if log_file.exists():
        try:
            # Read last 100 lines in a thread-safe / non-blocking manner
            with open(log_file, "r", encoding="utf-8", errors="replace") as f:
                content = f.readlines()
                lines = [line.strip() for line in content[-100:]]
        except Exception as e:
            lines = [f"Error leyendo rodo_log.txt: {e}"]
    else:
        lines = ["Log vacío o no encontrado (rodo_log.txt no existe aún)."]

    return web.json_response({"logs": lines})


async def http_dashboard_cleanup(request: web.Request, bot) -> web.Response:
    """POST /api/dashboard/cleanup - run Cache Depuration manually."""
    try:
        # Run cleanup_expired in a thread-safe executor pool
        import asyncio
        loop = asyncio.get_event_loop()
        res = await loop.run_in_executor(None, cleanup_expired)
        return web.json_response(res)
    except Exception as e:
        logger.error("Error executing dashboard cleanup: %s", e)
        return web.json_response({"ok": False, "error": str(e)}, status=500)


async def http_dashboard_cache_list(request: web.Request, bot) -> web.Response:
    """GET /api/dashboard/cache - list cached tracks and user queries."""
    try:
        conn = get_connection()
        c = conn.cursor()
        
        # 1. Fetch tracks (L2/L3 global metadata cache)
        c.execute("""
            SELECT id, track_key, title, artist, duration, webpage_url, 
                   stream_url IS NOT NULL as has_stream, stream_expires_at, play_count, stream_invalid
            FROM tracks 
            ORDER BY play_count DESC, id DESC 
            LIMIT 150
        """)
        tracks = []
        now = int(time.time())
        for row in c.fetchall():
            expires_at = row["stream_expires_at"]
            is_expired = True
            if expires_at and expires_at > now and row["has_stream"] and not row["stream_invalid"]:
                is_expired = False
                
            tracks.append({
                "id": row["id"],
                "track_key": row["track_key"],
                "title": row["title"],
                "artist": row["artist"],
                "duration": row["duration"],
                "webpage_url": row["webpage_url"],
                "has_stream": bool(row["has_stream"]),
                "is_expired": is_expired,
                "play_count": row["play_count"],
                "stream_invalid": bool(row["stream_invalid"]),
                "expires_in_mins": round((expires_at - now) / 60) if expires_at and expires_at > now else 0
            })
            
        # 2. Fetch user queries (associations)
        c.execute("""
            SELECT uq.id, uq.user_key, uq.normalized_query, uq.track_key, uq.confidence, uq.usage_count, uq.updated_at,
                   t.title, t.artist
            FROM user_queries uq 
            LEFT JOIN tracks t ON uq.track_key = t.track_key 
            ORDER BY uq.updated_at DESC 
            LIMIT 200
        """)
        queries = []
        for row in c.fetchall():
            queries.append({
                "id": row["id"],
                "user_key": row["user_key"],
                "normalized_query": row["normalized_query"],
                "track_key": row["track_key"],
                "confidence": round(row["confidence"], 3) if row["confidence"] is not None else 0.0,
                "usage_count": row["usage_count"],
                "updated_at": row["updated_at"],
                "title": row["title"] or "Desconocido",
                "artist": row["artist"] or "Desconocido"
            })
            
        conn.close()
        return web.json_response({
            "ok": True,
            "tracks": tracks,
            "queries": queries
        })
    except Exception as e:
        logger.error("Error listing cache from dashboard: %s", e)
        return web.json_response({"ok": False, "error": str(e)}, status=500)


async def http_dashboard_cache_delete(request: web.Request, bot) -> web.Response:
    """POST /api/dashboard/cache/delete - delete a track or user query association."""
    try:
        data = await request.json()
        item_type = data.get("type") # "query" or "track"
        item_id = data.get("id")     # ID (int) for query, or track_key (str) for track
        
        if not item_type or item_id is None:
            return web.json_response({"ok": False, "error": "Faltan parámetros de eliminación"}, status=400)
            
        conn = get_connection()
        c = conn.cursor()
        
        if item_type == "query":
            c.execute("DELETE FROM user_queries WHERE id = ?", (item_id,))
            conn.commit()
            conn.close()
            return web.json_response({"ok": True, "message": f"Asociación de consulta #{item_id} eliminada."})
            
        elif item_type == "track":
            # Delete track
            c.execute("DELETE FROM tracks WHERE track_key = ?", (item_id,))
            # Delete associated queries to maintain referential integrity
            c.execute("DELETE FROM user_queries WHERE track_key = ?", (item_id,))
            conn.commit()
            conn.close()
            return web.json_response({"ok": True, "message": f"Canción '{item_id}' y sus consultas asociadas eliminadas."})
            
        else:
            conn.close()
            return web.json_response({"ok": False, "error": "Tipo de item inválido"}, status=400)
            
    except Exception as e:
        logger.error("Error deleting cache item from dashboard: %s", e)
        return web.json_response({"ok": False, "error": str(e)}, status=500)


async def http_dashboard_cache_refresh(request: web.Request, bot) -> web.Response:
    """POST /api/dashboard/cache/refresh - force a fresh stream URL extraction via yt-dlp."""
    try:
        data = await request.json()
        track_key = data.get("track_key")
        if not track_key:
            return web.json_response({"ok": False, "error": "Falta track_key"}, status=400)
            
        conn = get_connection()
        c = conn.cursor()
        c.execute("SELECT webpage_url FROM tracks WHERE track_key = ?", (track_key,))
        row = c.fetchone()
        conn.close()
        
        if not row:
            return web.json_response({"ok": False, "error": "Canción no encontrada"}, status=404)
            
        webpage_url = row["webpage_url"]
        
        from modules.music.search import yt_search
        from modules.music.cache import refresh_stream_url
        
        # Extract direct stream URL
        refreshed = await yt_search(webpage_url, log=False, fast=True)
        expires = int(refreshed["_resolved_at"] + 4 * 3600)
        
        # Save to SQLite database
        refresh_stream_url(track_key, refreshed["url"], expires)
        
        return web.json_response({
            "ok": True, 
            "message": f"Stream URL para '{track_key}' extraído y guardado con éxito.",
            "expires_at": expires
        })
    except Exception as e:
        logger.error("Error refreshing stream URL from dashboard: %s", e)
        return web.json_response({"ok": False, "error": str(e)}, status=500)


async def http_client_log(request: web.Request, bot) -> web.Response:
    """POST /api/client_log - receive real-time audio transcripts/logs from the client."""
    try:
        data = await request.json()
        message = data.get("message", "").strip()
        if not message:
            return web.json_response({"ok": False, "error": "Falta mensaje"}, status=400)

        # Print the message to stdout so it goes to console and is captured by Tee
        user_display = request.get("auth_user") or "amigo"
        print(f"[CLIENTE:{user_display}] {message}")
        
        return web.json_response({"ok": True})
    except Exception as e:
        logger.error("Error processing client log: %s", e)
        return web.json_response({"ok": False, "error": str(e)}, status=500)

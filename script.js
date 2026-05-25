        // ══════════════════════════════════════
        //  WEBSOCKET STATE
        // ══════════════════════════════════════
        let ws = null;
        let wsReady = false;
        let queryCount = 0;
        let searchCount = 0;
        let startTime = Date.now();
        let sessionStartTime = null;   // set on init_ok = JARVIS session start
        let isAgentConnected = false;  // set on agent check or stats packet
        let isBusy = false;
        let webSearchEnabled = true;
        let history = [];
        let waveAmplitude = 6;
        let waveTarget = 6;
        let waveOffset = 0;

        // ══════════════════════════════════════
        //  JWT SESSION STATE
        // ══════════════════════════════════════
        let jarvisToken = localStorage.getItem('jarvis_jwt') || '';

        // ══════════════════════════════════════
        //  BOOT — Phase 4: JWT Auth
        // ══════════════════════════════════════
        async function boot() {
            const key = document.getElementById('apiKeyInput').value.trim();
            const name = document.getElementById('userNameInput').value.trim() || 'D.Tejesh Kumar';
            if (!key.startsWith('gsk_')) {
                document.getElementById('apiKeyInput').style.borderColor = 'var(--red)';
                document.getElementById('apiKeyInput').placeholder = 'Invalid key format!';
                return;
            }

            const btn = document.querySelector('.api-btn');
            btn.innerText = 'AUTHENTICATING...';
            btn.disabled = true;

            try {
                // Phase 4: Hit /api/auth to get a signed JWT — key never goes over WS
                const res = await fetch('/api/auth', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ key, name })
                });
                const data = await res.json();

                if (!data.success) {
                    // Auth failed — show error on correct field
                    if (data.status === 'IDENTITY_MISMATCH' || data.status === 'NAME_TAKEN') {
                        const input = document.getElementById('userNameInput');
                        input.style.borderColor = 'var(--warn)';
                        input.value = '';
                        input.placeholder = data.error;
                        document.getElementById('apiKeyInput').style.borderColor = 'var(--red)';
                    } else {
                        document.getElementById('apiKeyInput').style.borderColor = 'var(--red)';
                        document.getElementById('apiKeyInput').value = '';
                        document.getElementById('apiKeyInput').placeholder = data.error || 'Auth failed!';
                    }
                    btn.innerText = '▶ INITIALIZE ALL SYSTEMS';
                    btn.disabled = false;
                    return;
                }

                // Store JWT securely
                jarvisToken = data.token;
                localStorage.setItem('jarvis_jwt', data.token);
                localStorage.setItem('jarvis_user_name', data.user_name);

                // Now tell the already-open WebSocket to init using the JWT
                if (ws && wsReady) {
                    ws.send(JSON.stringify({ type: 'init_jwt', token: data.token, name: data.user_name }));
                    document.getElementById('apiKeyInput').placeholder = 'Session secured...';
                }
            } catch(err) {
                console.error('Auth error:', err);
                btn.innerText = '▶ INITIALIZE ALL SYSTEMS';
                btn.disabled = false;
                document.getElementById('apiKeyInput').placeholder = 'Connection error!';
            }
        }

        // ══════════════════════════════════════
        //  ENVIRONMENT DETECT
        // ══════════════════════════════════════
        function detectEnv() {
            const ua = navigator.userAgent;
            let os = 'Windows NT';
            if (/Mac/.test(ua)) os = 'macOS';
            else if (/Linux/.test(ua)) os = 'Linux';
            let br = 'Chromium';
            if (/Edg/.test(ua)) br = 'Edge';
            else if (/Firefox/.test(ua)) br = 'Firefox';
            setText('eOS', os);
            setText('eBR', br);
            setText('eCOR', (navigator.hardwareConcurrency || '--') + ' cores');
            setText('eSCR', screen.width + '×' + screen.height);
            setText('eTZ', Intl.DateTimeFormat().resolvedOptions().timeZone);
            setText('eLNG', navigator.language || '--');
            setText('ePLT', navigator.platform || '--');
        }

        function setText(id, val) {
            const el = document.getElementById(id);
            if (el) el.textContent = val;
        }

        // ══════════════════════════════════════
        //  CLOCK
        // ══════════════════════════════════════
        function tickClock() {
            const now = new Date();
            const utc = now.toUTCString().match(/\d+:\d+:\d+/)[0];
            setText('footerClock', utc + ' UTC');

            // Drive session uptime from client-side clock (not PC boot time)
            if (sessionStartTime) {
                const elapsed = Math.floor((Date.now() - sessionStartTime) / 1000);
                const h = Math.floor(elapsed / 3600);
                const m = Math.floor((elapsed % 3600) / 60);
                const s = elapsed % 60;
                const hh = String(h).padStart(2, '0');
                const mm = String(m).padStart(2, '0');
                const ss = String(s).padStart(2, '0');
                setText('hUptime', `${hh}:${mm}:${ss}`);
            }
        }

        function updateVitals() {
            const r = (a, b) => Math.floor(Math.random() * (b - a) + a);
            
            if (!isAgentConnected) {
                // Clear vitals to '-' when disconnected
                setVital('vCPU', '-', 'bCPU', 0);
                setVital('vMEM', '-', 'bMEM', 0);
                setVital('vNET', '-', 'bNET', 0);
                setVital('vDSK', '-', 'bDSK', 0);
                setVital('vTMP', '-', 'bTMP', 0);
                setText('eBAT', '-');
                setText('ePROC', '-');
                return;
            }
            
            const tmp = r(28, 68);
            setText('vTMP', tmp + '°C'); const bt = document.getElementById('bTMP'); if (bt) bt.style.width = tmp + '%';
            
            if (!wsReady) {
                const net = r(8, 95), dsk = r(5, 60);
                setText('vNET', net + 'KB/s'); const bn = document.getElementById('bNET'); if (bn) bn.style.width = net + '%';
                setText('vDSK', dsk + 'MB/s'); const bd = document.getElementById('bDSK'); if (bd) bd.style.width = dsk + '%';
            }
        }

        function setVital(valId, valTxt, barId, pct) {
            setText(valId, valTxt);
            const bar = document.getElementById(barId);
            if (bar) bar.style.width = pct + '%';
        }

        // ══════════════════════════════════════
        //  LOG
        // ══════════════════════════════════════
        const autoLogs = [
            ['KERNEL', 'Memory garbage collection run', 'ok'],
            ['NET', 'Packet loss 0.002% — nominal', 'ok'],
            ['CRYPTO', 'AES-256 key rotation complete', 'ok'],
            ['SENSOR', 'Ambient temperature: 22.4°C', ''],
            ['RADAR', 'No hostile contacts detected', 'ok'],
            ['NET', 'DNS cache refreshed', 'ok'],
            ['GPU', 'Driver optimization applied', 'ok'],
            ['PROC', 'Background tasks rebalanced', ''],
            ['UPLINK', 'Satellite sync: 48ms latency', 'ok'],
        ];

        function log(src, msg, type = '') {
            const el = document.createElement('div');
            const t = new Date().toLocaleTimeString('en', { hour12: false });
            el.className = `log-line ${type ? 'log-' + type : ''}`;
            el.innerHTML = `<span class="log-ts">[${t}] ${src}:</span> ${msg}`;
            const container = document.getElementById('sysLog');
            container.prepend(el);
            while (container.children.length > 40) container.lastChild.remove();
        }

        function autoLog() {
            const [src, msg, type] = autoLogs[Math.floor(Math.random() * autoLogs.length)];
            log(src, msg, type);
        }

        // ══════════════════════════════════════
        //  WEATHER & LOCATION
        // ══════════════════════════════════════
        
        const weatherCodes = {
            0: { icon: '[ CLR ]', desc: 'CLEAR' },
            1: { icon: '[ MCL ]', desc: 'MOSTLY CLEAR' },
            2: { icon: '[ PCL ]', desc: 'PARTLY CLOUDY' },
            3: { icon: '[ OVC ]', desc: 'OVERCAST' },
            45: { icon: '[ FOG ]', desc: 'FOG' },
            48: { icon: '[ R-F ]', desc: 'RIME FOG' },
            51: { icon: '[ L-D ]', desc: 'LIGHT DRIZZLE' },
            53: { icon: '[ DRZ ]', desc: 'DRIZZLE' },
            55: { icon: '[ H-D ]', desc: 'HEAVY DRIZZLE' },
            61: { icon: '[ L-R ]', desc: 'LIGHT RAIN' },
            63: { icon: '[ RAN ]', desc: 'RAIN' },
            65: { icon: '[ H-R ]', desc: 'HEAVY RAIN' },
            71: { icon: '[ L-S ]', desc: 'LIGHT SNOW' },
            73: { icon: '[ SNW ]', desc: 'SNOW' },
            75: { icon: '[ H-S ]', desc: 'HEAVY SNOW' },
            95: { icon: '[ STM ]', desc: 'THUNDERSTORM' }
        };

        async function initWeatherAndLocation() {
            try {
                let url = '/api/weather';
                if (window.location.hostname !== 'localhost' && window.location.hostname !== '127.0.0.1') {
                    try {
                        const locRes = await fetch('https://freeipapi.com/api/json');
                        const locData = await locRes.json();
                        if (locData && locData.cityName) {
                            url = `/api/weather?location=${encodeURIComponent(locData.cityName)}`;
                        }
                    } catch (e) {
                        console.warn("Client-side geo-lookup failed, falling back to server default.");
                    }
                }
                const res = await fetch(url);
                const data = await res.json();
                
                if(!data.success) throw new Error("Backend weather fetch failed: " + data.error);

                const lat = data.lat;
                const lon = data.lon;
                const city = data.city;
                const country = data.country;

                setText('locCity', `${city.toUpperCase()}, ${country.toUpperCase()}`);
                log('UPLINK', `Location acquired: ${city} (${lat}, ${lon})`, 'ok');

                const codeInfo = weatherCodes[data.weathercode] || { icon: '[ UNK ]', desc: 'UNKNOWN' };

                document.getElementById('wTemp').innerHTML = `${Math.round(data.temperature)}<span style="font-size:0.55em; vertical-align:super;">°C</span>`;
                setText('wIcon', codeInfo.icon);
                setText('wWind', `${data.windspeed} km/h`);
                setText('wHumid', `${data.humidity}%`);
                setText('wCond', codeInfo.desc);
                
                log('SENSOR', `Weather feed live: ${codeInfo.desc}, ${Math.round(data.temperature)}°C`, 'ok');

            } catch (err) {
                console.error("Weather/Location Error:", err);
                setText('locCity', 'LOCATION OFFLINE');
                setText('wIcon', '[ ERR ]');
                document.getElementById('wTemp').innerHTML = `--<span style="font-size:0.55em; vertical-align:super;">°C</span>`;
                log('UPLINK', 'Failed to acquire location/weather telemetry', 'err');
            }
        }


        // ══════════════════════════════════════
        //  WAVEFORM
        // ══════════════════════════════════════
        const WC = document.getElementById('waveCanvas');
        const wctx = WC.getContext('2d');
        let waveColor = [0, 229, 255]; // R, G, B

        function drawWave() {
            WC.width = WC.parentElement.clientWidth;
            WC.height = WC.parentElement.clientHeight;
            const W = WC.width, H = WC.height;
            wctx.clearRect(0, 0, W, H);

            waveAmplitude += (waveTarget - waveAmplitude) * 0.08;

            const mode = document.getElementById('waveMode').innerText;
            let targetColor = [0, 229, 255];
            if (mode === 'LISTENING') targetColor = [255, 193, 7]; // Yellow
            else if (mode === 'PROCESSING') targetColor = [0, 230, 118]; // Green
            
            waveColor[0] += (targetColor[0] - waveColor[0]) * 0.1;
            waveColor[1] += (targetColor[1] - waveColor[1]) * 0.1;
            waveColor[2] += (targetColor[2] - waveColor[2]) * 0.1;
            
            const r = Math.round(waveColor[0]);
            const g = Math.round(waveColor[1]);
            const b = Math.round(waveColor[2]);

            wctx.globalCompositeOperation = 'screen';

            const layers = [
                { freq: 0.015, amp: 1.0, alpha: 0.9, lw: 2.0 },
                { freq: 0.022, amp: 0.7, alpha: 0.6, lw: 1.5 },
                { freq: 0.035, amp: 0.45, alpha: 0.35, lw: 1.2 },
                { freq: 0.055, amp: 0.25, alpha: 0.15, lw: 0.8 },
            ];

            layers.forEach((l, i) => {
                wctx.beginPath();
                for (let x = 0; x <= W; x++) {
                    // Smoothly pinch the wave at the left and right edges of the panel
                    const distFromCenter = Math.abs((W / 2) - x) / (W / 2);
                    const taper = Math.max(0, 1 - distFromCenter * distFromCenter);

                    const y = H / 2
                        + Math.sin(x * l.freq + waveOffset + i * 1.5) * waveAmplitude * l.amp * taper
                        + Math.cos(x * l.freq * 2.3 - waveOffset * 0.8) * waveAmplitude * 0.25 * taper;

                    x === 0 ? wctx.moveTo(x, y) : wctx.lineTo(x, y);
                }

                wctx.shadowBlur = i === 0 ? 8 : 0;
                wctx.shadowColor = `rgba(${r}, ${g}, ${b}, 0.8)`;
                wctx.strokeStyle = `rgba(${r}, ${g}, ${b}, ${l.alpha})`;
                wctx.lineWidth = l.lw;
                wctx.stroke();
            });

            wctx.globalCompositeOperation = 'source-over';
            wctx.shadowBlur = 0;

            waveOffset += 0.05;
            requestAnimationFrame(drawWave);
        }

        // ══════════════════════════════════════
        //  NETWORK GRAPH
        // ══════════════════════════════════════
        const NC = document.getElementById('netCanvas');
        const nctx = NC.getContext('2d');
        let netNodes = [];

        function initNet() {
            NC.width = NC.parentElement.clientWidth;
            netNodes = Array.from({ length: 10 }, () => ({
                x: Math.random() * NC.width,
                y: Math.random() * 60,
                vx: (Math.random() - 0.5) * 0.35,
                vy: (Math.random() - 0.5) * 0.35,
                r: Math.random() * 2.5 + 1.5
            }));
        }

        function drawNet() {
            if (!NC.width) { requestAnimationFrame(drawNet); return; }
            const W = NC.width, H = 60;
            nctx.clearRect(0, 0, W, H);

            netNodes.forEach(n => {
                n.x += n.vx; n.y += n.vy;
                if (n.x < 4 || n.x > W - 4) n.vx *= -1;
                if (n.y < 4 || n.y > H - 4) n.vy *= -1;
            });

            netNodes.forEach((a, i) => netNodes.forEach((b, j) => {
                if (j <= i) return;
                const d = Math.hypot(a.x - b.x, a.y - b.y);
                if (d < 70) {
                    nctx.beginPath();
                    nctx.moveTo(a.x, a.y); nctx.lineTo(b.x, b.y);
                    nctx.strokeStyle = `rgba(0,229,255,${(0.5 - d / 140).toFixed(2)})`;
                    nctx.lineWidth = 0.8;
                    nctx.stroke();
                }
            }));

            netNodes.forEach(n => {
                nctx.save();
                nctx.shadowBlur = 8;
                nctx.shadowColor = 'var(--arc)';
                nctx.beginPath();
                nctx.arc(n.x, n.y, n.r, 0, Math.PI * 2);
                nctx.fillStyle = 'rgba(0,229,255,0.9)';
                nctx.fill();
                nctx.restore();
            });

            requestAnimationFrame(drawNet);
        }

        // ══════════════════════════════════════
        //  BG GRID
        // ══════════════════════════════════════
        const BGC = document.getElementById('bgCanvas');
        const bgctx = BGC.getContext('2d');

        function drawBG() {
            BGC.width = window.innerWidth;
            BGC.height = window.innerHeight;
            const W = BGC.width, H = BGC.height;
            const gs = 48;
            bgctx.clearRect(0, 0, W, H);
            bgctx.strokeStyle = 'rgba(0,229,255,0.04)';
            bgctx.lineWidth = 0.5;
            for (let x = 0; x < W; x += gs) { bgctx.beginPath(); bgctx.moveTo(x, 0); bgctx.lineTo(x, H); bgctx.stroke(); }
            for (let y = 0; y < H; y += gs) { bgctx.beginPath(); bgctx.moveTo(0, y); bgctx.lineTo(W, y); bgctx.stroke(); }
            // Diagonal accent
            bgctx.strokeStyle = 'rgba(0,229,255,0.02)';
            for (let i = -H; i < W + H; i += gs * 4) {
                bgctx.beginPath(); bgctx.moveTo(i, 0); bgctx.lineTo(i + H, H); bgctx.stroke();
            }
        }

        // ══════════════════════════════════════
        //  RESPONSE FORMATTER
        // ══════════════════════════════════════
        function formatResponse(text) {
            if (!text) return '';

            // Split on HTML tags to preserve server-sent HTML (pre blocks, buttons, etc.)
            // We only format the plain-text segments between HTML tags
            const parts = text.split(/(<[^>]+>[\s\S]*?<\/[^>]+>|<[^>]+\/>|<[^>]+>)/g);
            const formatted = parts.map(part => {
                // If this segment is an HTML tag or block, pass it through untouched
                if (part.startsWith('<')) return part;

                // Plain text segment — apply markdown + list formatting
                let t = part;

                // **bold**
                t = t.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
                // *italic*
                t = t.replace(/\*(.+?)\*/g, '<em>$1</em>');

                // Process line by line for numbered/bullet lists
                const lines = t.split('\n');
                const out = [];
                let inOl = false, inUl = false;

                for (let i = 0; i < lines.length; i++) {
                    const line = lines[i].trimEnd();
                    const olMatch = line.match(/^(\d+)\.\s+(.*)/);
                    const ulMatch = line.match(/^[-•]\s+(.*)/);

                    if (olMatch) {
                        if (inUl) { out.push('</ul>'); inUl = false; }
                        if (!inOl) { out.push('<ol>'); inOl = true; }
                        out.push(`<li>${olMatch[2]}</li>`);
                    } else if (ulMatch) {
                        if (inOl) { out.push('</ol>'); inOl = false; }
                        if (!inUl) { out.push('<ul>'); inUl = true; }
                        out.push(`<li>${ulMatch[1]}</li>`);
                    } else {
                        if (inOl) { out.push('</ol>'); inOl = false; }
                        if (inUl) { out.push('</ul>'); inUl = false; }
                        if (line.trim() === '') {
                            out.push('<br>');
                        } else {
                            out.push(`<span>${line}</span><br>`);
                        }
                    }
                }
                if (inOl) out.push('</ol>');
                if (inUl) out.push('</ul>');
                return out.join('');
            });

            return formatted.join('');
        }

        // ══════════════════════════════════════
        //  CHAT
        // ══════════════════════════════════════
        function qCmd(txt) {
            document.getElementById('cmdInput').value = txt;
            sendMsg(false);
        }

        function sendMsg(isVoice = false) {
            if (!wsReady) { alert('J.A.R.V.I.S. backend not connected. Run start_jarvis.bat first.'); return; }
            if (typeof synth !== 'undefined' && synth && synth.speaking) synth.cancel();
            const input = document.getElementById('cmdInput');
            const txt = input.value.trim();
            if (!txt || isBusy) return;
            isBusy = true;
            input.value = '';
            
            queryCount++;
            setText('hQueries', queryCount);

            appendMsg('user', txt, null);
            showTyping();
            waveTarget = 30;
            setText('waveMode', 'PROCESSING');
            log('CMD', txt.substring(0, 50) + (txt.length > 50 ? '...' : ''), '');
            
            // Inject live HUD telemetry into the message payload silently
            const hudData = ` [SYSTEM TELEMETRY: Location=${document.getElementById('locCity').innerText}, Temp=${document.getElementById('wTemp').innerText}, Wind=${document.getElementById('wWind').innerText}, Humid=${document.getElementById('wHumid').innerText}]`;
            ws.send(JSON.stringify({ type: 'message', text: txt + hudData, is_voice: isVoice }));
        }

        function appendMsg(role, content, tag) {
            const chat = document.getElementById('chatBox');
            const t = new Date().toLocaleTimeString('en', { hour12: false });
            const div = document.createElement('div');
            let msgClasses = 'msg';
            if (role === 'user') msgClasses += ' msg-user';
            if (tag === 'err') msgClasses += ' msg-err';
            div.className = msgClasses;

            let tagHtml = '';
            if (tag === 'search') tagHtml = '<span class="mtag mtag-search">◈ WEB SEARCH</span>';
            else if (tag === 'sys') tagHtml = '<span class="mtag mtag-sys">⌘ SYSTEM</span>';
            else if (tag === 'ai') tagHtml = '<span class="mtag mtag-ai">● AI</span>';
            else if (tag === 'err') tagHtml = '<span class="mtag mtag-err">⚠ ERROR</span>';

            const displayContent = role === 'user'
                ? content.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
                : formatResponse(content);

            div.innerHTML = `
    <div class="avatar">${role === 'user' ? 'DTK' : 'J'}</div>
    <div class="bubble">
      <div class="bubble-meta">${role === 'user' ? 'D.TEJESH' : 'JARVIS'} ${tagHtml} // ${t}</div>
      ${displayContent}
    </div>`;
            chat.appendChild(div);
            chat.scrollTop = chat.scrollHeight;
        }

        function clearApiKey() {
            if (confirm("Are you sure you want to clear your saved Groq Cloud API credentials and disconnect the neural net?")) {
                ws.send(JSON.stringify({ type: 'clear_key' }));
                // Phase 4: Also erase JWT so user must fully re-authenticate
                jarvisToken = '';
                localStorage.removeItem('jarvis_jwt');
                localStorage.removeItem('jarvis_user_name');
                document.getElementById('apiOverlay').style.display = 'flex';
                document.getElementById('apiKeyInput').value = '';
                document.getElementById('userNameInput').value = '';
                document.getElementById('apiKeyInput').placeholder = 'Enter Groq Cloud API Key...';
                document.getElementById('chatBox').innerHTML = '';
                log('SYSTEM', '🔓 JWT + API Credentials purged. Full re-authentication required.', 'warn');
            }
        }

        function showTyping() {
            isBusy = true;
            document.getElementById('execBtn').disabled = true;
            const chat = document.getElementById('chatBox');
            const div = document.createElement('div');
            div.className = 'msg'; div.id = 'typingMsg';
            div.innerHTML = `
    <div class="avatar">J</div>
    <div class="bubble typing-bubble">
      <div class="typing-dots">
        <div class="tdot"></div><div class="tdot"></div><div class="tdot"></div>
      </div>
    </div>`;
            chat.appendChild(div);
            chat.scrollTop = chat.scrollHeight;
        }

        function hideTyping() {
            const t = document.getElementById('typingMsg');
            if (t) t.remove();
            isBusy = false;
            document.getElementById('execBtn').disabled = false;
            waveTarget = 6;
            setText('waveMode', 'STANDBY');
        }


        // ══════════════════════════════════════
        //  VOICE RECOGNITION & SYNTHESIS
        // ══════════════════════════════════════
        const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
        let recognition = null;
        let isListening = false;
        let synth = window.speechSynthesis;
        let jarvisVoice = null;

        let speechTimeout = null;
        let cumulativeTranscript = "";

        if (SpeechRecognition) {
            recognition = new SpeechRecognition();
            recognition.continuous = true; // Stay on until explicitly stopped or long silence
            recognition.interimResults = true;
            recognition.lang = 'en-US';

            recognition.onstart = () => {
                isListening = true;
                cumulativeTranscript = "";
                document.getElementById('cmdInput').value = "";
                document.getElementById('micBtn').classList.add('listening');
                document.getElementById('cmdInput').placeholder = "Listening (Mic stays open, pause for 3s to send)...";
                waveTarget = 45;
                setText('waveMode', 'LISTENING');
                log('AUDIO', 'Microphone active. Listening for continuous input.', 'ok');
            };

            recognition.onresult = (event) => {
                let interimTranscript = '';
                let newFinalAdded = false;

                for (let i = event.resultIndex; i < event.results.length; ++i) {
                    if (event.results[i].isFinal) {
                        cumulativeTranscript += event.results[i][0].transcript + ' ';
                        newFinalAdded = true;
                    } else {
                        interimTranscript += event.results[i][0].transcript;
                    }
                }

                document.getElementById('cmdInput').value = cumulativeTranscript + interimTranscript;

                clearTimeout(speechTimeout);
                
                if (newFinalAdded || interimTranscript.trim()) {
                    speechTimeout = setTimeout(() => {
                        if (isListening && document.getElementById('cmdInput').value.trim() !== '') {
                            recognition.stop();
                            sendMsg(true);
                        }
                    }, 3000); // 3 full seconds of silence
                }
            };

            recognition.onerror = (event) => {
                console.error("Speech error", event.error);
                log('AUDIO', 'Microphone error: ' + event.error, 'err');
                if (event.error === 'network') {
                    appendMsg('sys', 'CRITICAL MALFUNCTION: Browser Speech API network connection failed. If you are using Brave/Firefox, standard Google Speech services are blocked. Please use Google Chrome or Microsoft Edge.', 'err');
                } else if (event.error === 'not-allowed') {
                    appendMsg('sys', 'PERMISSION DENIED: Microphone access was blocked. Please allow microphone access in site settings.', 'err');
                }
                stopMic();
            };

            recognition.onend = () => {
                clearTimeout(speechTimeout);
                stopMic();
            };
        }

        if (synth) {
            synth.onvoiceschanged = () => { synth.getVoices(); };
        }

        function toggleMic() {
            if (!recognition) {
                alert("Voice recognition is not supported in your browser (Try Chrome).");
                return;
            }
            if (isListening) {
                recognition.stop();
            } else {
                if (synth && synth.speaking) synth.cancel();
                recognition.start();
            }
        }

        function stopMic() {
            isListening = false;
            const mb = document.getElementById('micBtn');
            if(mb) mb.classList.remove('listening');
            const ci = document.getElementById('cmdInput');
            if(ci && ci.placeholder.includes("Listening")) {
                ci.placeholder = "Issue a command, ask anything, or say 'search for...' / 'open Chrome'...";
            }
            if (!isBusy) {
                waveTarget = 6;
                setText('waveMode', 'STANDBY');
            }
        }


        // ══════════════════════════════════════
        //  PHASE 3 — PROACTIVE ALERT SYSTEM
        // ══════════════════════════════════════
        const alertIcons = { cpu: '⚡', ram: '💾', battery: '🔋', disk: '💿' };
        const alertColors = { cpu: 'var(--arc)', ram: 'var(--gold)', battery: 'var(--warn)', disk: 'var(--red, #ff1744)' };

        function showProactiveAlert(alertType, text) {
            // 1. Show in chat with a distinctive alert style
            const chat = document.getElementById('chatBox');
            const t = new Date().toLocaleTimeString('en', { hour12: false });
            const icon = alertIcons[alertType] || '🚨';
            const color = alertColors[alertType] || 'var(--warn)';
            const div = document.createElement('div');
            div.className = 'msg';
            div.innerHTML = `
    <div class="avatar" style="background:${color}20;border-color:${color};color:${color};">J</div>
    <div class="bubble" style="border-left:3px solid ${color};background:${color}0d;">
      <div class="bubble-meta" style="color:${color};">${icon} PROACTIVE ALERT // ${alertType.toUpperCase()} // ${t}</div>
      ${text}
    </div>`;
            chat.appendChild(div);
            chat.scrollTop = chat.scrollHeight;
            log('ALERT', `${icon} ${text}`, 'warn');

            // 2. Cinematic HUD flash banner
            const banner = document.createElement('div');
            banner.style.cssText = `
                position:fixed; top:60px; left:50%; transform:translateX(-50%);
                background: ${color}22; border:1px solid ${color}; border-radius:4px;
                color:${color}; font-family:'Orbitron',monospace; font-size:11px;
                letter-spacing:2px; padding:10px 24px; z-index:9999;
                animation: alertSlide 0.3s ease; white-space:nowrap;
                box-shadow: 0 0 20px ${color}44;
            `;
            banner.textContent = `${icon} SYSTEM ALERT — ${text}`;
            document.body.appendChild(banner);
            setTimeout(() => {
                banner.style.transition = 'opacity 0.5s';
                banner.style.opacity = '0';
                setTimeout(() => banner.remove(), 500);
            }, 6000);
        }

        function speakText(text) {

            if (!synth) return;
            
            let cleanText = text.replace(/<[^>]+>/g, '') 
                                .replace(/\*\*/g, '')
                                .replace(/\*/g, '')
                                .replace(/■/g, '')
                                .replace(/\[.*?\]\(.*?\)/g, '');



            const utterance = new SpeechSynthesisUtterance(cleanText);
            
            if (!jarvisVoice) {
                const voices = synth.getVoices();
                jarvisVoice = voices.find(v => v.lang === 'en-GB' && v.name.includes('Male')) ||
                              voices.find(v => v.name.includes('Google UK English Male')) ||
                              voices.find(v => v.lang === 'en-GB') ||
                              voices.find(v => v.lang.startsWith('en'));
            }
            
            if (jarvisVoice) utterance.voice = jarvisVoice;
            utterance.rate = 1.05;
            utterance.pitch = 0.9;

            utterance.onstart = () => {
                if(!isListening) {
                    waveTarget = 25;
                    setText('waveMode', 'SPEAKING');
                }
            };
            
            utterance.onend = () => {
                if (!isBusy && !isListening) {
                    waveTarget = 6;
                    setText('waveMode', 'STANDBY');
                }
            };

            synth.speak(utterance);
        }
        
        let currentAudio = null;
        let mediaSource = null;
        let sourceBuffer = null;
        let audioChunkQueue = [];
        let isAppending = false;
        let audioStreamDone = false;

        function initAudioStream() {
            // Stop any currently playing audio
            if (currentAudio) {
                currentAudio.pause();
                currentAudio.src = '';
                currentAudio = null;
            }
            if (synth && synth.speaking) synth.cancel();

            audioChunkQueue = [];
            isAppending = false;
            audioStreamDone = false;

            // Create MediaSource for streaming MP3
            mediaSource = new MediaSource();
            const audioEl = new Audio();
            audioEl.src = URL.createObjectURL(mediaSource);
            currentAudio = audioEl;

            mediaSource.addEventListener('sourceopen', () => {
                try {
                    sourceBuffer = mediaSource.addSourceBuffer('audio/mpeg');
                    sourceBuffer.addEventListener('updateend', flushAudioQueue);
                    // Flush any chunks that arrived before sourceopen
                    flushAudioQueue();
                } catch(e) {
                    console.warn('MediaSource not supported, will use fallback', e);
                    sourceBuffer = null;
                }
            });

            audioEl.oncanplay = () => {
                if (!isListening) {
                    waveTarget = 30;
                    setText('waveMode', 'SPEAKING');
                }
                audioEl.play().catch(e => console.log('Autoplay blocked:', e));
            };

            audioEl.onended = () => {
                if (!isBusy && !isListening) {
                    waveTarget = 6;
                    setText('waveMode', 'STANDBY');
                }
            };
        }

        function appendAudioChunk(bytes) {
            if (!sourceBuffer) {
                // Queue for when sourceBuffer is ready
                audioChunkQueue.push(bytes);
                return;
            }
            audioChunkQueue.push(bytes);
            flushAudioQueue();
        }

        function flushAudioQueue() {
            if (!sourceBuffer || sourceBuffer.updating || audioChunkQueue.length === 0) return;
            try {
                const chunk = audioChunkQueue.shift();
                sourceBuffer.appendBuffer(chunk);
            } catch(e) {
                console.error('AppendBuffer error:', e);
            }
            // If stream is done and queue empty, end the stream
            if (audioStreamDone && audioChunkQueue.length === 0 && !sourceBuffer.updating) {
                try {
                    if (mediaSource && mediaSource.readyState === 'open') {
                        mediaSource.endOfStream();
                    }
                } catch(e) {}
            }
        }

        function finalizeAudioStream() {
            audioStreamDone = true;
            if (sourceBuffer && !sourceBuffer.updating && audioChunkQueue.length === 0) {
                try {
                    if (mediaSource && mediaSource.readyState === 'open') {
                        mediaSource.endOfStream();
                    }
                } catch(e) {}
            } else {
                // Let the updateend handler close it when queue drains
                flushAudioQueue();
            }
        }

        function playAudioBase64(base64Data) {
            // Legacy fallback for non-streaming responses
            if (currentAudio) {
                currentAudio.pause();
                currentAudio = null;
            }
            if (synth && synth.speaking) synth.cancel();
            try {
                const audio = new Audio('data:audio/mp3;base64,' + base64Data);
                audio.onplay = () => { if (!isListening) { waveTarget = 30; setText('waveMode', 'SPEAKING'); } };
                audio.onended = () => { if (!isBusy && !isListening) { waveTarget = 6; setText('waveMode', 'STANDBY'); } };
                currentAudio = audio;
                audio.play();
            } catch (err) {
                console.error('Base64 Audio Error:', err);
            }
        }

        // ══════════════════════════════════════
        //  INPUT
        // ══════════════════════════════════════
        document.getElementById('cmdInput').addEventListener('keydown', e => {
            if (e.key === 'Enter') sendMsg();
        });

        // ══════════════════════════════════════
        //  ANIMATIONS + INIT
        // ══════════════════════════════════════
        function startAllAnimations() {
            setInterval(tickClock, 1000);
            setInterval(updateVitals, 2000);
            setInterval(autoLog, 4500);
            tickClock();
            updateVitals();

            // Client-side HTML5 Battery API support for cloud servers
            if (navigator.getBattery) {
                navigator.getBattery().then(bat => {
                    const updateBatteryHUD = () => {
                        const pct = Math.round(bat.level * 100);
                        const status = bat.charging ? "Charging ⚡" : "On Battery";
                        setText('eBAT', `${pct}% — ${status}`);
                    };
                    updateBatteryHUD();
                    bat.addEventListener('levelchange', updateBatteryHUD);
                    bat.addEventListener('chargingchange', updateBatteryHUD);
                });
            }
        }

        // Always-on
        drawBG();
        initWeatherAndLocation();
        setInterval(initWeatherAndLocation, 15 * 60 * 1000); // Poll weather every 15 minutes
        drawWave();
        initNet();
        drawNet();
        tickClock();
        window.addEventListener('resize', drawBG);

        // ══════════════════════════════════════
        //  BOOT BINARY RAIN
        // ══════════════════════════════════════
        (function initBootBinaryRain() {
            const canvas = document.getElementById('bootBinaryCanvas');
            if (!canvas) return;
            const ctx = canvas.getContext('2d');
            let drops = [];
            let animId = null;

            function resize() {
                canvas.width = window.innerWidth;
                canvas.height = window.innerHeight;
                const cols = Math.floor(canvas.width / 18);
                drops = Array.from({ length: cols }, () => ({
                    x: Math.random() * canvas.width,
                    y: Math.random() * canvas.height,
                    speed: 0.3 + Math.random() * 0.7,
                    opacity: 0.1 + Math.random() * 0.6,
                    size: 10 + Math.random() * 6,
                    char: Math.random() > 0.5 ? '1' : '0',
                    tick: 0,
                    interval: 20 + Math.floor(Math.random() * 40),
                    color: Math.random() > 0.15 ? '#00e5ff' : '#ffc107'
                }));
            }

            function drawRain() {
                ctx.clearRect(0, 0, canvas.width, canvas.height);
                drops.forEach(d => {
                    ctx.save();
                    ctx.globalAlpha = d.opacity;
                    ctx.fillStyle = d.color;
                    ctx.font = `${d.size}px 'Share Tech Mono', monospace`;
                    ctx.shadowBlur = 8;
                    ctx.shadowColor = d.color;
                    ctx.fillText(d.char, d.x, d.y);
                    ctx.restore();

                    d.y -= d.speed;
                    d.tick++;
                    if (d.tick >= d.interval) {
                        d.char = Math.random() > 0.5 ? '1' : '0';
                        d.color = Math.random() > 0.15 ? '#00e5ff' : '#ffc107';
                        d.tick = 0;
                    }
                    if (d.y < -20) {
                        d.y = canvas.height + 20;
                        d.x = Math.random() * canvas.width;
                        d.opacity = 0.1 + Math.random() * 0.6;
                        d.speed = 0.3 + Math.random() * 0.7;
                    }
                });

                const bo = document.getElementById('bootOverlay');
                if (bo && bo.style.display !== 'none') {
                    animId = requestAnimationFrame(drawRain);
                } else {
                    animId = null;
                }
            }

            resize();
            window.addEventListener('resize', resize);
            drawRain();
        })();

        // ══════════════════════════════════════
        //  BOOT TYPEWRITER SEQUENCE
        // ══════════════════════════════════════
        const bootLines = [
            { id: 'bootLine0', text: 'ESTABLISHING NEURAL UPLINK...',    delay: 0 },
            { id: 'bootLine1', text: 'AUTHENTICATING CREDENTIALS...',    delay: 800 },
            { id: 'bootLine2', text: 'WELCOME BACK, SIR.',               delay: 1700 },
        ];

        function typeBootLine(lineId, text, onDone) {
            const el = document.getElementById(lineId);
            if (!el) { if (onDone) onDone(); return; }
            el.classList.add('visible');

            // Add cursor
            const cursor = document.createElement('span');
            cursor.className = 'boot-cursor';
            el.innerHTML = '';
            el.appendChild(cursor);

            let i = 0;
            const speed = lineId === 'bootLine2' ? 55 : 38; // welcome line types slower for drama
            function type() {
                if (i < text.length) {
                    // Insert char before cursor
                    const charNode = document.createTextNode(text[i]);
                    el.insertBefore(charNode, cursor);
                    i++;
                    setTimeout(type, speed + Math.random() * 25);
                } else {
                    // Done — remove cursor from this line (keep for last line)
                    if (lineId !== 'bootLine2') cursor.remove();
                    if (onDone) onDone();
                }
            }
            type();
        }

        // Speak a line in the JARVIS voice during boot (robust version)
        function bootSpeak(text) {
            const synth = window.speechSynthesis;
            if (!synth) return;
            synth.cancel();

            function doSpeak() {
                const voices = synth.getVoices();
                const voice =
                    voices.find(v => v.name === 'Google UK English Male') ||
                    voices.find(v => v.lang === 'en-GB' && /male/i.test(v.name)) ||
                    voices.find(v => v.lang === 'en-GB') ||
                    voices.find(v => v.lang === 'en-US' && /male/i.test(v.name)) ||
                    voices.find(v => v.lang.startsWith('en'));

                const u = new SpeechSynthesisUtterance(text);
                if (voice) u.voice = voice;
                u.lang   = 'en-GB';
                u.rate   = 0.9;
                u.pitch  = 0.82;
                u.volume = 1.0;
                synth.speak(u);
            }

            const voices = synth.getVoices();
            if (voices.length > 0) {
                // Small delay avoids Chrome race condition on boot
                setTimeout(doSpeak, 80);
            } else {
                synth.onvoiceschanged = () => {
                    synth.onvoiceschanged = null;
                    setTimeout(doSpeak, 80);
                };
            }
        }

        function runBootSequence() {
            typeBootLine('bootLine0', bootLines[0].text, () => {
                setTimeout(() => {
                    typeBootLine('bootLine1', bootLines[1].text, null);
                }, 300);
            });
        }

        // Start the typewriter immediately on page load
        runBootSequence();

        // Connect WebSocket to Python backend
        function connectWS() {
            const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
            const host = window.location.host || 'localhost:8000';
            ws = new WebSocket(`${proto}//${host}/ws`);

            ws.onopen = () => {
                wsReady = true;
                log('SYSTEM', 'Backend WebSocket connected', 'ok');

                // Phase 4: Verify JWT first; fall back to check_saved_key or API overlay
                setTimeout(async () => {
                    const storedToken = localStorage.getItem('jarvis_jwt') || '';
                    if (storedToken) {
                        try {
                            const res = await fetch(`/api/verify?token=${encodeURIComponent(storedToken)}`);
                            const data = await res.json();
                            if (data.valid) {
                                jarvisToken = storedToken;
                                ws.send(JSON.stringify({ type: 'init_jwt', token: storedToken, name: data.user_name }));
                                log('SECURITY', `🔒 JWT session verified — ${data.user_name}`, 'ok');
                                return;
                            } else {
                                localStorage.removeItem('jarvis_jwt');
                                jarvisToken = '';
                                log('SECURITY', `JWT expired (${data.reason}), re-auth required`, 'warn');
                            }
                        } catch(e) {
                            console.warn('JWT verify failed:', e);
                        }
                    }
                    ws.send(JSON.stringify({ type: 'check_saved_key' }));
                }, 1800);
            };

            ws.onmessage = (e) => {
                // Handle binary audio chunks (Phase 2 streaming)
                if (e.data instanceof Blob) {
                    e.data.arrayBuffer().then(buf => appendAudioChunk(buf));
                    return;
                }

                const data = JSON.parse(e.data);
                if (data.type === 'init_ok') {
                    const bo = document.getElementById('bootOverlay');
                    if (bo) {
                        bo.style.opacity = '0';
                        setTimeout(() => bo.style.display = 'none', 800);
                    }
                    document.getElementById('apiOverlay').style.display = 'none';
                    appendMsg('ai', data.message, 'sys');
                    log('SYSTEM', 'Neural interface online', 'ok');
                    detectEnv();
                    startAllAnimations();
                    sessionStartTime = Date.now();   // start JARVIS session uptime
                    setText('hUptime', '00:00:00');   // reset display immediately
                    // Fire agent-status polling
                    document.dispatchEvent(new CustomEvent('jarvis:init_ok'));
                } else if (data.type === 'init_warning') {
                    const input = document.getElementById('userNameInput');
                    input.style.borderColor = 'var(--warn)';
                    input.value = '';
                    input.placeholder = data.message;
                    const keyInput = document.getElementById('apiKeyInput');
                    keyInput.style.borderColor = 'var(--red)';
                    const btn = document.querySelector('.api-btn');
                    btn.innerText = '▶ INITIALIZE ALL SYSTEMS';
                    btn.disabled = false;
                } else if (data.type === 'init_fail') {
                    const bo = document.getElementById('bootOverlay');
                    if (bo) bo.style.display = 'none';
                    document.getElementById('apiKeyInput').style.borderColor = 'var(--red)';
                    document.getElementById('apiKeyInput').value = '';
                    document.getElementById('apiKeyInput').placeholder = 'Invalid API Key!';
                    document.getElementById('apiOverlay').style.display = 'flex';
                } else if (data.type === 'response') {
                    hideTyping();
                    if (data.tag === 'search') {
                        searchCount++;
                        setText('hSearches', searchCount);
                    }
                    appendMsg('ai', data.text, data.tag);

                    if (data.audio_streaming) {
                        // Phase 2: Initialize MediaSource stream — chunks will arrive as binary frames
                        initAudioStream();
                    } else if (data.audio_base64) {
                        playAudioBase64(data.audio_base64);
                    } else if (data.should_speak) {
                        speakText(data.text);
                    }
                } else if (data.type === 'audio_done') {
                    // Phase 2: All audio chunks received, finalize the stream
                    finalizeAudioStream();
                } else if (data.type === 'proactive_alert') {
                    // Phase 3: Proactive Agent Alert
                    showProactiveAlert(data.alert_type, data.text);
                    initAudioStream(); // Audio chunks incoming as binary frames
                } else if (data.type === 'stats') {
                    if (data.connected === false) {
                        isAgentConnected = false;
                        updateVitals();
                    } else {
                        isAgentConnected = true;
                        const s = data.data;
                        setVital('vCPU', s.cpu, 'bCPU', parseFloat(s.cpu));
                        setVital('vMEM', s.ram.split(' ')[0], 'bMEM', parseFloat(s.ram));
                        if (s.net_kbs !== undefined) setVital('vNET', s.net_kbs, 'bNET', parseFloat(s.net_pct));
                        if (s.disk_mbs !== undefined) setVital('vDSK', s.disk_mbs, 'bDSK', parseFloat(s.disk_pct));
                        if (!navigator.getBattery || s.battery !== "N/A") {
                            setText('eBAT', s.battery);
                        }
                        setText('ePROC', s.processes);

                        // Fluctuating GPU/system temp based on CPU load
                        const cpuVal = parseFloat(s.cpu) || 10;
                        const fakeTemp = Math.round(30 + (cpuVal * 0.35) + Math.random() * 4);
                        setVital('vTMP', fakeTemp + '°C', 'bTMP', fakeTemp);
                    }
                } else if (data.type === 'error') {
                    hideTyping();
                    appendMsg('ai', 'Error: ' + data.message, 'err');
                } else if (data.type === 'no_saved_key') {
                    const bo = document.getElementById('bootOverlay');
                    if (bo) bo.style.display = 'none';
                    document.getElementById('apiOverlay').style.display = 'flex';
                    const savedName = localStorage.getItem('jarvis_user_name') || '';
                    if (savedName) document.getElementById('userNameInput').value = savedName;
                }
            };

            ws.onclose = () => {
                wsReady = false;
                log('SYSTEM', 'WebSocket disconnected', 'err');
                const bo = document.getElementById('bootOverlay');
                if (bo) {
                    bo.style.display = 'flex';
                    bo.style.opacity = '1';
                    // Reset sequence lines for reconnect
                    ['bootLine0','bootLine1','bootLine2'].forEach(id => {
                        const el = document.getElementById(id);
                        if (el) { el.innerHTML = ''; el.classList.remove('visible'); }
                    });
                    setTimeout(() => {
                        typeBootLine('bootLine0', 'RECONNECTING TO BACKEND...', null);
                    }, 200);
                } else {
                    document.getElementById('apiOverlay').style.display = 'flex';
                    document.getElementById('apiKeyInput').placeholder = 'Reconnecting to backend...';
                }
                setTimeout(connectWS, 3000);
            };
        }

        connectWS();


        // ══════════════════════════════════════════════════
        //  AGENT STATUS — Banner & Download Notification
        // ══════════════════════════════════════════════════
        let agentBannerDismissed = false;
        let agentPollInterval   = null;

        function showAgentBanner(show) {
            const banner = document.getElementById('agentBanner');
            if (!banner) return;
            if (show && !agentBannerDismissed) {
                banner.style.display = 'flex';
            } else {
                banner.style.display = 'none';
            }
        }

        function dismissAgentBanner() {
            agentBannerDismissed = true;
            showAgentBanner(false);
        }

        async function checkAgentStatus() {
            const token = jarvisToken || localStorage.getItem('jarvis_jwt') || '';
            if (!token) return;   // Not logged in yet — skip
            try {
                const res  = await fetch(`/api/agent_status?token=${encodeURIComponent(token)}`);
                const data = await res.json();
                const connected = data.connected === true;

                // Update the SYS AGENT dot in the header using stable ID selection
                const agentDot = document.getElementById('agentDot');
                if (agentDot) {
                    agentDot.className = connected
                        ? 'dot dot-green'
                        : 'dot dot-warn';
                }

                isAgentConnected = connected;
                updateVitals();
                showAgentBanner(!connected);
            } catch (e) {
                // Silently ignore network errors during polling
                console.debug('Agent status check failed:', e);
            }
        }

        function startAgentPolling() {
            // Run immediately, then every 15 seconds
            checkAgentStatus();
            if (agentPollInterval) clearInterval(agentPollInterval);
            agentPollInterval = setInterval(checkAgentStatus, 15000);
        }

        // Hook into init_ok: start polling once the user is authenticated
        const _origOnmessage = null; // placeholder, we patch below

        // Patch the ws.onmessage handler to call startAgentPolling on init_ok.
        // We do this by wrapping the connectWS logic via a post-message interceptor.
        document.addEventListener('jarvis:init_ok', () => {
            startAgentPolling();
        });

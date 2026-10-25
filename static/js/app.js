// Global Thin Client App JS

function updateGlobalStatus() {
    fetch('/api/status')
    .then(r => r.json())
    .then(data => {
        // Wi-Fi badge
        const wifiBadge = document.getElementById('badge-wifi');
        const wifiText = document.getElementById('wifi-status-text');
        const cardWifiVal = document.getElementById('card-wifi-val');
        const cardWifiSub = document.getElementById('card-wifi-sub');

        const wf = data.network?.wifi || {};
        const eth = data.network?.ethernet || {};
        const isOnline = wf.connected || eth.connected;

        if (wifiBadge && wifiText) {
            if (wf.connected) {
                wifiBadge.className = 'status-badge badge-connected';
                wifiText.innerText = `${wf.ssid} (${wf.signal}%)`;
            } else if (eth.connected) {
                wifiBadge.className = 'status-badge badge-connected';
                wifiText.innerText = `Ethernet`;
            } else {
                wifiBadge.className = 'status-badge badge-disconnected';
                wifiText.innerText = `Disconnesso`;
            }
        }

        if (cardWifiVal) {
            if (wf.connected) {
                cardWifiVal.innerText = wf.ssid;
                cardWifiVal.style.color = "#4ade80";
                cardWifiSub.innerText = `Segnale: ${wf.signal}% | IP: ${wf.ip || '--'}`;
            } else if (eth.connected) {
                cardWifiVal.innerText = "Ethernet";
                cardWifiVal.style.color = "#4ade80";
                cardWifiSub.innerText = `IP: ${eth.ip || '--'}`;
            } else {
                cardWifiVal.innerText = "Disconnesso";
                cardWifiVal.style.color = "#f87171";
                cardWifiSub.innerText = "Nessuna rete locale";
            }
        }

        // Tailscale badge
        const tsBadge = document.getElementById('badge-tailscale');
        const tsText = document.getElementById('tailscale-status-text');
        const cardTsVal = document.getElementById('card-ts-val');
        const cardTsSub = document.getElementById('card-ts-sub');
        const ts = data.tailscale || {};

        if (tsBadge && tsText) {
            if (ts.connected) {
                tsBadge.className = 'status-badge badge-connected';
                tsText.innerText = `Connesso`;
            } else {
                tsBadge.className = 'status-badge badge-disconnected';
                tsText.innerText = `Non Connesso`;
            }
        }

        if (cardTsVal) {
            if (ts.connected) {
                cardTsVal.innerText = "CONNESSO";
                cardTsVal.style.color = "#4ade80";
                cardTsSub.innerText = `IP: ${ts.ip || '--'}`;
            } else {
                cardTsVal.innerText = "NON CONNESSO";
                cardTsVal.style.color = "#f87171";
                cardTsSub.innerText = "Verificare connessione";
            }
        }

        // Footer info
        const footerInfo = document.getElementById('system-info-text');
        if (footerInfo) {
            const primaryIp = data.network?.primary_ip || '--';
            const tsIp = ts.ip || '--';
            footerInfo.innerText = `IP Locale: ${primaryIp} | Tailscale IP: ${tsIp}`;
        }

        const footerVersion = document.getElementById('footer-version');
        if (footerVersion && data.version) {
            footerVersion.innerText = `v${data.version}`;
        }

        // VNC Remote Assistance Badge
        const vncBadge = document.getElementById('badge-vnc');
        if (vncBadge) {
            const vnc = data.vnc || {};
            if (vnc.clients_count && vnc.clients_count > 0) {
                vncBadge.style.display = 'flex';
            } else {
                vncBadge.style.display = 'none';
            }
        }
    })
    .catch(err => {
        console.error("Error polling status:", err);
    });
}

function showModal(title, message) {
    const modal = document.getElementById('app-modal');
    document.getElementById('modal-title').innerText = title;
    document.getElementById('modal-message').innerText = message;
    modal.style.display = 'flex';
}

function closeModal() {
    document.getElementById('app-modal').style.display = 'none';
}

// Initial status check & periodic polling every 15 seconds (reduced overhead for Raspberry Pi)
updateGlobalStatus();
setInterval(updateGlobalStatus, 15000);

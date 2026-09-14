#include "wifi_v2.h"

#include <esp_wifi.h>
#include <mbedtls/md.h>
#include <mbedtls/sha256.h>

namespace {
String bytesToHex(const uint8_t* bytes, size_t length) {
    static const char digits[] = "0123456789abcdef";
    String result;
    result.reserve(length * 2);
    for (size_t i = 0; i < length; ++i) {
        result += digits[(bytes[i] >> 4) & 0x0F];
        result += digits[bytes[i] & 0x0F];
    }
    return result;
}
}

void WifiV2Manager::begin(SnapshotHandler handler) {
    _snapshotHandler = handler;
    uint64_t chipId = ESP.getEfuseMac();
    char idBuffer[32];
    snprintf(idBuffer, sizeof(idBuffer), "esp32s3_%04X%08X",
             static_cast<uint16_t>(chipId >> 32), static_cast<uint32_t>(chipId));
    _deviceId = idBuffer;

    _prefs.begin("hud_v2_0", false);
    loadConfiguration();
    WiFi.mode(WIFI_STA);
    esp_wifi_set_country_code("SG", false);
    WiFi.setAutoReconnect(false);
    WiFi.onEvent([this](WiFiEvent_t event, WiFiEventInfo_t info) {
        if (event == ARDUINO_EVENT_WIFI_STA_DISCONNECTED) {
            _lastDisconnectReason = info.wifi_sta_disconnected.reason;
        }
    });
    _webSocket.onEvent([this](WStype_t type, uint8_t* payload, size_t length) {
        onWebSocketEvent(type, payload, length);
    });
    // arduinoWebSockets interprets 0 as "retry immediately", not "disabled".
    // Keep reconnects parked until a fresh UDP OFFER supplies a fresh nonce.
    _webSocket.setReconnectInterval(0xFFFFFFFFUL);
    _webSocket.enableHeartbeat(15000, 3000, 2);

    if (_activeSsid.isEmpty()) {
        setState(WifiV2State::WIFI_NO_CREDENTIALS);
    } else {
        startWifi(_activeSsid, _activePassword);
    }
    sendDeviceStatus();
}

void WifiV2Manager::loadConfiguration() {
    _activeSsid = _prefs.getString("ssid_active", "");
    _activePassword = _prefs.getString("pass_active", "");
    _activeManualHost = _prefs.getString("host_active", "");
    _pairingSecret = _prefs.getString("pair_secret", "");
    _serverId = _prefs.getString("server_id", "");
    _lastHost = _prefs.getString("last_host", "");
}

void WifiV2Manager::setState(WifiV2State state) {
    if (_state == state) return;
    _state = state;
    _stateSince = millis();
    sendDeviceStatus();
}

String WifiV2Manager::stateText() const {
    switch (_state) {
        case WifiV2State::WIFI_NO_CREDENTIALS: return "需要 USB 配网";
        case WifiV2State::WIFI_CONNECTING: return "Wi-Fi 连接中";
        case WifiV2State::HOST_DISCOVERING: return "寻找 Host";
        case WifiV2State::WS_AUTHENTICATING: return "安全认证中";
        case WifiV2State::ONLINE: return "Wi-Fi 在线";
        case WifiV2State::DEGRADED_SERIAL: return "USB 模式";
        case WifiV2State::OFFLINE:
        default: return "网络离线";
    }
}

String WifiV2Manager::ipText() const {
    return WiFi.status() == WL_CONNECTED ? WiFi.localIP().toString() : "";
}

int32_t WifiV2Manager::rssi() const {
    return WiFi.status() == WL_CONNECTED ? WiFi.RSSI() : 0;
}

void WifiV2Manager::startWifi(const String& ssid, const String& password) {
    _authenticated = false;
    _nonce = "";
    _streamId = "";
    _lastSeq = 0;
    _lastDisconnectReason = 0;
    if (_wsStarted) {
        _webSocket.disconnect();
        _wsStarted = false;
    }
    if (_udpStarted) {
        _udp.stop();
        _udpStarted = false;
    }
    WiFi.disconnect(false, false);
    delay(50);
    WiFi.begin(ssid.c_str(), password.c_str());
    setState(WifiV2State::WIFI_CONNECTING);
}

bool WifiV2Manager::startScanPass() {
    WiFi.scanDelete();
    int result = WiFi.scanNetworks(true, false, true, 400);
    if (result == WIFI_SCAN_FAILED) return false;
    _scanInProgress = true;
    return true;
}

void WifiV2Manager::collectScanResults(int count) {
    for (int i = 0; i < count; ++i) {
        String ssid = WiFi.SSID(i);
        if (ssid.isEmpty()) continue;
        int32_t signal = WiFi.RSSI(i);
        wifi_auth_mode_t auth = WiFi.encryptionType(i);
        int existing = -1;
        for (uint8_t index = 0; index < _scanResultCount; ++index) {
            if (_scanSsids[index] == ssid) {
                existing = index;
                break;
            }
        }
        if (existing >= 0) {
            if (signal > _scanRssi[existing]) {
                _scanRssi[existing] = signal;
                _scanAuth[existing] = auth;
            }
            continue;
        }
        if (_scanResultCount >= WIFI_SCAN_MAX_RESULTS) continue;
        _scanSsids[_scanResultCount] = ssid;
        _scanRssi[_scanResultCount] = signal;
        _scanAuth[_scanResultCount] = auth;
        ++_scanResultCount;
    }
}

void WifiV2Manager::finishWifiScan() {
    for (uint8_t left = 0; left < _scanResultCount; ++left) {
        for (uint8_t right = left + 1; right < _scanResultCount; ++right) {
            if (_scanRssi[right] <= _scanRssi[left]) continue;
            String ssid = _scanSsids[left];
            _scanSsids[left] = _scanSsids[right];
            _scanSsids[right] = ssid;
            int32_t signal = _scanRssi[left];
            _scanRssi[left] = _scanRssi[right];
            _scanRssi[right] = signal;
            wifi_auth_mode_t auth = _scanAuth[left];
            _scanAuth[left] = _scanAuth[right];
            _scanAuth[right] = auth;
        }
    }

    JsonDocument reply;
    reply["type"] = "WIFI_SCAN_RESULT";
    reply["request_id"] = _scanRequestId;
    JsonArray networks = reply["networks"].to<JsonArray>();
    for (uint8_t i = 0; i < _scanResultCount; ++i) {
        JsonObject item = networks.add<JsonObject>();
        item["ssid"] = _scanSsids[i];
        item["rssi"] = _scanRssi[i];
        item["auth"] = _scanAuth[i] == WIFI_AUTH_OPEN ? "OPEN" : "SECURED";
    }
    sendResponse(reply);
    _scanRequestId = "";
    _scanInProgress = false;
    _scanPass = 0;
    _scanResultCount = 0;
}

void WifiV2Manager::processWifiScan() {
    if (!_scanInProgress) return;
    int count = WiFi.scanComplete();
    if (count == WIFI_SCAN_RUNNING) return;
    if (count == WIFI_SCAN_FAILED) {
        String requestId = _scanRequestId;
        _scanRequestId = "";
        _scanInProgress = false;
        _scanPass = 0;
        _scanResultCount = 0;
        sendSimpleError(requestId, "WIFI_SCAN_ERROR", "SCAN_FAILED", "Wi-Fi scan failed");
        return;
    }
    collectScanResults(count);
    WiFi.scanDelete();
    ++_scanPass;
    if (_scanPass < WIFI_SCAN_PASSES) {
        if (!startScanPass()) {
            String requestId = _scanRequestId;
            _scanRequestId = "";
            _scanInProgress = false;
            _scanPass = 0;
            _scanResultCount = 0;
            sendSimpleError(requestId, "WIFI_SCAN_ERROR", "SCAN_FAILED", "Wi-Fi scan failed");
        }
        return;
    }
    finishWifiScan();
}

void WifiV2Manager::startDiscovery() {
    _nonce = "";
    if (!_udpStarted) {
        _udp.begin(UDP_LOCAL_PORT);
        _udpStarted = true;
    }
    _discoveryStage = 0;
    _lastDiscoveryAt = 0;
    setState(WifiV2State::HOST_DISCOVERING);
}

void WifiV2Manager::sendDiscovery(const IPAddress& target) {
    JsonDocument doc;
    doc["type"] = "DISCOVER";
    doc["protocol_version"] = PROTOCOL_VERSION;
    doc["device_id"] = _deviceId;
    doc["server_id"] = _serverId;
    String payload;
    serializeJson(doc, payload);
    _udp.beginPacket(target, UDP_PORT);
    _udp.write(reinterpret_cast<const uint8_t*>(payload.c_str()), payload.length());
    _udp.endPacket();
    _lastDiscoveryAt = millis();
}

void WifiV2Manager::processDiscoveryResponses() {
    int packetSize = _udp.parsePacket();
    if (packetSize <= 0) return;
    if (packetSize > static_cast<int>(MAX_FRAME_BYTES)) {
        while (_udp.available()) _udp.read();
        return;
    }
    char buffer[MAX_FRAME_BYTES + 1];
    int length = _udp.read(buffer, MAX_FRAME_BYTES);
    if (length <= 0) return;
    buffer[length] = '\0';
    JsonDocument doc;
    if (deserializeJson(doc, buffer, length)) return;
    if (String(doc["type"] | "") != "OFFER") return;
    if (String(doc["protocol_version"] | "") != PROTOCOL_VERSION) return;
    if (String(doc["device_id"] | "") != _deviceId) return;
    if (String(doc["server_id"] | "") != _serverId) return;
    _nonce = String(doc["nonce"] | "");
    if (_nonce.isEmpty()) return;
    connectWebSocket(_udp.remoteIP());
}

void WifiV2Manager::connectWebSocket(const IPAddress& host) {
    _lastHost = host.toString();
    // begin() resets the library's last-failure timestamp. A zero interval
    // permits exactly the initial connection attempt; WStype_CONNECTED parks
    // library-level retries again so a disconnect must return to discovery.
    _webSocket.setReconnectInterval(0);
    _webSocket.begin(_lastHost.c_str(), WS_PORT, "/");
    _wsStarted = true;
    setState(WifiV2State::WS_AUTHENTICATING);
}

String WifiV2Manager::hmacHex(const String& message) const {
    uint8_t output[32];
    const mbedtls_md_info_t* info = mbedtls_md_info_from_type(MBEDTLS_MD_SHA256);
    if (!info) return "";
    int result = mbedtls_md_hmac(
        info,
        reinterpret_cast<const unsigned char*>(_pairingSecret.c_str()), _pairingSecret.length(),
        reinterpret_cast<const unsigned char*>(message.c_str()), message.length(), output);
    return result == 0 ? bytesToHex(output, sizeof(output)) : "";
}

String WifiV2Manager::sha256Prefix(const String& value) const {
    uint8_t output[32];
    if (mbedtls_sha256_ret(reinterpret_cast<const unsigned char*>(value.c_str()), value.length(), output, 0) != 0) {
        return "";
    }
    return bytesToHex(output, 8);
}

bool WifiV2Manager::constantTimeEquals(const String& left, const String& right) const {
    if (left.length() != right.length()) return false;
    uint8_t diff = 0;
    for (size_t i = 0; i < left.length(); ++i) diff |= static_cast<uint8_t>(left[i] ^ right[i]);
    return diff == 0;
}

void WifiV2Manager::sendAuth() {
    String message = _nonce + "|" + _deviceId + "|" + _serverId + "|" + PROTOCOL_VERSION;
    JsonDocument doc;
    doc["type"] = "AUTH";
    doc["protocol_version"] = PROTOCOL_VERSION;
    doc["device_id"] = _deviceId;
    doc["server_id"] = _serverId;
    doc["nonce"] = _nonce;
    doc["signature"] = hmacHex(message);
    String payload;
    serializeJson(doc, payload);
    _webSocket.sendTXT(payload);
}

void WifiV2Manager::onWebSocketEvent(WStype_t type, uint8_t* payload, size_t length) {
    if (type == WStype_CONNECTED) {
        _webSocket.setReconnectInterval(0xFFFFFFFFUL);
        sendAuth();
    } else if (type == WStype_TEXT) {
        if (length > MAX_FRAME_BYTES) return;
        processWebSocketText(payload, length);
    } else if (type == WStype_DISCONNECTED) {
        _authenticated = false;
        _wsStarted = false;
        _nonce = "";
        _webSocket.setReconnectInterval(0xFFFFFFFFUL);
        if (WiFi.status() == WL_CONNECTED) startDiscovery();
    }
}

void WifiV2Manager::processWebSocketText(const uint8_t* payload, size_t length) {
    JsonDocument doc;
    if (deserializeJson(doc, payload, length)) return;
    String type = String(doc["type"] | "");
    if (type == "AUTH_OK") {
        if (String(doc["protocol_version"] | "") != PROTOCOL_VERSION) return;
        if (String(doc["device_id"] | "") != _deviceId || String(doc["server_id"] | "") != _serverId) return;
        String supplied = String(doc["signature"] | "");
        String expected = hmacHex("AUTH_OK|" + _nonce + "|" + _deviceId + "|" + _serverId + "|" + PROTOCOL_VERSION);
        if (!constantTimeEquals(supplied, expected)) {
            _webSocket.disconnect();
            return;
        }
        _authenticated = true;
        _prefs.putString("last_host", _lastHost);
        setState(WifiV2State::ONLINE);
        if (_pendingConfig) commitPending();
        return;
    }
    if (type == "SNAPSHOT" && _authenticated) acceptSnapshot(doc.as<JsonObjectConst>());
}

void WifiV2Manager::acceptSnapshot(JsonObjectConst frame) {
    if (String(frame["protocol_version"] | "") != PROTOCOL_VERSION) return;
    String streamId = String(frame["stream_id"] | "");
    uint64_t seq = frame["seq"] | 0;
    if (streamId.isEmpty() || seq == 0) return;
    if (streamId != _streamId) {
        _streamId = streamId;
        _lastSeq = seq;
    } else {
        if (seq <= _lastSeq) return;
        _lastSeq = seq;
    }
    JsonObjectConst payload = frame["payload"].as<JsonObjectConst>();
    if (!payload.isNull() && _snapshotHandler) _snapshotHandler(payload);
}

bool WifiV2Manager::handleSerialSnapshot(JsonObjectConst frame) {
    if (String(frame["type"] | "") != "SNAPSHOT") return false;
    acceptSnapshot(frame);
    return true;
}

void WifiV2Manager::commitPending() {
    _prefs.putString("ssid_active", _pendingSsid);
    _prefs.putString("pass_active", _pendingPassword);
    _prefs.putString("host_active", _pendingManualHost);
    _prefs.remove("ssid_pending");
    _prefs.remove("pass_pending");
    _prefs.remove("host_pending");
    _activeSsid = _pendingSsid;
    _activePassword = _pendingPassword;
    _activeManualHost = _pendingManualHost;

    JsonDocument reply;
    reply["type"] = "WIFI_CONFIG_OK";
    reply["request_id"] = _pendingRequestId;
    reply["ip"] = WiFi.localIP().toString();
    reply["rssi"] = WiFi.RSSI();
    sendResponse(reply);
    _pendingConfig = false;
    _pendingPassword = "";
    _pendingRequestId = "";
}

void WifiV2Manager::failPending(const char* code, const char* message) {
    if (!_pendingConfig) return;
    sendSimpleError(_pendingRequestId, "WIFI_CONFIG_ERROR", code, message);
    _prefs.remove("ssid_pending");
    _prefs.remove("pass_pending");
    _prefs.remove("host_pending");
    _pendingConfig = false;
    _pendingPassword = "";
    _pendingRequestId = "";
    restoreActive();
}

void WifiV2Manager::restoreActive() {
    if (_activeSsid.isEmpty()) {
        WiFi.disconnect(false, false);
        setState(WifiV2State::WIFI_NO_CREDENTIALS);
    } else {
        startWifi(_activeSsid, _activePassword);
    }
}

void WifiV2Manager::failPendingWifiConnection() {
    // ESP-IDF disconnect reasons: 201=no AP, 202=auth fail,
    // 203=association fail, 204=handshake timeout. Legacy authentication
    // failures also surface as reasons 2 or 15.
    switch (_lastDisconnectReason) {
        case 201:
            failPending("WIFI_AP_NOT_FOUND", "Selected 2.4GHz access point was not found; scan again and select the exact SSID");
            return;
        case 2:
        case 15:
        case 202:
        case 204:
            failPending("WIFI_AUTH_FAILED", "Router rejected authentication; verify the Wi-Fi password and use WPA2 or WPA2/WPA3 compatibility mode");
            return;
        case 4:
        case 203:
            failPending("WIFI_ASSOC_FAILED", "Router rejected device association; check access control and WPA compatibility settings");
            return;
        default:
            failPending("WIFI_CONNECT_TIMEOUT", "Connection timed out; verify the password, 2.4GHz SSID, and router compatibility settings");
            return;
    }
}

void WifiV2Manager::sendResponse(JsonDocument& doc) {
    serializeJson(doc, Serial);
    Serial.println();
}

void WifiV2Manager::sendSimpleError(const String& requestId, const char* type, const char* code, const char* message) {
    JsonDocument reply;
    reply["type"] = type;
    reply["request_id"] = requestId;
    reply["code"] = code;
    reply["message"] = message;
    sendResponse(reply);
}

bool WifiV2Manager::handleUsbCommand(JsonObjectConst command) {
    String type = String(command["type"] | "");
    String requestId = String(command["request_id"] | "");

    if (type == "PAIRING_SET") {
        String version = String(command["protocol_version"] | "");
        String serverId = String(command["server_id"] | "");
        String secret = String(command["pairing_secret"] | "");
        if (version != PROTOCOL_VERSION || serverId.isEmpty() || secret.length() < 32) {
            sendSimpleError(requestId, "PAIRING_ERROR", "INVALID_PAIRING", "Invalid V2.0 pairing payload");
            return true;
        }
        _pairingSecret = secret;
        _serverId = serverId;
        _prefs.putString("pair_secret", _pairingSecret);
        _prefs.putString("server_id", _serverId);
        JsonDocument reply;
        reply["type"] = "PAIRING_OK";
        reply["request_id"] = requestId;
        reply["device_id"] = _deviceId;
        reply["fingerprint"] = sha256Prefix(_pairingSecret);
        sendResponse(reply);
        return true;
    }

    if (type == "PAIRING_CLEAR") {
        _pairingSecret = "";
        _serverId = "";
        _authenticated = false;
        _prefs.remove("pair_secret");
        _prefs.remove("server_id");
        _webSocket.disconnect();
        JsonDocument reply;
        reply["type"] = "PAIRING_CLEARED";
        reply["request_id"] = requestId;
        reply["device_id"] = _deviceId;
        sendResponse(reply);
        return true;
    }

    if (type == "WIFI_SCAN_REQUEST") {
        if (_scanInProgress) {
            sendSimpleError(requestId, "WIFI_SCAN_ERROR", "SCAN_BUSY", "Wi-Fi scan already running");
            return true;
        }
        _scanRequestId = requestId;
        _scanPass = 0;
        _scanResultCount = 0;
        if (!startScanPass()) {
            _scanRequestId = "";
            sendSimpleError(requestId, "WIFI_SCAN_ERROR", "SCAN_FAILED", "Wi-Fi scan failed");
        }
        return true;
    }

    if (type == "WIFI_CONFIG_SET") {
        String ssid = String(command["ssid"] | "");
        String password = String(command["password"] | "");
        String manualHost = String(command["manual_host_ip"] | "");
        if (_pairingSecret.isEmpty() || _serverId.isEmpty()) {
            sendSimpleError(requestId, "WIFI_CONFIG_ERROR", "PAIR_REQUIRED", "Pair the device over USB first");
            return true;
        }
        if (ssid.isEmpty() || ssid.length() > 32 || password.length() > 64) {
            sendSimpleError(requestId, "WIFI_CONFIG_ERROR", "INVALID_CONFIG", "Invalid SSID or password length");
            return true;
        }
        IPAddress parsed;
        if (!manualHost.isEmpty() && !parsed.fromString(manualHost)) {
            sendSimpleError(requestId, "WIFI_CONFIG_ERROR", "INVALID_HOST_IP", "Invalid manual Host IPv4 address");
            return true;
        }
        _pendingSsid = ssid;
        _pendingPassword = password;
        _pendingManualHost = manualHost;
        _pendingRequestId = requestId;
        _pendingConfig = true;
        _prefs.putString("ssid_pending", ssid);
        _prefs.putString("pass_pending", password);
        _prefs.putString("host_pending", manualHost);
        startWifi(_pendingSsid, _pendingPassword);
        return true;
    }

    if (type == "WIFI_STATUS_REQUEST") {
        sendDeviceStatus();
        return true;
    }
    return false;
}

void WifiV2Manager::sendDeviceStatus() {
    JsonDocument doc;
    doc["type"] = "DEVICE_STATUS";
    doc["protocol_version"] = PROTOCOL_VERSION;
    doc["device_id"] = _deviceId;
    doc["network_state"] = stateText();
    doc["paired"] = !_pairingSecret.isEmpty();
    doc["ssid"] = WiFi.status() == WL_CONNECTED ? WiFi.SSID() : "";
    doc["ip"] = ipText();
    doc["rssi"] = rssi();
    sendResponse(doc);
    _lastStatusAt = millis();
}

void WifiV2Manager::sendKeyPress() {
    JsonDocument doc;
    doc["event"] = "KEY_PRESS";
    doc["key"] = "BOOT";
    doc["action"] = "APPROVE";
    doc["device_id"] = _deviceId;
    String payload;
    serializeJson(doc, payload);
    if (_authenticated) _webSocket.sendTXT(payload);
    serializeJson(doc, Serial);
    Serial.println();
}

void WifiV2Manager::clearConfiguration() {
    _webSocket.disconnect();
    _udp.stop();
    WiFi.disconnect(true, true);
    _prefs.clear();
    _pairingSecret = "";
    _serverId = "";
    _activeSsid = "";
    _activePassword = "";
    _activeManualHost = "";
    _pendingConfig = false;
    _authenticated = false;
    _udpStarted = false;
    _wsStarted = false;
    setState(WifiV2State::WIFI_NO_CREDENTIALS);
}

void WifiV2Manager::loop() {
    _webSocket.loop();
    processWifiScan();
    unsigned long now = millis();

    if (_state == WifiV2State::WIFI_CONNECTING) {
        if (WiFi.status() == WL_CONNECTED) {
            startDiscovery();
        } else if (now - _stateSince > 15000) {
            if (_pendingConfig) {
                failPendingWifiConnection();
            } else {
                setState(WifiV2State::OFFLINE);
            }
        }
    } else if (_state == WifiV2State::HOST_DISCOVERING) {
        processDiscoveryResponses();
        // A discovery reply can synchronously advance the FSM to
        // WS_AUTHENTICATING. Do not continue evaluating HOST_DISCOVERING with
        // the old `now` value: `now - _stateSince` would underflow and falsely
        // trigger HOST_UNREACHABLE.
        if (_state != WifiV2State::HOST_DISCOVERING) return;
        unsigned long elapsed = now - _stateSince;
        if (now - _lastDiscoveryAt >= 2000) {
            // Never leave broadcast discovery behind permanently. A Mac can
            // receive a new DHCP address after reboot, making both last_host
            // and a previously entered manual Host IP stale. Alternate a LAN
            // broadcast with the two cached unicast hints so recovery remains
            // bounded while known addresses still provide a fast path.
            IPAddress target(255, 255, 255, 255);
            String manual = _pendingConfig ? _pendingManualHost : _activeManualHost;
            uint8_t stage = _discoveryStage++ % 4;
            if (stage == 1 && !_lastHost.isEmpty()) {
                if (!target.fromString(_lastHost)) target.fromString("255.255.255.255");
            } else if (stage == 3 && !manual.isEmpty()) {
                if (!target.fromString(manual)) target.fromString("255.255.255.255");
            }
            sendDiscovery(target);
        }
        if (_pendingConfig && elapsed > 35000) {
            failPending("HOST_UNREACHABLE", "Wi-Fi connected but the paired Host was not reachable");
        }
    } else if (_state == WifiV2State::WS_AUTHENTICATING) {
        if (_pendingConfig && now - _stateSince > 10000) {
            failPending("AUTH_TIMEOUT", "Host authentication timed out");
        } else if (!_pendingConfig && now - _stateSince > 10000) {
            startDiscovery();
        }
    } else if (_state == WifiV2State::OFFLINE) {
        unsigned long delayMs = min<unsigned long>(30000, 1000UL << min<unsigned long>(5, (now - _stateSince) / 30000));
        if (now - _stateSince >= delayMs && !_activeSsid.isEmpty()) startWifi(_activeSsid, _activePassword);
    } else if (WiFi.status() != WL_CONNECTED && _state == WifiV2State::ONLINE) {
        _authenticated = false;
        setState(WifiV2State::OFFLINE);
    }

    if (now - _lastStatusAt >= 10000) sendDeviceStatus();
}

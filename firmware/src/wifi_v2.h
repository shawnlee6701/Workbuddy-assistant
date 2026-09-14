#pragma once

#include <Arduino.h>
#include <ArduinoJson.h>
#include <Preferences.h>
#include <WiFi.h>
#include <WiFiUdp.h>
#include <WebSocketsClient.h>

enum class WifiV2State {
    WIFI_NO_CREDENTIALS,
    WIFI_CONNECTING,
    HOST_DISCOVERING,
    WS_AUTHENTICATING,
    ONLINE,
    OFFLINE,
    DEGRADED_SERIAL
};

class WifiV2Manager {
public:
    using SnapshotHandler = void (*)(JsonObjectConst payload);

    void begin(SnapshotHandler handler);
    void loop();
    bool handleUsbCommand(JsonObjectConst command);
    bool handleSerialSnapshot(JsonObjectConst frame);
    void sendKeyPress();
    void clearConfiguration();

    WifiV2State state() const { return _state; }
    bool online() const { return _authenticated; }
    String stateText() const;
    String ipText() const;
    int32_t rssi() const;
    const String& deviceId() const { return _deviceId; }

private:
    static constexpr size_t MAX_FRAME_BYTES = 4096;
    static constexpr uint16_t UDP_PORT = 5202;
    static constexpr uint16_t UDP_LOCAL_PORT = 5203;
    static constexpr uint16_t WS_PORT = 5201;
    static constexpr const char* PROTOCOL_VERSION = "2.0.0";
    static constexpr uint8_t WIFI_SCAN_PASSES = 2;
    static constexpr uint8_t WIFI_SCAN_MAX_RESULTS = 20;

    Preferences _prefs;
    WiFiUDP _udp;
    WebSocketsClient _webSocket;
    SnapshotHandler _snapshotHandler = nullptr;
    WifiV2State _state = WifiV2State::WIFI_NO_CREDENTIALS;

    String _deviceId;
    String _pairingSecret;
    String _serverId;
    String _activeSsid;
    String _activePassword;
    String _activeManualHost;
    String _pendingSsid;
    String _pendingPassword;
    String _pendingManualHost;
    String _pendingRequestId;
    String _nonce;
    String _lastHost;
    String _streamId;
    String _scanRequestId;
    uint64_t _lastSeq = 0;

    String _scanSsids[WIFI_SCAN_MAX_RESULTS];
    int32_t _scanRssi[WIFI_SCAN_MAX_RESULTS] = {};
    wifi_auth_mode_t _scanAuth[WIFI_SCAN_MAX_RESULTS] = {};
    uint8_t _scanResultCount = 0;
    uint8_t _scanPass = 0;

    bool _pendingConfig = false;
    bool _authenticated = false;
    bool _udpStarted = false;
    bool _wsStarted = false;
    bool _scanInProgress = false;
    unsigned long _stateSince = 0;
    unsigned long _lastDiscoveryAt = 0;
    unsigned long _lastStatusAt = 0;
    uint8_t _discoveryStage = 0;
    uint8_t _lastDisconnectReason = 0;

    void setState(WifiV2State state);
    void loadConfiguration();
    void startWifi(const String& ssid, const String& password);
    bool startScanPass();
    void processWifiScan();
    void collectScanResults(int count);
    void finishWifiScan();
    void startDiscovery();
    void sendDiscovery(const IPAddress& target);
    void processDiscoveryResponses();
    void connectWebSocket(const IPAddress& host);
    void onWebSocketEvent(WStype_t type, uint8_t* payload, size_t length);
    void sendAuth();
    void processWebSocketText(const uint8_t* payload, size_t length);
    void acceptSnapshot(JsonObjectConst frame);
    void commitPending();
    void failPending(const char* code, const char* message);
    void restoreActive();
    void failPendingWifiConnection();
    void sendDeviceStatus();
    void sendResponse(JsonDocument& doc);
    void sendSimpleError(const String& requestId, const char* type, const char* code, const char* message);
    String hmacHex(const String& message) const;
    String sha256Prefix(const String& value) const;
    bool constantTimeEquals(const String& left, const String& right) const;
};
